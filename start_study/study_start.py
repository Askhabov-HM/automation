import ctypes
import re
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
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
FORBIDDEN_CMD_TITLE_CHARS = set('&|<>^%"')


# =========================
# КОНФИГ
# =========================
FOXIT_EXE = ""
PDF_PATH = ""
CHROME_EXE = ""
CHROME_URLS = []
NEKORAY_EXE = ""
DOCKER_DESKTOP_EXE = ""
DOCKER_CMD = ""
CONTAINER_NAME = ""
DB_NAME = ""
DB_USER = ""
DB_HOST = ""
DB_PORT = 5432
CMD_WINDOW_TITLE = ""
WIFI_PRIMARY_SSID = ""
WIFI_SECONDARY_SSID = ""
WIFI_CONNECT_TIMEOUT = 15
WIFI_PARSE_WARNING_INTERVAL = 30
LAST_WIFI_PARSE_WARNING_AT = 0
DOCKER_READY_TIMEOUT = 180
POSTGRES_READY_TIMEOUT = 60
WINDOW_WAIT_TIMEOUT = 60
POLL_INTERVAL = 0.5


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


def load_chrome_urls(config):
    entries = []
    prefix = "CHROME_URL_"

    for key, value in config.items():
        if not key.startswith(prefix):
            continue

        suffix = key[len(prefix) :]
        if not suffix.isdigit():
            continue

        entries.append((int(suffix), value.strip()))

    entries.sort()

    if not entries:
        raise ValueError("В .env не найдено ни одного CHROME_URL_N.")

    urls = []
    for index, url in entries:
        validate_url(url, f"CHROME_URL_{index}")
        urls.append(url)

    return urls


def validate_url(url, key_name):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{key_name} должен быть корректным http/https URL, получено: {url}")


def validate_cmd_window_title(title):
    invalid_chars = sorted({char for char in title if char in FORBIDDEN_CMD_TITLE_CHARS})
    if invalid_chars:
        chars = " ".join(invalid_chars)
        raise ValueError(
            f"CMD_WINDOW_TITLE содержит опасные символы для cmd.exe: {chars}"
        )


def load_config():
    global FOXIT_EXE
    global PDF_PATH
    global CHROME_EXE
    global CHROME_URLS
    global NEKORAY_EXE
    global DOCKER_DESKTOP_EXE
    global DOCKER_CMD
    global CONTAINER_NAME
    global DB_NAME
    global DB_USER
    global DB_HOST
    global DB_PORT
    global CMD_WINDOW_TITLE
    global WIFI_PRIMARY_SSID
    global WIFI_SECONDARY_SSID
    global WIFI_CONNECT_TIMEOUT
    global DOCKER_READY_TIMEOUT
    global POSTGRES_READY_TIMEOUT
    global WINDOW_WAIT_TIMEOUT
    global POLL_INTERVAL

    config = read_env_file(ENV_PATH)

    FOXIT_EXE = require_env(config, "FOXIT_EXE")
    PDF_PATH = require_env(config, "PDF_PATH")
    CHROME_EXE = require_env(config, "CHROME_EXE")
    CHROME_URLS = load_chrome_urls(config)
    NEKORAY_EXE = require_env(config, "NEKORAY_EXE")
    DOCKER_DESKTOP_EXE = require_env(config, "DOCKER_DESKTOP_EXE")
    DOCKER_CMD = require_env(config, "DOCKER_CMD")
    CONTAINER_NAME = require_env(config, "CONTAINER_NAME")
    DB_NAME = require_env(config, "DB_NAME")
    DB_USER = require_env(config, "DB_USER")
    DB_HOST = require_env(config, "DB_HOST")
    DB_PORT = require_positive_int(config, "DB_PORT")
    CMD_WINDOW_TITLE = require_env(config, "CMD_WINDOW_TITLE")
    WIFI_PRIMARY_SSID = require_env(config, "WIFI_PRIMARY_SSID")
    WIFI_SECONDARY_SSID = require_env(config, "WIFI_SECONDARY_SSID")
    WIFI_CONNECT_TIMEOUT = require_positive_int(config, "WIFI_CONNECT_TIMEOUT")
    DOCKER_READY_TIMEOUT = require_positive_int(config, "DOCKER_READY_TIMEOUT")
    POSTGRES_READY_TIMEOUT = require_positive_int(config, "POSTGRES_READY_TIMEOUT")
    WINDOW_WAIT_TIMEOUT = require_positive_int(config, "WINDOW_WAIT_TIMEOUT")
    POLL_INTERVAL = require_positive_float(config, "POLL_INTERVAL")

    validate_cmd_window_title(CMD_WINDOW_TITLE)


