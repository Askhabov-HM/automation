# Versioning

Project versioning must follow Semantic Versioning:

`MAJOR.MINOR.PATCH`

## When to change the version

- Do not change the project version during ordinary commits.
- Determine the next version only when the user explicitly requests versioning or release preparation.
- Inspect all relevant changes since the previous release and apply the highest required version bump.
- Explain which changes caused the selected bump.
- Ask the user when the public impact or previous release cannot be determined reliably.
- Do not create a release or tag unless the user explicitly requests it.

## Stable version bump rules

For versions `1.0.0` and above:

- backward-compatible bug fix -> `PATCH`
- backward-compatible performance or security fix -> `PATCH`
- backward-compatible feature -> `MINOR`
- public API breaking change -> `MAJOR`

When multiple changes are included in one release, use the highest required bump:

`MAJOR` > `MINOR` > `PATCH`

## Initial development

For versions `0.y.z`:

- backward-compatible bug fix -> `PATCH`
- new feature -> `MINOR`
- breaking change -> `MINOR`

Use `1.0.0` when the public API is considered stable and consumers can rely on compatibility guarantees.

## Commit type mapping

- `fix` normally requires `PATCH`.
- `feat` normally requires `MINOR`.
- any commit with `!` or a `BREAKING CHANGE:` footer requires the breaking-change bump for the current development stage.
- `perf` normally requires `PATCH` when it changes released behavior without breaking compatibility.
- `docs`, `test`, `ci`, `chore`, and behavior-preserving `refactor` do not trigger a release by themselves.
- Determine the effect of `revert` from the released behavior it restores or removes.

## Public API baseline

For backend and API projects, treat these as public API when they are exposed to consumers:

- HTTP methods and endpoint paths
- path and query parameters
- request body schemas
- required and optional fields
- public field types, defaults, and constraints
- response body schemas
- documented HTTP status codes and headers
- authentication and authorization behavior
- documented error formats and error codes
- webhook and event payloads
- documented environment variables required to run or integrate with the project
- exported functions and types when the project is used as a library

Treat a database schema as public API only when external consumers or services access it directly.

## Breaking API changes

Examples of breaking changes include:

- removing or renaming an endpoint
- changing an endpoint HTTP method
- removing or renaming a public field
- changing a public field type
- making an optional input required
- tightening validation so previously valid requests are rejected
- incompatibly changing a response or error format
- incompatibly changing authentication or authorization behavior

Examples of normally backward-compatible changes include:

- adding a new endpoint
- adding a new optional request field
- changing internal implementation without changing public behavior
- refactoring private code
- fixing behavior so it matches the documented contract
- improving internal performance without changing the public contract

## Release rules

- Do not modify an already released version.
- Every new release must use a new version.
- Base the decision on public behavior, not only on filenames or commit types.
