---
name: git-local-exclude
description: Add local-only files, folders, or ignore patterns to a Git repository's .git/info/exclude file. Use when the user asks to ignore personal notes, temporary files, local settings, generated scratch folders, or other paths only for the current repository without changing the shared .gitignore.
---

# Git Local Exclude

## Overview

Use this skill to add repository-local ignore rules to `.git/info/exclude`. These rules are not committed and apply only to the current local clone.

Do not use this skill for shared ignore rules that the whole team needs. Put those in `.gitignore` instead.

## Workflow

1. Identify the file, folder, or pattern the user wants to ignore locally.
2. Do not read file contents, especially for `.env`, credentials, local notes, or other private files.
3. Run `scripts/update_exclude.py` from this skill with the requested paths.
4. Report the entries that were added and entries that were already present.

Do not run `git check-ignore -v` or `git status --ignored -s` unless the user explicitly asks for extra verification.

## Path Rules

- Treat paths ending in `/` as folders.
- If a requested path exists and is a directory, store it with a trailing `/`.
- Normalize Windows separators to Git-style `/`.
- Convert absolute paths inside the repository to repository-relative paths.
- Reject absolute paths outside the repository.
- Preserve explicit Git ignore patterns when the user clearly asks for a pattern, such as `*.log`.

## Tracked Files

Git local excludes only affect untracked files. If a path is already tracked, warn the user that `.git/info/exclude` will not hide future modifications to it.

Do not untrack files with `git rm --cached` unless the user explicitly requests that separate operation.

## Script

Run from any directory inside the target Git repository:

```bash
python path/to/git-local-exclude/scripts/update_exclude.py my_project_notes.md local-notes/
```

The script updates the repository's `.git/info/exclude` file under this section:

```gitignore
# Codex local excludes
```
