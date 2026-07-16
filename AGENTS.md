# Project rules

Follow the detailed project rules in:

- `codex-guidance/commit-convention.md`
- `codex-guidance/env-files.md`
- `codex-guidance/versioning.md`
- `codex-guidance/security-secrets.md`

Mandatory baseline:

- Use Conventional Commits.
- Use Semantic Versioning (`MAJOR.MINOR.PATCH`).
- Never commit secrets, `.env` files with real values, API keys, tokens, passwords, private keys, certificates, or cloud credentials.
- Never copy real environment values or their fragments into `.env.example`, `.env.template`, `.env.sample`, or any other configuration template.
- Commit only placeholder templates such as `.env.example` or `.env.template`.

Commit workflow:

- Use `safe-commit-manual` by default for commit and commit-and-push requests.
- Use `safe-commit-auto` only when the user explicitly invokes `$safe-commit-auto` or explicitly requests commit and push without preview or approval.
