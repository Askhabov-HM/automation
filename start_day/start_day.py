import ctypes
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

from pywinauto import Desktop


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
WINDOW_WAIT_TIMEOUT = 60
POLL_INTERVAL = 0.5

CHROME_EXE = ""
NEKORAY_EXE = ""
LEFT_WINDOW_URLS = []
RIGHT_WINDOW_URLS = []


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
        raise FileNotFoundError(f"Файл конфигурации не найден: {path}")

    result = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Некорректная строка в .env ({line_number}): {raw_line}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(f"Пустой ключ в .env ({line_number})")

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        result[key] = value

    return result


def require_env(config, key):
    value = config.get(key, "").strip()
    if not value:
        raise ValueError(f"В .env отсутствует обязательное значение: {key}")
    return value


def require_positive_int(config, key):
    raw_value = require_env(config, key)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} должен быть целым числом, получено: {raw_value}") from exc

    if value <= 0:
        raise ValueError(f"{key} должен быть больше 0, получено: {value}")

    return value


def require_positive_float(config, key):
    raw_value = require_env(config, key)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} должен быть числом, получено: {raw_value}") from exc

    if value <= 0:
        raise ValueError(f"{key} должен быть больше 0, получено: {value}")

    return value


def validate_url(url, key_name):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{key_name} должен быть корректным http/https URL, получено: {url}")


def load_url_group(config, prefix):
    entries = []
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
    urls = [url for _, url in entries]

    if not urls:
        raise ValueError(f"В .env не найдено ни одного URL для группы {prefix}")

    return urls


def load_config():
    global CHROME_EXE
    global NEKORAY_EXE
    global LEFT_WINDOW_URLS
    global RIGHT_WINDOW_URLS
    global WINDOW_WAIT_TIMEOUT
    global POLL_INTERVAL

    config = read_env_file(ENV_PATH)

    CHROME_EXE = require_env(config, "CHROME_EXE")
    NEKORAY_EXE = require_env(config, "NEKORAY_EXE")
    LEFT_WINDOW_URLS = load_url_group(config, "LEFT_WINDOW_URL_")
    RIGHT_WINDOW_URLS = load_url_group(config, "RIGHT_WINDOW_URL_")
    WINDOW_WAIT_TIMEOUT = require_positive_int(config, "WINDOW_WAIT_TIMEOUT")
    POLL_INTERVAL = require_positive_float(config, "POLL_INTERVAL")


def validate_paths():
    paths = [
        ("CHROME_EXE", CHROME_EXE),
        ("NEKORAY_EXE", NEKORAY_EXE),
    ]
    for name, path in paths:
        if not Path(path).exists():
            raise FileNotFoundError(f"{name} не найден: {path}")


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
        raise RuntimeError("Не удалось получить рабочую область экрана.")
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


def wait_for_window(predicate, timeout=WINDOW_WAIT_TIMEOUT, description="окно"):
    deadline = time.time() + timeout

    while time.time() < deadline:
        for info in list_visible_windows():
            try:
                if predicate(info):
                    return info["wrapper"]
            except Exception:
                continue
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Не удалось дождаться: {description}")


def safe_restore(wrapper):
    try:
        wrapper.restore()
        time.sleep(0.3)
    except Exception:
        pass


def safe_move(wrapper, x, y, width, height, name):
    try:
        safe_restore(wrapper)
        wrapper.move_window(x, y, width, height, repaint=True)
        log(f"Разместил: {name}")
    except Exception as e:
        log(f"Не удалось разместить {name}: {e}")


def launch_nekoray():
    log("Запуск NekoRay...")
    subprocess.Popen([NEKORAY_EXE])


def launch_chrome_window(urls, description):
    log(f"Открытие Chrome: {description}...")

    before_handles = current_handles(
        lambda info: info["class_name"] == "Chrome_WidgetWin_1"
    )

    subprocess.Popen([CHROME_EXE, "--new-window", *urls])

    chrome_window = wait_for_window(
        lambda info: (
            info["class_name"] == "Chrome_WidgetWin_1"
            and info["handle"] not in before_handles
        ),
        timeout=45,
        description=description,
    )

    time.sleep(2)
    return chrome_window


def arrange_windows(left_window, right_window):
    left, top, right, bottom = get_work_area()
    total_width = right - left
    total_height = bottom - top

    left_width = total_width // 2
    right_width = total_width - left_width

    log("Раскладываю окна Chrome...")

    safe_move(
        left_window,
        left,
        top,
        left_width,
        total_height,
        "Chrome слева",
    )

    safe_move(
        right_window,
        left + left_width,
        top,
        right_width,
        total_height,
        "Chrome справа",
    )


def main():
    load_config()
    enable_dpi_awareness()
    validate_paths()

    launch_nekoray()

    left_window = launch_chrome_window(
        LEFT_WINDOW_URLS,
        "левое окно Chrome",
    )
    right_window = launch_chrome_window(
        RIGHT_WINDOW_URLS,
        "правое окно Chrome",
    )

    arrange_windows(left_window, right_window)

    log("Готово. Сценарий start_day завершён.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА: {e}")
        traceback.print_exc()
        input("\nНажми Enter, чтобы закрыть окно...")
        sys.exit(1)