# =========================
# WIN API / DPI
# =========================
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def enable_dpi_awareness():
    """Чтобы координаты окон были корректными на 4K / 125%."""
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
    """Рабочая область основного монитора без панели задач."""
    rect = RECT()
    SPI_GETWORKAREA = 0x0030
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
    )
    if not ok:
        raise RuntimeError("Не удалось получить рабочую область экрана.")
    return rect.left, rect.top, rect.right, rect.bottom


# =========================
# ЛОГИ
# =========================
def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# =========================
# ПРОВЕРКИ
# =========================
def validate_paths():
    paths = [
        ("FOXIT_EXE", FOXIT_EXE),
        ("PDF_PATH", PDF_PATH),
        ("CHROME_EXE", CHROME_EXE),
        ("NEKORAY_EXE", NEKORAY_EXE),
        ("DOCKER_DESKTOP_EXE", DOCKER_DESKTOP_EXE),
    ]
    for name, path in paths:
        if not Path(path).exists():
            raise FileNotFoundError(f"{name} не найден: {path}")

    docker_path = Path(DOCKER_CMD)
    if docker_path.is_absolute() and not docker_path.exists():
        raise FileNotFoundError(f"DOCKER_CMD не найден: {DOCKER_CMD}")


# =========================
# ОКНА
# =========================
def run_netsh_command(args, timeout=15):
    return subprocess.run(
        args,
        capture_output=True,
        text=False,
        timeout=timeout,
    )


def decode_command_output(data):
    if not data:
        return ""

    encodings = []
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff") or b"\x00" in data:
        encodings.extend(("utf-16", "utf-16-le", "utf-16-be"))
    if data.startswith(b"\xef\xbb\xbf"):
        encodings.append("utf-8-sig")

    encodings.extend(("utf-8", "cp866", "cp1251", "latin-1"))

    for encoding in encodings:
        try:
            return data.decode(encoding).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="ignore").replace("\x00", "")


def normalize_wifi_state(value):
    normalized = (value or "").strip().lower()
    mapping = {
        "connected": "connected",
        "disconnected": "disconnected",
        "connecting": "connecting",
        "disconnecting": "disconnecting",
        "authenticating": "authenticating",
        "discovering": "discovering",
        "associating": "associating",
        "подключено": "connected",
        "не подключено": "disconnected",
        "отключено": "disconnected",
        "подключение": "connecting",
        "отключение": "disconnecting",
        "проверка подлинности": "authenticating",
        "обнаружение": "discovering",
        "связывание": "associating",
    }
    return mapping.get(normalized, normalized or None)


def normalize_wifi_label(value):
    return " ".join((value or "").strip().lower().split())


def maybe_log_unparsed_wifi_output(output):
    global LAST_WIFI_PARSE_WARNING_AT

    now = time.time()
    if now - LAST_WIFI_PARSE_WARNING_AT < WIFI_PARSE_WARNING_INTERVAL:
        return

    LAST_WIFI_PARSE_WARNING_AT = now
    snippet = (output or "").strip()
    if not snippet:
        log("Wi-Fi parse warning: netsh returned empty output.")
        return

    log(f"Wi-Fi parse warning: could not extract state/ssid from netsh output:\n{snippet}")


def get_wifi_status():
    try:
        result = run_netsh_command(["netsh", "wlan", "show", "interfaces"], timeout=10)
    except FileNotFoundError:
        log("Wi-Fi check skipped: netsh is not available.")
        return {"state": None, "ssid": None}
    except Exception as exc:
        log(f"Wi-Fi check failed: {exc}")
        return {"state": None, "ssid": None}

    output = decode_command_output(result.stdout or result.stderr)
    status = {"state": None, "ssid": None}
    for line in output.splitlines():
        if ":" not in line:
            continue

        label, _, raw_value = line.partition(":")
        label = normalize_wifi_label(label)
        value = raw_value.strip()
        if not value:
            continue

        if label in {"state", "состояние"}:
            state = normalize_wifi_state(value)
            if state:
                status["state"] = state
            continue

        if label == "имя ssid" or label.startswith("ssid"):
            status["ssid"] = value

    if result.returncode != 0:
        log(
            "Wi-Fi check command returned a non-zero exit code: "
            f"{result.returncode}. Output: {output.strip()}"
        )
    elif status["state"] is None and status["ssid"] is None:
        maybe_log_unparsed_wifi_output(output)

    return status


