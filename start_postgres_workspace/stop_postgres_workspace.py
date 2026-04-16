import subprocess
import sys
import traceback
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / ".launch-state.json"
COMPOSE_FILE = BASE_DIR / "docker-compose.yml"

from launcher_runtime import stop_registered_targets


def log(message):
    print(message, flush=True)


def read_env_file(path):
    if not path.exists():
        return {}

    result = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if key:
            result[key] = value

    return result


def compose_down():
    config = read_env_file(ENV_PATH)
    docker_cmd = config.get("DOCKER_CMD", "").strip()
    project_name = config.get("COMPOSE_PROJECT_NAME", "").strip()

    if not docker_cmd or not project_name:
        log("Docker compose stop skipped: DOCKER_CMD or COMPOSE_PROJECT_NAME is missing in .env.")
        return

    if not COMPOSE_FILE.exists():
        log(f"Docker compose stop skipped: compose file not found: {COMPOSE_FILE}")
        return

    log("Stopping postgres and pgAdmin compose stack...")
    result = subprocess.run(
        [
            docker_cmd,
            "compose",
            "-p",
            project_name,
            "-f",
            str(COMPOSE_FILE),
            "down",
        ],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        log(f"Failed to stop docker compose stack: {output}")
        return

    log("Docker compose stack stopped.")


def main():
    compose_down()
    stop_registered_targets(STATE_PATH, log)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        traceback.print_exc()
        input("\nPress Enter to close the window...")
        sys.exit(1)
