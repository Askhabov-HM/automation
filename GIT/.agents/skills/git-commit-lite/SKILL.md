---
name: git-commit-lite
description: Quickly create a simple Conventional Commit for small, obvious local Git changes. Use when the user explicitly asks for an easy, light, quick, or simple commit and does not need the full safe-commit-manual preview workflow. Refuse secret-like files, unsafe Git states, broad staging, history rewriting, and ambiguous mixed changes. Push only when explicitly requested.
---

# Git Commit Lite

## Overview

Use this skill for small, obvious commits where the full safe-commit-manual preview would be too heavy.

Keep the workflow short, but do not remove the minimum guardrails that prevent accidental broad staging, unsafe Git operations, or obvious secret-file commits.

## Minimal Workflow

1. Run `git status --short --branch`.
2. Stop if Git is in merge, rebase, cherry-pick, revert, conflict, or detached-HEAD state.
3. Select only files that clearly belong to the user's requested change.
4. Refuse obvious secret-like files by filename or extension.
5. Create one English Conventional Commit message.
6. Stage only explicit paths with `git add -- <path>...`.
7. Run `git diff --cached --name-status` and confirm only intended paths are staged.
8. Commit normally with `git commit -m "<message>"`.
9. Push only if the user explicitly asked to push.
10. Report the commit SHA, message, push result if any, and remaining changes.

## Minimal Secret Guard

Do not read `.env` contents. Do not scan the whole repository.

Stop instead of committing when a selected path matches any of these names or patterns:

```gitignore
.env
.env.*
*.pem
*.key
*.crt
*.p12
*.pfx
secrets.*
secret.*
credentials.*
*.local
```

If these files are part of the intended change, switch to `$safe-commit-manual` or ask the user for explicit direction.

## Commit Message

Use Conventional Commits:

```text
type(scope): short summary
```

Prefer these types:

- `feat` for new functionality
- `fix` for bug fixes
- `docs` for documentation only
- `chore` for maintenance, config, or skill metadata
- `refactor` for internal changes without behavior change
- `test` for tests only

Keep the subject in English, imperative, short, and without a trailing period.

## Stop Conditions

Stop without committing when:

- there are no eligible changes;
- the change is mixed or ambiguous;
- any selected path is secret-like;
- Git is in an unsafe state;
- committing would require broad staging;
- a hook rejects the commit;
- pushing would require merge, rebase, force, or history rewriting.

## Prohibited Actions

- Do not use `git add .`, `git add -A`, or broad whole-tree staging.
- Do not use `git commit --amend`, `git commit --no-verify`, reset, rebase, force push, or history rewriting.
- Do not run tests, linters, formatters, builds, or type checks unless the user separately asks.
- Do not push unless the user explicitly requested push.