def get_current_wifi_ssid():
    return get_wifi_status()["ssid"]


def summarize_wifi_status(status):
    state = status.get("state") or "unknown"
    ssid = status.get("ssid") or "none"
    return f"state={state}, ssid={ssid}"


def wait_for_allowed_wifi(targets, timeout):
    deadline = time.time() + timeout
    last_status = {"state": None, "ssid": None}
    stable_reads = 0

    while time.time() < deadline:
        status = get_wifi_status()
        last_status = status

        if status.get("state") == "connected" and status.get("ssid") in targets:
            stable_reads += 1
            if stable_reads >= 2:
                return status
        else:
            stable_reads = 0

        time.sleep(1)

    return last_status


def connect_to_wifi(ssid, timeout=None):
    timeout = timeout or WIFI_CONNECT_TIMEOUT
    log(f"Trying Wi-Fi: {ssid}")

    try:
        result = run_netsh_command(
            ["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"],
            timeout=15,
        )
    except FileNotFoundError:
        log("Wi-Fi connect skipped: netsh is not available.")
        return False
    except Exception as exc:
        log(f"Wi-Fi connect failed for {ssid}: {exc}")
        return False

    command_output = decode_command_output(result.stdout or result.stderr).strip()
    if command_output:
        log(f"netsh connect output for {ssid}: {command_output}")

    status = wait_for_allowed_wifi({ssid}, timeout + 3)
    if status.get("state") == "connected" and status.get("ssid") == ssid:
        log(f"Connected to Wi-Fi: {ssid}")
        return True

    log(
        f"Wi-Fi did not switch to {ssid} within {timeout} seconds. "
        f"Last status: {summarize_wifi_status(status)}"
    )
    return False


def ensure_wifi_connection():
    targets = list(dict.fromkeys([WIFI_PRIMARY_SSID, WIFI_SECONDARY_SSID]))
    allowed_targets = set(targets)

    current_status = get_wifi_status()
    current_ssid = current_status.get("ssid")
    if current_ssid:
        log(f"Wi-Fi already connected. Keeping current network: {current_ssid}")
        return

    log(
        "Current Wi-Fi before reconnect: "
        f"{summarize_wifi_status(current_status)}"
    )

    for ssid in targets:
        current_status = get_wifi_status()
        current_ssid = current_status.get("ssid")
        if current_ssid:
            log(f"Wi-Fi became connected during checks. Keeping network: {current_ssid}")
            return

        if current_ssid == ssid:
            log(f"Wi-Fi already connected to allowed network: {ssid}")
            return

        if connect_to_wifi(ssid):
            return

        grace_status = wait_for_allowed_wifi(allowed_targets, 5)
        if grace_status.get("state") == "connected" and grace_status.get("ssid") in allowed_targets:
            log(
                "Wi-Fi connected during fallback grace period: "
                f"{grace_status.get('ssid')}"
            )
            return

    final_status = get_wifi_status()
    final_ssid = final_status.get("ssid")
    if final_status.get("state") == "connected" and final_ssid:
        log(f"Wi-Fi fallback failed. Continuing with current network: {final_ssid}")
    else:
        log(
            "Wi-Fi fallback failed. Continuing without an active Wi-Fi connection. "
            f"Last status: {summarize_wifi_status(final_status)}"
        )


def list_visible_windows():
    desktop = Desktop(backend="win32")
    result = []

    for wrapper in desktop.windows():
        try:
            if not wrapper.is_visible():
                continue

            info = {
                "wrapper": wrapper,
                "handle": wrapper.handle,
                "title": wrapper.window_text() or "",
                "class_name": wrapper.class_name() or "",
                "pid": wrapper.element_info.process_id,
            }
            result.append(info)
        except Exception:
            # Окно могло исчезнуть прямо во время обхода
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


