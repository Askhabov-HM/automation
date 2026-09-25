import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen


class UserError(Exception):
    pass


DOTENV_KEYS = {"GITLAB_TOKEN", "GITLAB_URL", "GITLAB_PROJECT"}


def run_git(arguments, cwd):
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise UserError("Git is not installed or is not available on PATH") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or "Git command failed"
        raise UserError(details) from exc

    return result.stdout.strip()


def find_git_root(cwd):
    return Path(run_git(["rev-parse", "--show-toplevel"], cwd)).resolve()


def parse_dotenv_value(value, line_number):
    value = value.strip()
    if not value:
        return ""

    if value[0] in {"'", '"'}:
        quote_character = value[0]
        if len(value) < 2 or value[-1] != quote_character:
            raise UserError(
                f"Invalid quoted value in .env at line {line_number}"
            )
        return value[1:-1]

    return value.split(" #", 1)[0].rstrip()


def load_dotenv(path):
    if not path.is_file():
        return

    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise UserError(f"Cannot read local environment file: {path}") from exc

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()

        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise UserError(f"Invalid .env entry at line {line_number}")
        if key not in DOTENV_KEYS or key in os.environ:
            continue

        os.environ[key] = parse_dotenv_value(value, line_number)


def parse_remote_url(remote_url):
    remote_url = remote_url.strip()
    if not remote_url:
        raise UserError("Git remote origin has an empty URL")

    if "://" not in remote_url:
        scp_match = re.fullmatch(
            r"(?:[^@\s/]+@)?(?P<host>[^:/\\\s]+):(?P<path>.+)",
            remote_url,
        )
        if not scp_match:
            raise UserError(
                "Cannot infer GitLab target from a local or unsupported remote URL"
            )
        host = scp_match.group("host")
        project = scp_match.group("path")
        gitlab_url = f"https://{host}"
    else:
        parsed = urlparse(remote_url)
        if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
            raise UserError("Git remote origin uses an unsupported URL format")

        host = parsed.hostname
        if parsed.scheme in {"http", "https"}:
            port = f":{parsed.port}" if parsed.port else ""
            gitlab_url = f"{parsed.scheme}://{host}{port}"
        else:
            gitlab_url = f"https://{host}"
        project = unquote(parsed.path)

    project = project.strip("/")
    if project.endswith(".git"):
        project = project[:-4]
    if not project:
        raise UserError("Cannot infer a GitLab project path from remote origin")

    return gitlab_url, project


def detect_target(cwd, remote_name):
    git_root = find_git_root(cwd)
    remote_url = run_git(
        ["-C", str(git_root), "remote", "get-url", remote_name],
        cwd,
    )
    gitlab_url, project = parse_remote_url(remote_url)
    return gitlab_url, project


def validate_gitlab_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserError("GitLab URL must be a valid HTTP or HTTPS URL")
    return value.rstrip("/")


def validate_due_date(value):
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise UserError("Due date must use the YYYY-MM-DD format") from exc
    if parsed.isoformat() != value:
        raise UserError("Due date must use the YYYY-MM-DD format")
    return value


def normalize_labels(value):
    if not value:
        return ""
    return ",".join(label.strip() for label in value.split(",") if label.strip())


def read_description(path):
    description_path = Path(path)
    if not description_path.is_file():
        raise UserError(f"Description file not found: {description_path}")
    return description_path.read_text(encoding="utf-8-sig").strip()


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Preview or create a GitLab issue for the repository in the current "
            "working directory."
        )
    )
    parser.add_argument("--title", required=True, help="Issue title")
    parser.add_argument(
        "--description-file",
        required=True,
        help="UTF-8 Markdown file containing the issue description",
    )
    parser.add_argument("--labels", help="Comma-separated label names")
    parser.add_argument("--due-date", help="Due date in YYYY-MM-DD format")
    parser.add_argument(
        "--confidential",
        action="store_true",
        help="Create a confidential issue",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote used for automatic target detection (default: origin)",
    )
    parser.add_argument(
        "--gitlab-url",
        help="Override the GitLab base URL",
    )
    parser.add_argument(
        "--project",
        help="Override the numeric project ID or namespace/project path",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Create the issue; without this flag only a preview is shown",
    )
    return parser


