import sys
import traceback
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
from launcher_runtime import stop_registered_targets


STATE_PATH = BASE_DIR / ".launch-state.json"


def log(message):
    print(message, flush=True)


def main():
    stop_registered_targets(STATE_PATH, log)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {exc}")
        traceback.print_exc()
        input("\nPress Enter to close the window...")
        sys.exit(1)