def safe_minimize(wrapper, name):
    try:
        wrapper.minimize()
        log(f"Свернул: {name}")
    except Exception as e:
        log(f"Не удалось свернуть {name}: {e}")


def safe_move(wrapper, x, y, width, height, name):
    try:
        safe_restore(wrapper)
        wrapper.move_window(x, y, width, height, repaint=True)
        log(f"Разместил: {name}")
    except Exception as e:
        log(f"Не удалось разместить {name}: {e}")


# =========================
# DOCKER
# =========================
def run_cli(args, timeout=20):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def wait_for_docker_ready(timeout=DOCKER_READY_TIMEOUT):
    deadline = time.time() + timeout
    last_error = ""

    while time.time() < deadline:
        try:
            result = run_cli([DOCKER_CMD, "info"], timeout=15)
            if result.returncode == 0:
                log("Docker готов.")
                return
            last_error = (result.stderr or result.stdout or "").strip()
        except FileNotFoundError:
            raise RuntimeError(
                "Команда docker не найдена. Проверь PATH или укажи полный путь в DOCKER_CMD."
            )
        except Exception as e:
            last_error = str(e)

        time.sleep(3)

    raise TimeoutError(f"Docker не стал готов за {timeout} сек. Последняя ошибка: {last_error}")


def ensure_container_running(container_name):
    inspect_result = run_cli(
        [DOCKER_CMD, "inspect", "-f", "{{.State.Running}}", container_name], timeout=15
    )

    if inspect_result.returncode != 0:
        raise RuntimeError(
            f"Не удалось проверить контейнер {container_name}:\n"
            f"{inspect_result.stderr or inspect_result.stdout}"
        )

    running = inspect_result.stdout.strip().lower() == "true"

    if running:
        log(f"Контейнер {container_name} уже запущен.")
        return

    log(f"Запускаю контейнер {container_name}...")
    start_result = run_cli([DOCKER_CMD, "start", container_name], timeout=30)

    if start_result.returncode != 0:
        raise RuntimeError(
            f"Не удалось запустить контейнер {container_name}:\n"
            f"{start_result.stderr or start_result.stdout}"
        )

    log(f"Контейнер {container_name} запущен.")


def wait_for_postgres_ready(timeout=POSTGRES_READY_TIMEOUT):
    deadline = time.time() + timeout
    last_error = ""

    log("Жду готовности PostgreSQL...")

    while time.time() < deadline:
        result = run_cli(
            [
                DOCKER_CMD,
                "exec",
                CONTAINER_NAME,
                "pg_isready",
                "-h",
                DB_HOST,
                "-p",
                str(DB_PORT),
                "-U",
                DB_USER,
                "-d",
                DB_NAME,
            ],
            timeout=15,
        )

        if result.returncode == 0:
            log("PostgreSQL готов.")
            return

        last_error = (result.stderr or result.stdout or "").strip()
        time.sleep(2)

    raise TimeoutError(
        f"PostgreSQL не стал готов за {timeout} сек. Последняя ошибка: {last_error}"
    )


# =========================
# ЗАПУСК ПРОГРАММ
# =========================
def launch_nekoray():
    log("Запуск NekoRay...")
    return subprocess.Popen([NEKORAY_EXE])


def launch_docker_desktop():
    log("Запуск Docker Desktop...")
    return subprocess.Popen([DOCKER_DESKTOP_EXE])


def launch_psql_cmd():
    log("Запуск cmd с psql...")

    docker_exec_cmd = subprocess.list2cmdline(
        [
            DOCKER_CMD,
            "exec",
            "-it",
            CONTAINER_NAME,
            "psql",
            "-h",
            DB_HOST,
            "-p",
            str(DB_PORT),
            "-d",
            DB_NAME,
            "-U",
            DB_USER,
        ]
    )
    title_cmd = subprocess.list2cmdline(["title", CMD_WINDOW_TITLE])
    cmd_command = f"{title_cmd} && {docker_exec_cmd}"

    cmd_process = subprocess.Popen(
        ["cmd.exe", "/k", cmd_command],
        creationflags=CREATE_NEW_CONSOLE,
    )

    cmd_window = wait_for_window(
        lambda info: CMD_WINDOW_TITLE.lower() in info["title"].lower(),
        timeout=30,
        description="cmd с psql",
    )

    # Небольшая пауза, чтобы psql успел стартовать
    time.sleep(2)
    return cmd_process, cmd_window


