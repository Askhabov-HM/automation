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
CMD_WINDOW_TITLE = ""
DOCKER_READY_TIMEOUT = 180
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
    global CMD_WINDOW_TITLE
    global DOCKER_READY_TIMEOUT
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
    CMD_WINDOW_TITLE = require_env(config, "CMD_WINDOW_TITLE")
    DOCKER_READY_TIMEOUT = require_positive_int(config, "DOCKER_READY_TIMEOUT")
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


# =========================
# ЗАПУСК ПРОГРАММ
# =========================
def launch_nekoray():
    log("Запуск NekoRay...")
    subprocess.Popen([NEKORAY_EXE])


def launch_docker_desktop():
    log("Запуск Docker Desktop...")
    subprocess.Popen([DOCKER_DESKTOP_EXE])


def launch_psql_cmd():
    log("Запуск cmd с psql...")

    docker_exec_cmd = subprocess.list2cmdline(
        [DOCKER_CMD, "exec", "-it", CONTAINER_NAME, "psql", "-d", DB_NAME, "-U", DB_USER]
    )
    title_cmd = subprocess.list2cmdline(["title", CMD_WINDOW_TITLE])
    cmd_command = f"{title_cmd} && {docker_exec_cmd}"

    subprocess.Popen(
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
    return cmd_window


def launch_chrome_new_window():
    log("Открытие Chrome...")

    before_handles = current_handles(
        lambda info: info["class_name"] == "Chrome_WidgetWin_1"
    )

    subprocess.Popen([CHROME_EXE, "--new-window", *CHROME_URLS])

    chrome_window = wait_for_window(
        lambda info: (
            info["class_name"] == "Chrome_WidgetWin_1"
            and info["handle"] not in before_handles
        ),
        timeout=45,
        description="новое окно Chrome",
    )

    time.sleep(2)
    return chrome_window


def open_pdf_in_foxit():
    log("Открытие PDF в Foxit...")
    subprocess.Popen([FOXIT_EXE, PDF_PATH])

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
    return foxit_window


def try_minimize_docker_window():
    try:
        docker_window = wait_for_window(
            lambda info: "docker desktop" in info["title"].lower(),
            timeout=20,
            description="окно Docker Desktop",
        )
        safe_minimize(docker_window, "Docker Desktop")
    except Exception as e:
        log(f"Окно Docker Desktop не нашёл для сворачивания: {e}")


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
    enable_dpi_awareness()
    validate_paths()

    launch_nekoray()

    launch_docker_desktop()
    log("Жду готовности Docker...")
    wait_for_docker_ready()

    ensure_container_running(CONTAINER_NAME)

    cmd_window = launch_psql_cmd()
    safe_minimize(cmd_window, "cmd / psql")

    foxit_window = open_pdf_in_foxit()
    chrome_window = launch_chrome_new_window()

    arrange_windows(chrome_window, foxit_window)
    try_minimize_docker_window()

    log("Готово. Сценарий завершён.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ОШИБКА: {e}")
        traceback.print_exc()
        input("\nНажми Enter, чтобы закрыть окно...")
        sys.exit(1)
