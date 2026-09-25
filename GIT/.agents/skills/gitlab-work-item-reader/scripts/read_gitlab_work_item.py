import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


class UserError(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status, details):
        super().__init__(details)
        self.status = status
        self.details = details


DOTENV_KEYS = {"GITLAB_TOKEN", "GITLAB_URL"}
WORK_ITEM_PATH = re.compile(
    r"^(?P<project>.+?)/-/(?:work_items|issues)/(?P<iid>[1-9][0-9]*)/?$"
)


def parse_dotenv_value(value, line_number):
    value = value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise UserError(
                f"Invalid quoted GitLab setting in .env at line {line_number}"
            )
        return value[1:-1]
    return value.split(" #", 1)[0].rstrip()


def load_gitlab_env(path):
    if not path.is_file():
        raise UserError(
            f"GitLab settings file not found: {path}. "
            "Create .env.gitlab in the current Git repository root."
        )
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise UserError(f"Cannot read local GitLab settings from {path}") from exc

    settings = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if separator and key in DOTENV_KEYS:
            settings[key] = parse_dotenv_value(value, line_number)
    return settings


def find_settings_root(cwd):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return cwd
    return Path(result.stdout.strip()).resolve()


def origin_from_url(value, setting_name):
    parsed = urlparse(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise UserError(f"{setting_name} must be a valid HTTP or HTTPS GitLab URL")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), "", "", "", ""))


def parse_work_item_url(value):
    parsed = urlparse(value.strip())
    origin = origin_from_url(value, "Work item URL")
    match = WORK_ITEM_PATH.fullmatch(parsed.path.lstrip("/"))
    if not match:
        raise UserError(
            "Expected a GitLab project URL ending in "
            "/-/work_items/<iid> or /-/issues/<iid>"
        )
    return origin, unquote(match.group("project")), int(match.group("iid"))


def extract_error_details(body):
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        details = body.strip() or "No error details returned"
    else:
        if isinstance(parsed, dict):
            details = str(parsed.get("message", parsed))
        else:
            details = str(parsed)
    return details[:1000]


class GitLabReader:
    def __init__(self, origin, token):
        self.api_root = f"{origin}/api/v4"
        self.token = token

    def get(self, path, params=None):
        query = f"?{urlencode(params)}" if params else ""
        headers = {
            "Accept": "application/json",
            "User-Agent": "gitlab-work-item-reader/1",
        }
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        request = Request(f"{self.api_root}{path}{query}", headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body), response.headers
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ApiError(exc.code, extract_error_details(body)) from exc
        except URLError as exc:
            raise UserError(f"Cannot connect to GitLab: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise UserError("GitLab returned an invalid JSON response") from exc

    def get_all_pages(self, path):
        items = []
        page = 1
        while page <= 100:
            data, headers = self.get(path, {"per_page": 100, "page": page})
            if not isinstance(data, list):
                raise UserError(f"GitLab returned a non-list response for {path}")
            items.extend(data)
            next_page = headers.get("X-Next-Page", "").strip()
            if next_page:
                page = int(next_page)
            elif len(data) == 100:
                page += 1
            else:
                return items
        raise UserError(f"Pagination exceeded 100 pages for {path}")


def unavailable_entry(name, error):
    return {
        "section": name,
        "http_status": error.status,
        "message": error.details,
    }


def read_optional_collection(reader, name, path, unavailable):
    try:
        return reader.get_all_pages(path)
    except ApiError as exc:
        unavailable.append(unavailable_entry(name, exc))
        return []


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read all accessible data for a GitLab work item without changing it."
    )
    parser.add_argument(
        "url",
        help="GitLab URL ending in /-/work_items/<iid> or /-/issues/<iid>",
    )
    return parser


def main():
    args = build_parser().parse_args()
    settings_root = find_settings_root(Path.cwd())
    settings = load_gitlab_env(settings_root / ".env.gitlab")

    origin, project, iid = parse_work_item_url(args.url)
    token = settings.get("GITLAB_TOKEN", "").strip()
    configured_url = settings.get("GITLAB_URL", "").strip()
    missing = [
        key for key, value in (
            ("GITLAB_URL", configured_url),
            ("GITLAB_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise UserError(
            ".env.gitlab must define non-empty values for: " + ", ".join(missing)
        )
    token_origin = origin_from_url(configured_url, "GITLAB_URL")
    if origin != token_origin:
        raise UserError(
            "Work item host differs from GITLAB_URL in .env.gitlab. "
            "Refusing to send GITLAB_TOKEN; update .env.gitlab and retry."
        )

    reader = GitLabReader(origin, token)
    issue_path = f"/projects/{quote(project, safe='')}/issues/{iid}"
    try:
        work_item, _ = reader.get(issue_path)
    except ApiError as exc:
        if exc.status in {401, 403, 404}:
            raise UserError(
                f"Work item is missing or inaccessible (HTTP {exc.status}). "
                "Check GITLAB_TOKEN in .env.gitlab, project access, and the URL."
            ) from exc
        raise UserError(
            f"GitLab returned HTTP {exc.status}: {exc.details}"
        ) from exc

    unavailable = []
    collections = {
        "discussions": f"{issue_path}/discussions",
        "linked_issues": f"{issue_path}/links",
        "related_merge_requests": f"{issue_path}/related_merge_requests",
        "participants": f"{issue_path}/participants",
        "award_emoji": f"{issue_path}/award_emoji",
    }
    result = {
        "source_url": args.url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "gitlab_url": origin,
        "project": project,
        "iid": iid,
        "work_item": work_item,
    }
    for name, path in collections.items():
        result[name] = read_optional_collection(reader, name, path, unavailable)

    event_paths = {
        "labels": f"{issue_path}/resource_label_events",
        "milestones": f"{issue_path}/resource_milestone_events",
        "states": f"{issue_path}/resource_state_events",
        "weights": f"{issue_path}/resource_weight_events",
        "iterations": f"{issue_path}/resource_iteration_events",
    }
    result["resource_events"] = {}
    for name, path in event_paths.items():
        section = f"resource_events.{name}"
        result["resource_events"][name] = read_optional_collection(
            reader, section, path, unavailable
        )
    result["unavailable"] = unavailable
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (UserError, KeyboardInterrupt) as exc:
        message = str(exc) or "Operation cancelled"
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)
