import csv
import ctypes
import json
import subprocess
import time
from pathlib import Path


WM_CLOSE = 0x0010
USER32 = ctypes.windll.user32


class LaunchRegistry:
    def __init__(self, state_path, logger):
        self.state_path = Path(state_path)
        self.log = logger
        self.state = {
            "processes": [],
            "windows": [],
            "updated_at": time.time(),
        }

    def reset(self):
        self.state = {
            "processes": [],
            "windows": [],
            "updated_at": time.time(),
        }
        self._save()

    def register_process(self, name, popen=None, pid=None, image_path=None, image_name=None):
        resolved_pid = pid if pid is not None else getattr(popen, "pid", None)
        if not resolved_pid:
            return

        entry = {
            "name": name,
            "pid": int(resolved_pid),
            "expected_image": _normalize_image_name(image_path=image_path, image_name=image_name),
        }

        if any(existing["pid"] == entry["pid"] for existing in self.state["processes"]):
            return

        self.state["processes"].append(entry)
        self._save()

    def register_window(self, name, wrapper=None, handle=None, pid=None, image_path=None, image_name=None, title=None):
        resolved_handle = handle if handle is not None else getattr(wrapper, "handle", None)
        if not resolved_handle:
            return

        resolved_pid = pid
        resolved_title = title or ""

        if wrapper is not None:
            try:
                resolved_pid = wrapper.element_info.process_id
            except Exception:
                pass

            try:
                resolved_title = wrapper.window_text() or resolved_title
            except Exception:
                pass

        entry = {
            "name": name,
            "handle": int(resolved_handle),
            "pid": int(resolved_pid) if resolved_pid else None,
            "title": resolved_title,
            "expected_image": _normalize_image_name(image_path=image_path, image_name=image_name),
        }

        if any(existing["handle"] == entry["handle"] for existing in self.state["windows"]):
            return

        self.state["windows"].append(entry)
        self._save()

    def _save(self):
        self.state["updated_at"] = time.time()
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def stop_registered_targets(state_path, logger):
    state_file = Path(state_path)
    if not state_file.exists():
        logger(f"State file not found: {state_file.name}")
        return {"windows_closed": 0, "processes_stopped": 0}

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read state file {state_file}: {exc}") from exc

    windows = state.get("windows", [])
    processes = state.get("processes", [])

    windows_closed = 0
    for entry in windows:
        if _close_registered_window(entry, logger):
            windows_closed += 1

    if windows:
        time.sleep(1)

    processes_stopped = 0
    seen_pids = set()
    for entry in processes:
        pid = entry.get("pid")
        if not pid or pid in seen_pids:
            continue

        seen_pids.add(pid)
        if _stop_registered_process(entry, logger):
            processes_stopped += 1

    state_file.unlink(missing_ok=True)
    logger(
        "Stop completed: "
        f"{windows_closed} windows closed, {processes_stopped} processes stopped."
    )
    return {
        "windows_closed": windows_closed,
        "processes_stopped": processes_stopped,
    }


def _normalize_image_name(image_path=None, image_name=None):
    if image_name:
        return str(image_name).lower()
    if image_path:
        return Path(image_path).name.lower()
    return None


def _close_registered_window(entry, logger):
    handle = entry.get("handle")
    expected_pid = entry.get("pid")
    name = entry.get("name", "window")
    expected_image = entry.get("expected_image")

    if not handle or not USER32.IsWindow(handle):
        logger(f"Skip window {name}: handle is no longer valid.")
        return False

    actual_pid = _get_window_pid(handle)
    if expected_pid and actual_pid != expected_pid:
        logger(f"Skip window {name}: pid mismatch.")
        return False

    if expected_image:
        actual_image = _get_process_image_name(actual_pid)
        if actual_image and actual_image.lower() != expected_image:
            logger(f"Skip window {name}: image mismatch ({actual_image}).")
            return False

    USER32.PostMessageW(handle, WM_CLOSE, 0, 0)
    logger(f"Close signal sent to {name}.")
    return True


def _stop_registered_process(entry, logger):
    pid = entry.get("pid")
    expected_image = entry.get("expected_image")
    name = entry.get("name", "process")

    actual_image = _get_process_image_name(pid)
    if actual_image is None:
        logger(f"Skip process {name}: pid {pid} is not running.")
        return False

    if expected_image and actual_image.lower() != expected_image:
        logger(f"Skip process {name}: image mismatch ({actual_image}).")
        return False

    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        logger(f"Failed to stop {name} (pid {pid}): {output}")
        return False

    logger(f"Stopped {name} (pid {pid}).")
    return True


def _get_window_pid(handle):
    pid = ctypes.c_ulong()
    USER32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return int(pid.value)


def _get_process_image_name(pid):
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    if not output or output.startswith("INFO:"):
        return None

    rows = list(csv.reader([output]))
    if not rows or not rows[0]:
        return None

    return rows[0][0]
