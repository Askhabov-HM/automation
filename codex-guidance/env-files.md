# Environment files and templates

## Purpose

This policy applies to every language, framework, operating system, and deployment
environment.

Real environment files contain local or deployed configuration. Environment
templates document variable names and value shapes for onboarding and tooling.
Templates are publishable repository content and must be safe for a public
repository.

A written policy cannot provide a technical guarantee by itself. A repository that
claims enforcement must apply both the workflow and the automated checks described
below. All checks must fail closed: an unknown or unclassified value is rejected.

## Scope

Treat all of the following as environment templates:

- `.env.example`, `.env.template`, and `.env.sample`;
- variants such as `.env.development.example`, `service.env.example`, and
  `example.env`;
- YAML, JSON, TOML, shell, container, CI, and documentation examples that reproduce
  environment configuration.

Treat `.env`, `.env.local`, `.env.production`, `*.env`, CI exports, secret-manager
exports, and deployment configuration as real environment sources unless a file is
explicitly identified and validated as a template.

This policy covers values in assignments, comments, documentation, fixtures,
generated files, diffs, logs, and command output.

## Non-negotiable invariant

An environment template may contain variable names, comments, and explicitly
synthetic values. It must never contain a real value, an identifying fragment of a
real value, or a reversible transformation of a real value taken from any local,
shared, staging, production, CI, or secret-manager environment.

Variable names are expected in templates. Real variable values are forbidden.

Treat every real environment value as confidential by default, even when it is not
a credential and is already reachable on the public internet.

Real data includes, but is not limited to:

- passwords, tokens, API keys, cookies, private keys, certificates, and DSNs;
- URLs, hostnames, IP addresses, ports, repository links, and webhook endpoints;
- tenant, account, organization, workspace, project, bucket, cluster, and resource
  identifiers;
- usernames, email addresses, phone numbers, and other identity data;
- absolute local paths, home directories, executable paths, and mounted volumes;
- values copied from a developer machine, CI system, cloud console, password
  manager, deployment, database, or secret manager.

## Mandatory rules

- Never create a template by copying a real environment file and redacting selected
  fields afterward.
- Never use a real environment value as the input for generating, formatting, or
  suggesting a template value.
- Never copy a real value into a template temporarily, including during an
  intermediate edit.
- Never preserve a real hostname, path segment, identifier, username, or other
  fragment while replacing only the obvious secret portion.
- Never place real values in template comments, examples, defaults, test fixtures,
  generated documentation, commit messages, or review text.
- Never mask, truncate, hash, encode, encrypt, escape, or partially redact a real
  value for use in a template. Those are transformations of real data, not
  placeholders.
- Never print real environment values while inspecting keys or validating a
  template. Diagnostics may report only the template file, line, variable name, and
  rejection reason.
- When a user supplies a real value for a local environment file, use that value
  only in the explicitly requested real file. Represent the same key in every
  template with an independently chosen placeholder.
- When unsure whether a value is safe, leave it empty and stop it from being
  committed until it is classified.

## Safe source of template keys

Build template structure from committed, non-secret sources in this order:

1. A typed configuration schema or application validation code.
2. Calls that read environment variable names in source code.
3. Existing safe templates and project documentation.
4. Key-only extraction from a real environment file when no safer source exists.

Key-only extraction must parse the file without displaying, logging, returning, or
copying the right-hand side of any assignment. Only variable names may leave the
parser. Do not use a command that dumps the file and then visually ignore the
values.

Synchronizing an environment file with a template means synchronizing required
variable names, ordering, grouping, comments, and documented value shapes. It never
means synchronizing values.

## Allowed template values

A template value is allowed only when it belongs to one of these categories:

- empty, especially for secrets and user-supplied values;
- an unmistakably synthetic placeholder created independently of every real
  environment;
- a documented application default obtained from committed source or schema;
- a fixed public endpoint required by the application and independently verified
  from official documentation, never copied from a real environment.

Use reserved and synthetic values consistently:

