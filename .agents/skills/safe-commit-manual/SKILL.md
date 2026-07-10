---
name: safe-commit-manual
description: "Preview a safe commit-and-push plan, report repository status and suspected secrets, wait for explicit user approval, then stage, commit, and push according to the repository AGENTS.md and codex-guidance. Use for generic commit requests, when the user invokes $safe-commit-manual, or whenever approval is required before Git writes. Do not use for releases, pull requests, or history rewriting."
---

# Safe Commit Manual

Prepare a read-only commit-and-push plan, wait for explicit approval, then execute exactly the approved plan.

## Phase 1: Read-Only Preview

1. Resolve the Git repository root.
2. Read the root `AGENTS.md` and follow all applicable instructions.
3. Read `codex-guidance/commit-convention.md` and `codex-guidance/security-secrets.md` from the repository root. Read `codex-guidance/versioning.md` only when version or release files are included.
4. Inspect the current branch, remotes, upstream, staged changes, unstaged changes, and untracked files.
5. Detect merge, rebase, cherry-pick, revert, conflict, and detached-HEAD states.
6. Review all candidate diffs and filenames for secrets. Redact suspected values in all output.
7. Exclude unrelated, temporary, generated, or user-owned changes that do not belong to the requested work.
8. Divide the selected changes into logical commits and generate English Conventional Commit messages that follow the project guidance.
9. Present a preview containing:
   - current branch and intended push destination;
   - staged, unstaged, and relevant untracked files;
   - secret-check status without exposing values;
   - proposed commits in order, with message and included files;
   - excluded files;
   - blockers, ambiguities, and warnings.
10. Do not stage, commit, or push anything during this phase.
11. Stop and wait for explicit user approval. Allow the user to edit the proposed grouping, files, or messages before approval.

Always pause after the preview, even if the original request already asked to commit and push.

## Phase 2: Approved Execution

1. Treat only a clear approval of the displayed plan as authorization to proceed.
2. Re-run the repository status and diff checks before writing anything.
3. If any candidate file, diff, branch, remote, or upstream changed after the preview, cancel the approval and present a refreshed plan.
4. Stop if a suspected secret, unsafe Git state, unresolved ambiguity, missing guidance, or conflicting instruction exists.
5. Stage only the explicit paths or hunks assigned to the first approved commit.
6. Review the staged diff and repeat the secret check immediately before every commit.
7. Create each approved commit normally and allow configured Git hooks to run.
8. Push the current branch to the approved upstream. If the approved plan showed no existing upstream and `origin` was the single unambiguous remote, set `origin/<current-branch>` as upstream and push.
9. Report the created commit SHAs and messages, push destination, remaining changes, and warnings.

Do not run project tests, linters, formatters, builds, or type checks as part of this skill. Git hooks may still run them during `git commit`; never bypass those hooks.

## Stop Conditions

Stop without completing the operation when:

- a suspected secret or forbidden file is found;
- there are no eligible changes;
- the intended commit scope is ambiguous;
- required guidance is missing or contradictory;
- the branch or repository state is unsafe;
- the remote or push destination is ambiguous;
- a Git hook rejects a commit;
- push authentication fails or the push is rejected;
- pushing would require merge, rebase, history rewriting, or force.

Do not automatically recover from a rejected push. Report the exact non-sensitive reason and leave the repository state intact.

## Prohibited Actions

- Do not use `git add .`, broad `git add -A`, or equivalent whole-tree staging.
- Do not use `git commit --amend`, `git commit --no-verify`, or empty commits unless explicitly requested by a separate instruction.
- Do not use force push, reset, clean, rebase, automatic merge, automatic conflict resolution, or history rewriting.
- Do not create tags, releases, or pull requests.
- Do not reveal secret values in output.

