import socket
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / ".launch-state.json"
COMPOSE_FILE = BASE_DIR / "docker-compose.yml"

from launcher_runtime import LaunchRegistry


DOCKER_CMD = ""
DOCKER_DESKTOP_EXE = ""
COMPOSE_PROJECT_NAME = ""
POSTGRES_SERVICE = ""
PGADMIN_SERVICE = ""
POSTGRES_CONTAINER_NAME = ""
POSTGRES_DB = ""
POSTGRES_USER = ""
POSTGRES_PASSWORD = ""
POSTGRES_PORT = 5432
PGADMIN_EMAIL = ""
PGADMIN_PASSWORD = ""
PGADMIN_PORT = 5050
PGADMIN_URL = ""
DOCKER_READY_TIMEOUT = 180
POSTGRES_READY_TIMEOUT = 90
PGADMIN_READY_TIMEOUT = 60
POLL_INTERVAL = 2.0


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


def load_config():
    global DOCKER_CMD
    global DOCKER_DESKTOP_EXE
    global COMPOSE_PROJECT_NAME
    global POSTGRES_SERVICE
    global PGADMIN_SERVICE
    global POSTGRES_CONTAINER_NAME
    global POSTGRES_DB
    global POSTGRES_USER
    global POSTGRES_PASSWORD
    global POSTGRES_PORT
    global PGADMIN_EMAIL
    global PGADMIN_PASSWORD
    global PGADMIN_PORT
    global PGADMIN_URL
    global DOCKER_READY_TIMEOUT
    global POSTGRES_READY_TIMEOUT
    global PGADMIN_READY_TIMEOUT
    global POLL_INTERVAL

    config = read_env_file(ENV_PATH)

    DOCKER_CMD = require_env(config, "DOCKER_CMD")
    DOCKER_DESKTOP_EXE = require_env(config, "DOCKER_DESKTOP_EXE")
    COMPOSE_PROJECT_NAME = require_env(config, "COMPOSE_PROJECT_NAME")
    POSTGRES_SERVICE = require_env(config, "POSTGRES_SERVICE")
    PGADMIN_SERVICE = require_env(config, "PGADMIN_SERVICE")
    POSTGRES_CONTAINER_NAME = require_env(config, "POSTGRES_CONTAINER_NAME")
    POSTGRES_DB = require_env(config, "POSTGRES_DB")
    POSTGRES_USER = require_env(config, "POSTGRES_USER")
    POSTGRES_PASSWORD = require_env(config, "POSTGRES_PASSWORD")
    POSTGRES_PORT = require_positive_int(config, "POSTGRES_PORT")
    PGADMIN_EMAIL = require_env(config, "PGADMIN_EMAIL")
    PGADMIN_PASSWORD = require_env(config, "PGADMIN_PASSWORD")
    PGADMIN_PORT = require_positive_int(config, "PGADMIN_PORT")
    PGADMIN_URL = require_env(config, "PGADMIN_URL")
    DOCKER_READY_TIMEOUT = require_positive_int(config, "DOCKER_READY_TIMEOUT")
    POSTGRES_READY_TIMEOUT = require_positive_int(config, "POSTGRES_READY_TIMEOUT")
    PGADMIN_READY_TIMEOUT = require_positive_int(config, "PGADMIN_READY_TIMEOUT")
    POLL_INTERVAL = require_positive_float(config, "POLL_INTERVAL")


def validate_paths():
    if not COMPOSE_FILE.exists():
        raise FileNotFoundError(f"Не найден docker-compose.yml: {COMPOSE_FILE}")

    docker_desktop_path = Path(DOCKER_DESKTOP_EXE)
    if not docker_desktop_path.exists():
        raise FileNotFoundError(f"DOCKER_DESKTOP_EXE не найден: {DOCKER_DESKTOP_EXE}")

    docker_cmd_path = Path(DOCKER_CMD)
    if docker_cmd_path.is_absolute() and not docker_cmd_path.exists():
        raise FileNotFoundError(f"DOCKER_CMD не найден: {DOCKER_CMD}")


