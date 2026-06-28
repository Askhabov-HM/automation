import ctypes
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

from pywinauto import Desktop


BASE_DIR = Path(__file__).resolve().parent
from launcher_runtime import LaunchRegistry


ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / ".launch-state.json"

CHROME_EXE = ""
CHROME_URLS = []
WINDOW_WAIT_TIMEOUT = 60
POLL_INTERVAL = 0.5


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def read_env_file(path):
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    result = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Invalid .env line ({line_number}): {raw_line}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(f"Empty key in .env line {line_number}")

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        result[key] = value

    return result


def require_env(config, key):
    value = config.get(key, "").strip()
    if not value:
        raise ValueError(f"Required .env value is missing: {key}")
    return value


def require_positive_int(config, key):
    raw_value = require_env(config, key)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got: {raw_value}") from exc

    if value <= 0:
        raise ValueError(f"{key} must be greater than 0, got: {value}")

    return value


def require_positive_float(config, key):
    raw_value = require_env(config, key)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, got: {raw_value}") from exc

    if value <= 0:
        raise ValueError(f"{key} must be greater than 0, got: {value}")

    return value


def validate_url(url, key_name):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{key_name} must be a valid http/https URL, got: {url}")


def load_chrome_urls(config):
    entries = []
    prefix = "CHROME_URL_"

    for key, value in config.items():
        if not key.startswith(prefix):
            continue

        suffix = key[len(prefix) :]
        if not suffix.isdigit():
            continue

        url = value.strip()
        validate_url(url, key)
        entries.append((int(suffix), url))

    entries.sort()

    if not entries:
        raise ValueError("No CHROME_URL_N values were found in .env.")

    return [url for _, url in entries]


def load_config():
    global CHROME_EXE
    global CHROME_URLS
    global WINDOW_WAIT_TIMEOUT
    global POLL_INTERVAL

    config = read_env_file(ENV_PATH)

    CHROME_EXE = require_env(config, "CHROME_EXE")
    CHROME_URLS = load_chrome_urls(config)
    WINDOW_WAIT_TIMEOUT = require_positive_int(config, "WINDOW_WAIT_TIMEOUT")
    POLL_INTERVAL = require_positive_float(config, "POLL_INTERVAL")


def validate_paths():
    if not Path(CHROME_EXE).exists():
        raise FileNotFoundError(f"CHROME_EXE not found: {CHROME_EXE}")


def enable_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_work_area():
    rect = RECT()
    spi_getworkarea = 0x0030
    ok = ctypes.windll.user32.SystemParametersInfoW(
        spi_getworkarea, 0, ctypes.byref(rect), 0
    )
    if not ok:
        raise RuntimeError("Could not read the Windows work area.")
    return rect.left, rect.top, rect.right, rect.bottom


def list_visible_windows():
    desktop = Desktop(backend="win32")
    result = []

    for wrapper in desktop.windows():
        try:
            if not wrapper.is_visible():
                continue

            result.append(
                {
                    "wrapper": wrapper,
                    "handle": wrapper.handle,
                    "title": wrapper.window_text() or "",
                    "class_name": wrapper.class_name() or "",
                    "pid": wrapper.element_info.process_id,
                }
            )
        except Exception:
            continue

    return result


def current_handles(filter_func=None):
    handles = set()
    for info in list_visible_windows():
        try:
            if filter_func is None or filter_func(info):
                handles.add(info["handle"])
        except Exception:
            continue
    return handles


def wait_for_window(predicate, timeout=None, description="window"):
    timeout = timeout or WINDOW_WAIT_TIMEOUT
    deadline = time.time() + timeout

    while time.time() < deadline:
        for info in list_visible_windows():
            try:
                if predicate(info):
                    return info["wrapper"]
            except Exception:
                continue
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Timed out waiting for {description}")


def safe_restore(wrapper):
    try:
        wrapper.restore()
        time.sleep(0.3)
    except Exception:
        pass


def maximize_chrome_window(wrapper):
    try:
        wrapper.set_focus()
    except Exception:
        pass

    try:
        wrapper.maximize()
        time.sleep(0.5)
        log("Chrome window maximized.")
        return
    except Exception as exc:
        log(f"Could not maximize Chrome directly: {exc}")

    try:
        left, top, right, bottom = get_work_area()
        safe_restore(wrapper)
        wrapper.move_window(left, top, right - left, bottom - top, repaint=True)
        log("Chrome window moved to the full work area.")
    except Exception as exc:
        log(f"Could not place Chrome on the full work area: {exc}")


def launch_chrome_window():
    log("Opening Chrome job workspace...")

    before_handles = current_handles(
        lambda info: info["class_name"] == "Chrome_WidgetWin_1"
    )

    chrome_process = subprocess.Popen(
        [CHROME_EXE, "--new-window", "--start-maximized", *CHROME_URLS]
    )

    chrome_window = wait_for_window(
        lambda info: (
            info["class_name"] == "Chrome_WidgetWin_1"
            and info["handle"] not in before_handles
        ),
        timeout=45,
        description="new Chrome window",
    )

    time.sleep(2)
    return chrome_process, chrome_window


def main():
    load_config()
    enable_dpi_awareness()
    validate_paths()

    registry = LaunchRegistry(STATE_PATH, log)
    registry.reset()

    chrome_process, chrome_window = launch_chrome_window()
    registry.register_process("Chrome job BA launcher", popen=chrome_process, image_path=CHROME_EXE)
    registry.register_window("Chrome job BA window", wrapper=chrome_window, image_path=CHROME_EXE)

    maximize_chrome_window(chrome_window)

    log("Done. start_job_as_BA workspace is ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        traceback.print_exc()
        input("\nPress Enter to close the window...")
        sys.exit(1)
