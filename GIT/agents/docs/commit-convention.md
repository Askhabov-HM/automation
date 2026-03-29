# Commit convention

Use Conventional Commits format:

`type(scope): short summary`

## Allowed types

- `feat` — new functionality
- `fix` — bug fix
- `refactor` — internal code change without behavior change
- `docs` — documentation only
- `test` — tests only
- `chore` — maintenance, configs, dependencies
- `build` — build system or packaging
- `ci` — CI/CD changes
- `perf` — performance improvement
- `revert` — revert previous commit

## Rules

- Write commit subject in English.
- Use imperative mood.
- No trailing period.
- Keep it short and specific.
- Scope is optional but preferred.
- One commit = one logical change.
- Do not use vague messages like:
  - `update`
  - `fix stuff`
  - `changes`
  - `misc`
  - `wip`

## Good examples

- `feat(auth): add email login`
- `fix(api): handle token refresh retry`
- `refactor(cache): simplify invalidation logic`

## Bad examples

- `fixed`
- `some changes`
- `wip`
- `update project`

## Breaking changes

For breaking changes:
- use `!` after type/scope, or
- add `BREAKING CHANGE:` in the body

Examples:
- `feat(api)!: remove legacy v1 endpoints`
- `refactor(config)!: rename env variables`