def resolve_target(args):
    gitlab_url = (args.gitlab_url or os.environ.get("GITLAB_URL", "")).strip()
    project = (args.project or os.environ.get("GITLAB_PROJECT", "")).strip()

    if not gitlab_url or not project:
        detected_url, detected_project = detect_target(Path.cwd(), args.remote)
        if not project and detected_project.endswith(".wiki"):
            raise UserError(
                "Git remote points to a GitLab Wiki repository. Set "
                "GITLAB_PROJECT to the parent project path in the repository "
                ".env file or pass --project explicitly."
            )
        gitlab_url = gitlab_url or detected_url
        project = project or detected_project

    gitlab_url = validate_gitlab_url(gitlab_url)
    project = project.strip("/")
    if not project:
        raise UserError("GitLab project ID or path cannot be empty")

    return gitlab_url, project


def build_payload(args):
    title = args.title.strip()
    if not title:
        raise UserError("Issue title cannot be empty")

    description = read_description(args.description_file)
    if not description:
        raise UserError("Issue description cannot be empty")

    payload = {
        "title": title,
        "description": description,
        "issue_type": "issue",
    }

    labels = normalize_labels(args.labels)
    if labels:
        payload["labels"] = labels

    due_date = validate_due_date(args.due_date)
    if due_date:
        payload["due_date"] = due_date

    if args.confidential:
        payload["confidential"] = True

    return payload


def print_preview(gitlab_url, project, payload, confirmed):
    print("GitLab issue preview")
    print(f"Target: {gitlab_url}")
    print(f"Project: {project}")
    print(f"Title: {payload['title']}")
    print(f"Type: {payload['issue_type']}")
    print(f"Labels: {payload.get('labels', '-')}")
    print(f"Due date: {payload.get('due_date', '-')}")
    print(f"Confidential: {'yes' if payload.get('confidential') else 'no'}")
    print("Description:")
    print("---")
    print(payload["description"])
    print("---")
    if not confirmed:
        print("Preview only. Re-run with --confirm after explicit user approval.")


def extract_error_details(body):
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or "No error details returned"

    if isinstance(parsed, dict):
        return str(parsed.get("message", parsed))
    return str(parsed)


def create_issue(endpoint, token, payload):
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "PRIVATE-TOKEN": token,
            "User-Agent": "git-issue-assistant/1",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        details = extract_error_details(body)
        raise UserError(f"GitLab returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise UserError(f"Cannot connect to GitLab: {exc.reason}") from exc


def main():
    args = build_parser().parse_args()
    git_root = find_git_root(Path.cwd())
    load_dotenv(git_root / ".env.gitlab")
    load_dotenv(git_root / ".env")
    gitlab_url, project = resolve_target(args)
    payload = build_payload(args)
    print_preview(gitlab_url, project, payload, args.confirm)

    if not args.confirm:
        return

    token = os.environ.get("GITLAB_TOKEN", "").strip()
    if not token:
        raise UserError(
            "GITLAB_TOKEN is not set. Configure it locally without sending it "
            "through chat or committing it to the repository."
        )

    endpoint = (
        f"{gitlab_url}/api/v4/projects/{quote(project, safe='')}/issues"
    )
    issue = create_issue(endpoint, token, payload)
    issue_iid = issue.get("iid", "?")
    issue_url = issue.get("web_url", "")

    print(f"Created GitLab issue #{issue_iid}")
    if issue_url:
        print(f"URL: {issue_url}")


if __name__ == "__main__":
    try:
        main()
    except (UserError, KeyboardInterrupt) as exc:
        message = str(exc) or "Operation cancelled"
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)