def run_cli(args, timeout=30):
    return subprocess.run(
        args,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def docker_is_ready():
    result = run_cli([DOCKER_CMD, "info"], timeout=15)
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def wait_for_docker_ready(timeout):
    deadline = time.time() + timeout
    last_error = ""

    while time.time() < deadline:
        try:
            ready, output = docker_is_ready()
        except FileNotFoundError:
            raise RuntimeError(
                "Команда docker не найдена. Проверь PATH или укажи полный путь в DOCKER_CMD."
            )
        except Exception as exc:
            ready = False
            output = str(exc)

        if ready:
            log("Docker готов.")
            return

        last_error = output
        time.sleep(3)

    raise TimeoutError(f"Docker не стал готов за {timeout} сек. Последняя ошибка: {last_error}")


def launch_docker_desktop_if_needed(registry):
    ready, _ = docker_is_ready()
    if ready:
        log("Docker уже запущен.")
        return

    log("Запускаю Docker Desktop...")
    process = subprocess.Popen([DOCKER_DESKTOP_EXE])
    registry.register_process("Docker Desktop", popen=process, image_path=DOCKER_DESKTOP_EXE)
    wait_for_docker_ready(DOCKER_READY_TIMEOUT)


def compose_command(*extra_args):
    return [
        DOCKER_CMD,
        "compose",
        "-p",
        COMPOSE_PROJECT_NAME,
        "-f",
        str(COMPOSE_FILE),
        *extra_args,
    ]


def compose_up():
    log("Поднимаю postgres и pgAdmin через docker compose...")
    result = run_cli(compose_command("up", "-d"), timeout=120)
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Не удалось выполнить docker compose up -d:\n{output}")


def wait_for_postgres_ready(timeout):
    deadline = time.time() + timeout
    last_error = ""
    log("Жду готовности PostgreSQL...")

    while time.time() < deadline:
        result = run_cli(
            [
                DOCKER_CMD,
                "exec",
                POSTGRES_CONTAINER_NAME,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                POSTGRES_USER,
                "-d",
                POSTGRES_DB,
            ],
            timeout=20,
        )
        if result.returncode == 0:
            log("PostgreSQL готов.")
            return

        last_error = (result.stderr or result.stdout or "").strip()
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(
        f"PostgreSQL не стал готов за {timeout} сек. Последняя ошибка: {last_error}"
    )


def wait_for_tcp_port(host, port, timeout, name):
    deadline = time.time() + timeout
    last_error = ""

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                log(f"{name} доступен на {host}:{port}.")
                return
        except OSError as exc:
            last_error = str(exc)
            time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"{name} не стал доступен за {timeout} сек. Последняя ошибка: {last_error}")


def open_pgadmin_in_browser():
    log("Открываю pgAdmin в браузере...")
    opened = webbrowser.open_new_tab(PGADMIN_URL)
    if not opened:
        log(f"Не удалось открыть вкладку автоматически. Открой вручную: {PGADMIN_URL}")


def print_credentials():
    log("Данные для входа в pgAdmin:")
    log(f"  URL: {PGADMIN_URL}")
    log(f"  Email: {PGADMIN_EMAIL}")
    log(f"  Password: {PGADMIN_PASSWORD}")
    log("Дальше в pgAdmin можно добавить сервер PostgreSQL по хосту 'postgres' внутри docker-сети")
    log(f"или по localhost:{POSTGRES_PORT} с логином {POSTGRES_USER}.")


def main():
    load_config()
    validate_paths()

    registry = LaunchRegistry(STATE_PATH, log)
    registry.reset()

    launch_docker_desktop_if_needed(registry)
    compose_up()
    wait_for_postgres_ready(POSTGRES_READY_TIMEOUT)
    wait_for_tcp_port("127.0.0.1", PGADMIN_PORT, PGADMIN_READY_TIMEOUT, "pgAdmin")
    open_pgadmin_in_browser()
    print_credentials()
    log("Готово. Окружение поднято.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ОШИБКА: {exc}")
        traceback.print_exc()
        input("\nНажми Enter, чтобы закрыть окно...")
        sys.exit(1)
