#!/usr/bin/env python3
"""Add local-only Git ignore entries to .git/info/exclude."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SECTION_HEADER = "# Codex local excludes"


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def repo_root() -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"])).resolve()


def exclude_path() -> Path:
    return Path(run_git(["rev-parse", "--git-path", "info/exclude"])).resolve()


def normalize_entry(raw: str, root: Path) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("empty path is not allowed")
    if "\n" in value or "\r" in value:
        raise ValueError(f"path contains a newline: {raw!r}")
    if value.startswith("#") or value == "!":
        raise ValueError(f"not a file or folder path: {raw!r}")

    value = value.replace("\\", "/")
    is_folder_hint = value.endswith("/")

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"absolute path is outside this repository: {raw}") from exc
        value = relative.as_posix()
    else:
        value = value.removeprefix("./")
        candidate = root / value

    if candidate.exists() and candidate.is_dir():
        is_folder_hint = True

    value = value.strip("/")
    if not value:
        raise ValueError(f"path resolves to repository root: {raw!r}")
    if is_folder_hint and not value.endswith("/"):
        value += "/"
    return value


def update_exclude(path: Path, entries: list[str]) -> tuple[list[str], list[str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines()
    existing = {line.strip() for line in lines if line.strip()}

    added: list[str] = []
    already_present: list[str] = []
    for entry in entries:
        if entry in existing:
            already_present.append(entry)
        else:
            added.append(entry)
            existing.add(entry)

    if not added:
        return added, already_present

    output_lines = list(lines)
    if output_lines and output_lines[-1].strip():
        output_lines.append("")
    if SECTION_HEADER not in existing:
        output_lines.append(SECTION_HEADER)
    output_lines.extend(added)
    path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return added, already_present


def tracked_matches(entries: list[str]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    for entry in entries:
        pathspec = entry.rstrip("/") if entry.endswith("/") else entry
        result = subprocess.run(
            ["git", "ls-files", "--", pathspec],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        files = [line for line in result.stdout.splitlines() if line.strip()]
        if files:
            matches[entry] = files[:5]
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add file, folder, or pattern entries to .git/info/exclude."
    )
    parser.add_argument("paths", nargs="+", help="Repository paths or ignore patterns to add")
    args = parser.parse_args()

    try:
        root = repo_root()
        target = exclude_path()
        entries = [normalize_entry(item, root) for item in args.paths]
        added, already_present = update_exclude(target, entries)
        tracked = tracked_matches(entries)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        print(f"error: Git command failed: {message}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"exclude_file: {target}")
    if added:
        print("added:")
        for entry in added:
            print(f"  {entry}")
    if already_present:
        print("already_present:")
        for entry in already_present:
            print(f"  {entry}")
    if tracked:
        print("tracked_warning:")
        for entry, files in tracked.items():
            print(f"  {entry} is already tracked by Git; local exclude will not hide changes.")
            for file in files:
                print(f"    {file}")
    if not added and not already_present:
        print("no entries supplied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