def launch_chrome_new_window():
    log("Открытие Chrome...")

    before_handles = current_handles(
        lambda info: info["class_name"] == "Chrome_WidgetWin_1"
    )

    chrome_process = subprocess.Popen([CHROME_EXE, "--new-window", *CHROME_URLS])

    chrome_window = wait_for_window(
        lambda info: (
            info["class_name"] == "Chrome_WidgetWin_1"
            and info["handle"] not in before_handles
        ),
        timeout=45,
        description="новое окно Chrome",
    )

    time.sleep(2)
    return chrome_process, chrome_window


def open_pdf_in_foxit():
    log("Открытие PDF в Foxit...")
    foxit_process = subprocess.Popen([FOXIT_EXE, PDF_PATH])

    pdf_name = Path(PDF_PATH).name.lower()
    pdf_stem = Path(PDF_PATH).stem.lower()

    foxit_window = wait_for_window(
        lambda info: (
            pdf_name in info["title"].lower()
            or (pdf_stem in info["title"].lower() and "foxit" in info["title"].lower())
        ),
        timeout=45,
        description=f"окно Foxit с {pdf_name}",
    )

    time.sleep(1)
    return foxit_process, foxit_window


def try_minimize_docker_window():
    try:
        docker_window = wait_for_window(
            lambda info: "docker desktop" in info["title"].lower(),
            timeout=20,
            description="окно Docker Desktop",
        )
        safe_minimize(docker_window, "Docker Desktop")
        return docker_window
    except Exception as e:
        log(f"Окно Docker Desktop не нашёл для сворачивания: {e}")
        return None


# =========================
# РАСКЛАДКА
# =========================
def arrange_windows(chrome_window, foxit_window):
    left, top, right, bottom = get_work_area()
    total_width = right - left
    total_height = bottom - top

    left_width = total_width // 2
    right_width = total_width - left_width

    log("Раскладываю окна...")

    safe_move(
        chrome_window,
        left,
        top,
        left_width,
        total_height,
        "Chrome слева",
    )

    safe_move(
        foxit_window,
        left + left_width,
        top,
        right_width,
        total_height,
        "Foxit справа",
    )


# =========================
# MAIN
# =========================
def main():
    load_config()
    ensure_wifi_connection()
    enable_dpi_awareness()
    validate_paths()

    registry = LaunchRegistry(STATE_PATH, log)
    registry.reset()

    nekoray_process = launch_nekoray()
    registry.register_process("NekoRay", popen=nekoray_process, image_path=NEKORAY_EXE)

    docker_process = launch_docker_desktop()
    registry.register_process("Docker Desktop", popen=docker_process, image_path=DOCKER_DESKTOP_EXE)
    log("Жду готовности Docker...")
    wait_for_docker_ready()

    ensure_container_running(CONTAINER_NAME)
    wait_for_postgres_ready()

    cmd_process, cmd_window = launch_psql_cmd()
    registry.register_process("cmd / psql", popen=cmd_process, image_name="cmd.exe")
    registry.register_window("cmd / psql window", wrapper=cmd_window, image_name="cmd.exe")
    safe_minimize(cmd_window, "cmd / psql")

    foxit_process, foxit_window = open_pdf_in_foxit()
    registry.register_process("Foxit", popen=foxit_process, image_path=FOXIT_EXE)
    registry.register_window("Foxit window", wrapper=foxit_window, image_path=FOXIT_EXE)

    chrome_process, chrome_window = launch_chrome_new_window()
    registry.register_process("Chrome launcher", popen=chrome_process, image_path=CHROME_EXE)
    registry.register_window("Chrome window", wrapper=chrome_window, image_path=CHROME_EXE)

    arrange_windows(chrome_window, foxit_window)
    docker_window = try_minimize_docker_window()
    if docker_window is not None:
        registry.register_window("Docker Desktop window", wrapper=docker_window, image_path=DOCKER_DESKTOP_EXE)

    log("Готово. Сценарий завершён.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА: {e}")
        traceback.print_exc()
        input("\nНажми Enter, чтобы закрыть окно...")
        sys.exit(1)
