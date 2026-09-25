---
name: gitlab-work-item-reader
description: Retrieve and explain all accessible information for an existing GitLab work item or issue from a supplied `/-/work_items/NUMBER` or `/-/issues/NUMBER` URL. Use when Codex must read task requirements, metadata, comments, system activity, participants, linked issues, or related merge requests without changing GitLab.
---

# GitLab Work Item Reader

Read an existing GitLab work item through read-only API requests. Never mutate the
work item, its discussions, or its relationships.

## Retrieve the work item

1. Take the GitLab work item URL from the user. Require a project URL ending in
   `/-/work_items/<iid>` or `/-/issues/<iid>`.
2. Run the bundled script from the user's current working directory:

   ```text
   python <skill-dir>/scripts/read_gitlab_work_item.py "<work-item-url>"
   ```

3. Read the complete JSON output. It contains the core work item, discussions,
   participants, linked issues, related merge requests, emoji reactions, resource
   events, and a list of endpoints that GitLab did not make available.
4. Require `.env.gitlab` at the current Git repository root with both settings:

   ```dotenv
   GITLAB_URL=https://gitlab.com
   GITLAB_TOKEN=glpat-placeholder
   ```

   Read these values only from `.env.gitlab`. Ignore process environment values and
   never fall back to `.env`. Never ask the user to paste a token into chat and
   never print or store it in the skill.
5. If the supplied URL is on a host other than `GITLAB_URL`, do not send the token.
   Ask the user to configure the matching `GITLAB_URL` locally.

The script may make multiple `GET` requests and follows pagination. It contains no
GitLab write operation.

## Report the result

When the user asks for all information, include:

- work item number, title, type, state, confidentiality, and URL;
- the complete description and requirements without silently changing their meaning;
- author, assignees, labels, milestone, iteration, weight, dates, and time tracking;
- task checklist progress and votes when present;
- participants, comments, discussion replies, and relevant system activity;
- linked or blocking issues and related merge requests;
- every unavailable section reported by the script.

Keep requirements from the description separate from later comments and system
events. Identify contradictions, unresolved questions, and missing acceptance
criteria only as analysis; do not present inferred behavior as an original
requirement. Answer in the user's language unless asked otherwise.

If the user asks only for a summary or a specific field, retrieve the complete data
but return only the requested view.

## Boundaries

- Do not create, edit, close, assign, label, comment on, or reorder work items.
- Do not read GitLab credentials from process environment variables or `.env`.
- Do not claim that inaccessible premium, confidential, or version-specific data was
  retrieved. Report the relevant entry from `unavailable`.
- Treat a `404` as either missing or inaccessible; do not reveal assumptions about a
  private work item's existence.
- Use a separate write-capable workflow when the user requests a GitLab mutation.
