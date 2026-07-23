---
name: gitlab-task-assistant
description: Turn raw product notes into consistent GitLab issue drafts, assess whether requirements are ready for development, identify blocking open questions, preview issue metadata, and create GitLab issues through the bundled API script after explicit approval. Use when Codex needs to draft, standardize, review, refine, or publish a task or issue for the current GitLab project.
---

# GitLab Task Assistant

Prepare clear GitLab issues from incomplete notes and publish them reliably from
the current project.

## Draft the task

1. Treat the user's notes, linked specifications, and supplied artifacts as the
   source of truth.
2. Write the title and description in English unless the user requests another
   language.
3. Use `assets/task-template.md` as the structural guide.
4. Always include `Goal`, `Requirements`, and `Acceptance Criteria`.
5. Include `Context / Source`, `User Flow`, `Open Questions`, `Out of Scope`, and
   `Technical Notes` only when they add useful information.
6. Remove template comments, placeholder text, and empty sections.
7. Keep requirements concrete and acceptance criteria independently verifiable.
8. Avoid repeating the same statement across requirements, user flow, and
   acceptance criteria.
9. Never invent product behavior, API contracts, designs, links, or technical
   decisions. Put unresolved decisions under `Open Questions`.

## Assess readiness

Classify the draft before offering to publish it:

- `Ready for development`: no unresolved decision changes the expected behavior.
- `Needs clarification`: one or more open questions can materially change scope,
  UX, validation, security, API behavior, or acceptance criteria.
- `Discovery`: the central product or technical flow is not yet defined.

Allow a discovery issue to be published when its goal is explicitly to resolve
the listed questions. Do not describe an implementation issue as ready while
blocking questions remain.

## Preview before publishing

Show the user all of the following:

- detected GitLab URL and project;
- title and complete Markdown description;
- labels, due date, issue type, and confidentiality setting;
- readiness classification.

Use `scripts/create_gitlab_issue.py` without `--confirm` to validate the target
and display the exact API payload as a preview. Treat drafting or asking to
"prepare" a task as preview-only. Ask for explicit approval after showing the
preview.

Never run the script with `--confirm` until the user approves that preview.

## Publish the approved issue

1. Save the approved description to a uniquely named `*.local` Markdown file in
   the current repository. Do not overwrite an existing file.
2. Run the bundled script from the repository root:

   ```text
   python <skill-dir>/scripts/create_gitlab_issue.py \
     --title "<approved title>" \
     --description-file "<local description file>" \
     [--labels "label-one,label-two"] \
     [--due-date YYYY-MM-DD] \
     [--issue-type issue|task|incident|test_case] \
     [--confidential]
   ```

3. Review the preview output with the user.
4. After explicit approval, rerun the identical command with `--confirm`.
5. Report the created issue number and URL.
6. Remove only the temporary local description file created by this workflow.

The script infers the GitLab host and project path from `git remote origin`.
Use `--remote`, `--gitlab-url`, or `--project` only when automatic detection is
wrong or unavailable.

The script loads `GITLAB_TOKEN`, `GITLAB_URL`, and `GITLAB_PROJECT` from a local
`.env` file in the repository root. Existing process environment variables take
precedence. Keep `.env` ignored by Git and never commit it.

For a cloned GitLab Wiki repository, set `GITLAB_PROJECT` to the parent project
path because the Wiki remote ends in `.wiki` and is not a valid Issues API
target:

```dotenv
GITLAB_PROJECT=namespace/project
```

The script must stop preview generation when it detects a Wiki remote without an
explicit project override. Always show the resolved parent project in the
preview.

Require `GITLAB_TOKEN` only for the confirmed request. Never ask the user to paste
the token into chat, print it, place it in the skill, or commit it. If it is
missing, ask the user to configure it locally in the environment and then retry.

Stop without retrying automatically when GitLab rejects the request. Report the
safe error details and let the user decide whether to edit or retry.

## List ordering

Do not promise that a newly created issue appears first in every Open list.
Creation does not control the viewer's sort preference. Recommend sorting by
created date in descending order to show newest issues first. Use the reorder API
only when the user explicitly requests a change to the shared manual ordering,
and preview that separate mutation before executing it.
