import sys
import subprocess
import traceback
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
from launcher_runtime import stop_registered_targets


ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / ".launch-state.json"


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


def stop_docker_container():
    config = read_env_file(ENV_PATH)
    docker_cmd = config.get("DOCKER_CMD", "").strip()
    container_name = config.get("CONTAINER_NAME", "").strip()

    if not docker_cmd or not container_name:
        log("Docker stop skipped: DOCKER_CMD or CONTAINER_NAME is missing in .env.")
        return

    inspect_result = subprocess.run(
        [docker_cmd, "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    if inspect_result.returncode != 0:
        output = (inspect_result.stderr or inspect_result.stdout or "").strip()
        log(f"Docker inspect skipped for {container_name}: {output}")
        return

    is_running = inspect_result.stdout.strip().lower() == "true"
    if not is_running:
        log(f"Docker container {container_name} is already stopped.")
        return

    log(f"Stopping Docker container {container_name}...")
    stop_result = subprocess.run(
        [docker_cmd, "stop", container_name],
        capture_output=True,
        text=True,
    )
    if stop_result.returncode != 0:
        output = (stop_result.stderr or stop_result.stdout or "").strip()
        log(f"Failed to stop Docker container {container_name}: {output}")
        return

    log(f"Docker container {container_name} stopped.")


def main():
    stop_docker_container()
    stop_registered_targets(STATE_PATH, log)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        traceback.print_exc()
        input("\nPress Enter to close the window...")
        sys.exit(1)