```dotenv
API_TOKEN=
DATABASE_URL=
APP_URL=https://example.com
SERVICE_HOST=service.example
CALLBACK_URL=https://example.com/oauth/callback
SUPPORT_EMAIL=user@example.com
PROJECT_ID=example-project
TENANT_ID=replace-me
LOCAL_API_URL=http://localhost:3000
EXAMPLE_IPV4=192.0.2.1
EXAMPLE_IPV6=2001:db8::1
POSIX_TOOL_PATH=/path/to/tool
WINDOWS_TOOL_PATH=C:\path\to\tool.exe
```

Preferred reserved values are `example.com`, the `.example`, `.test`, and `.invalid`
top-level domains, documentation IP ranges, and clearly generic local paths.
`localhost` is allowed only for a genuinely local service.

Booleans, numbers, ports, enum values, and fixed service endpoints may look harmless
but must come from committed application defaults or an explicit reviewed allowlist,
not from a real environment file.

## Required update workflow

For every new or changed environment variable:

1. Determine the key and expected value shape from a safe source.
2. Classify the value as secret, user-specific, environment-specific, documented
   default, or fixed public constant.
3. Put the real value only in the ignored local or deployment environment that the
   user explicitly requested.
4. Add only the key and an allowed placeholder to repository templates.
5. Review the complete template line, its comments, and nearby examples for leaked
   fragments.
6. Run the local overlap check and the repository template validator.
7. Review the staged diff before commit and run the same validator again in CI.

Do not stage a real environment file to compare it with a template.

## Mandatory automated enforcement

Use two complementary checks. A generic secret scanner alone is insufficient
because real URLs, paths, usernames, and project identifiers may not look secret.

### Local overlap check

Before staging and before committing, a local check with access to ignored
environment files must:

- parse real files and templates without logging values;
- reject any non-empty real value found in a template assignment or comment;
- reject identifying URL hosts and paths, DSN components, account identifiers, and
  meaningful long fragments derived from real values;
- exempt only documented application defaults and reviewed safe literals;
- report the template location and variable name without reporting the matched real
  value.

The comparison must happen in memory. It must not create sanitized copies,
temporary dumps, snapshots, or reports containing real values.

### Repository and CI template validator

A repository validator, run on staged changes and in CI, must:

- discover every environment template covered by this policy;
- reject non-empty values outside the allowed categories;
- reject credentials, authenticated URLs, private hosts, personal home paths,
  emails outside reserved example domains, opaque IDs, and token-like strings;
- validate any allowlisted defaults or public constants against a committed schema
  or reviewed allowlist that was not generated from real environment files;
- scan assignments, comments, documentation examples, and generated templates;
- fail on parsing errors, unknown template formats, and unclassified values.

The CI check protects the repository when a developer has no local environment
file. The local overlap check catches non-secret real data that pattern matching
cannot identify. Both are required.

## Repository controls

- Ignore real environment files by default and explicitly unignore only approved
  template suffixes.
- Keep the list of recognized template names and formats centralized.
- Prefer generating templates from a typed committed schema.
- Require review for changes to template allowlists, validators, ignore rules, and
  configuration schemas.
- Run secret scanning across staged changes and repository history in addition to
  the template-specific checks.
- Never weaken a validator merely to make an unknown value pass; classify the value
  and document the safe source first.

## Incident response

If real data appears in a template:

1. Stop the commit or deployment and remove the value from every template, comment,
   fixture, generated file, and log.
2. Search the index, branch, repository history, CI artifacts, and published
   packages for the same value without exposing it in reports.
3. Rotate or revoke the value immediately if it can authenticate, authorize, sign,
   decrypt, or grant access.
4. Remove committed data from history using the repository's approved incident
   procedure, then coordinate any required force-push.
5. Add or strengthen an automated regression check for the class of leak.

## Review checklist

- Does the template contain variable names but no values sourced from a real
  environment?
- Is every non-empty value empty, synthetic, schema-derived, or explicitly
  allowlisted from an independent public source?
- Are comments and documentation examples free of real values and fragments?
- Were keys obtained from source or by key-only extraction rather than a file dump?
- Did the local overlap check pass without printing values?
- Did the staged template validator and secret scanner pass?
- Would every changed template be safe in a public repository?

If any answer is unknown, the template is not ready to commit.
