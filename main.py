"""Jira helpers and a small CLI for listing issues associated with a user."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from typing import Any

import requests
from dotenv import load_dotenv
from jira import JIRA


class JiraConnectionError(RuntimeError):
    """JIRA preflight failed — server returned a non-serverInfo (HTML/login) body.

    Raised instead of letting the cryptic ``requests.exceptions.JSONDecodeError``
    surface from deep inside the ``jira`` library's eager ``server_info()`` call,
    so the operator sees the actual HTTP status / Content-Type / body snippet and a
    likely-cause hint (the only way to tell an auth failure from a wrong URL on an
    air-gapped box where the JIRA server cannot be probed from elsewhere).
    """


def _serverinfo_url(server: str) -> str:
    return server.rstrip("/") + "/rest/api/2/serverInfo"


def preflight(
    server: str,
    api_token: str | None,
    username: str | None,
    verify_ssl: bool,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Raw connectivity probe against ``/rest/api/2/serverInfo``.

    Bypasses the ``jira`` library's eager JSON parse (which only yields
    ``JSONDecodeError: Expecting value`` when JIRA returns its HTML login page)
    and instead inspects the real status / Content-Type / body. Returns the parsed
    ``serverInfo`` dict on success; raises :class:`JiraConnectionError` with a
    diagnostic message otherwise. Follows redirects like the real client so a
    benign http→https canonicalisation is not mistaken for a failure.
    """
    url = _serverinfo_url(server)
    headers = {"Accept": "application/json"}
    auth = None
    if username:
        auth = (username, api_token or "")
    elif api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    try:
        resp = requests.get(
            url, headers=headers, auth=auth, verify=verify_ssl, timeout=timeout
        )
    except requests.exceptions.RequestException as exc:
        raise JiraConnectionError(
            f"JIRA preflight could not reach {url}: {type(exc).__name__}: {exc}"
        ) from exc

    content_type = resp.headers.get("Content-Type", "")
    body_head = (resp.text or "")[:300]
    redirected = resp.url.rstrip("/") != url.rstrip("/")

    info: Any = None
    if "application/json" in content_type.lower():
        try:
            info = resp.json()
        except ValueError:
            info = None
    if isinstance(info, dict) and ("baseUrl" in info or "version" in info):
        return info

    hints: list[str] = []
    if resp.status_code in (401, 403):
        hints.append("JIRA_TOKEN (PAT) was rejected (invalid / expired / insufficient).")
    else:
        hints.append(
            "JIRA_TOKEN (PAT) invalid/expired -> JIRA serves its HTML login page, OR"
        )
        hints.append("JIRA_URL wrong (context path / reverse-proxy / http-vs-https).")
    if redirected:
        hints.append(f"Request was redirected to {resp.url!r} (SSO / front-door smell).")

    raise JiraConnectionError(
        "JIRA preflight got a non-serverInfo response — this is the root cause of the "
        "JSONDecodeError raised inside the jira library.\n"
        f"  requested : {url}\n"
        f"  final URL : {resp.url}\n"
        f"  status    : {resp.status_code}\n"
        f"  content   : {content_type!r}\n"
        f"  body[:300]: {body_head!r}\n"
        "  likely    : " + " ".join(hints) + "\n"
        "Fix the credential/URL, then re-run `python main.py --check`."
    )


def _escape_jql_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None

    return date.fromisoformat(value)


def _format_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    return value.isoformat()


def _coerce_worklog_date(value: Any) -> date | None:
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        normalized_value = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized_value).date()
        except ValueError:
            return date.fromisoformat(value[:10])

    return None


def _flatten_identifiers(value: Any) -> list[str]:
    identifiers: list[str] = []

    if value is None:
        return identifiers

    if isinstance(value, str):
        if value:
            identifiers.append(value)
        return identifiers

    if isinstance(value, dict):
        for key, item in value.items():
            identifiers.extend(_flatten_identifiers(key))
            identifiers.extend(_flatten_identifiers(item))
        return identifiers

    if isinstance(value, (list, tuple, set)):
        for item in value:
            identifiers.extend(_flatten_identifiers(item))
        return identifiers

    for attribute_name in ("accountId", "name", "emailAddress", "displayName", "key"):
        attribute_value = getattr(value, attribute_name, None)
        if isinstance(attribute_value, str) and attribute_value:
            identifiers.append(attribute_value)

    return identifiers


def _collect_group_member_identifiers(jira_client: JIRA, group_name: str) -> list[str]:
    group_members = jira_client.group_members(group_name)
    identifiers = _flatten_identifiers(group_members)
    unique_identifiers = list(dict.fromkeys(identifiers))

    if not unique_identifiers:
        raise ValueError(f"No members found for Jira group: {group_name}")

    return unique_identifiers


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() not in {"0", "false", "no", "off"}


def _worklog_matches_filters(
    worklog: Any,
    *,
    target_identifiers: set[str] | None,
    from_date: date | None,
    to_date: date | None,
) -> bool:
    author_identifiers = set(_flatten_identifiers(getattr(worklog, "author", None)))
    worklog_date = _coerce_worklog_date(getattr(worklog, "started", None))

    if target_identifiers and author_identifiers.isdisjoint(target_identifiers):
        return False

    if from_date and worklog_date and worklog_date < from_date:
        return False

    if to_date and worklog_date and worklog_date > to_date:
        return False

    return True


def _build_worklog_jql(
    *,
    target_identifiers: list[str] | None,
    from_date: date | None,
    to_date: date | None,
) -> str:
    clauses: list[str] = []

    if target_identifiers:
        escaped_identifiers = [
            f'"{_escape_jql_value(identifier)}"' for identifier in target_identifiers
        ]
        if len(escaped_identifiers) == 1:
            clauses.append(f"worklogAuthor = {escaped_identifiers[0]}")
        else:
            clauses.append(f"worklogAuthor in ({', '.join(escaped_identifiers)})")

    if from_date:
        clauses.append(f'worklogDate >= "{from_date.isoformat()}"')

    if to_date:
        clauses.append(f'worklogDate <= "{to_date.isoformat()}"')

    if not clauses:
        return "ORDER BY updated DESC"

    return " AND ".join(clauses) + " ORDER BY updated DESC"


def get_user_issues(
    jira_client: JIRA,
    user_identifier: str,
    *,
    field: str = "assignee",
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Return Jira issues associated with a user.

    By default, this looks up issues assigned to the user. Pass `field="reporter"`
    if you want issues reported by the user instead.
    """
    if max_results <= 0:
        raise ValueError("max_results must be greater than 0")

    jql = f'{field} = "{_escape_jql_value(user_identifier)}" ORDER BY updated DESC'
    issues: list[dict[str, Any]] = []
    start_at = 0

    while True:
        batch = jira_client.search_issues(
            jql,
            startAt=start_at,
            maxResults=min(max_results, 100),
        )

        for issue in batch:
            issues.append(
                {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "assignee": getattr(issue.fields.assignee, "displayName", None),
                    "reporter": getattr(issue.fields.reporter, "displayName", None),
                    "updated": issue.fields.updated,
                }
            )

        if len(batch) < min(max_results, 100):
            break

        start_at += len(batch)

    return issues


def get_worklogs(
    jira_client: JIRA,
    *,
    person: str | None = None,
    group: str | None = None,
    issue_keys: list[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return worklogs for a person, group, or a set of issues."""
    if person and group:
        raise ValueError("Specify either person or group, not both")

    if not issue_keys and not person and not group:
        raise ValueError("Specify at least one of person, group, or issue_keys")

    target_identifiers: list[str] | None = None
    if person:
        target_identifiers = [person]
    elif group:
        target_identifiers = _collect_group_member_identifiers(jira_client, group)

    issue_keys_to_fetch = list(dict.fromkeys(issue_keys or []))
    if not issue_keys_to_fetch:
        jql = _build_worklog_jql(
            target_identifiers=target_identifiers,
            from_date=from_date,
            to_date=to_date,
        )
        issue_keys_to_fetch = []
        start_at = 0

        while True:
            batch = jira_client.search_issues(jql, startAt=start_at, maxResults=100)
            issue_keys_to_fetch.extend(issue.key for issue in batch)

            if len(batch) < 100:
                break

            start_at += len(batch)

    filtered_target_identifiers = (
        set(target_identifiers) if target_identifiers else None
    )
    worklogs: list[dict[str, Any]] = []

    for issue_key in issue_keys_to_fetch:
        issue_worklogs = jira_client.worklogs(issue_key)
        for worklog in issue_worklogs:
            if not _worklog_matches_filters(
                worklog,
                target_identifiers=filtered_target_identifiers,
                from_date=from_date,
                to_date=to_date,
            ):
                continue

            worklogs.append(
                {
                    "issue_key": issue_key,
                    "worklog_id": getattr(worklog, "id", None),
                    "author": getattr(
                        getattr(worklog, "author", None), "displayName", None
                    ),
                    "started": _format_date(getattr(worklog, "started", None)),
                    "time_spent_seconds": getattr(worklog, "timeSpentSeconds", None),
                    "comment": getattr(worklog, "comment", None),
                }
            )

    return worklogs


def build_jira_client() -> JIRA:
    """Build a Jira client from environment variables.

    Runs :func:`preflight` first so a bad URL/token fails with an actionable
    :class:`JiraConnectionError` instead of the opaque ``JSONDecodeError`` the
    ``jira`` library raises from its eager ``server_info()`` call at construction.
    """
    missing = [name for name in ("JIRA_URL", "JIRA_TOKEN") if not os.getenv(name)]
    if missing:
        raise JiraConnectionError(
            "Missing required JIRA env var(s): " + ", ".join(missing) + ". Set them in "
            "the .env / config.JIRA_SERVER_ENV before starting the JIRA MCP server."
        )

    server = os.environ["JIRA_URL"]
    api_token = os.environ["JIRA_TOKEN"]
    verify_ssl = _env_bool("JIRA_VERIFY_SSL", False)
    username = os.getenv("JIRA_USERNAME")

    preflight(server, api_token, username, verify_ssl)

    if username:
        return JIRA(
            server=server,
            basic_auth=(username, api_token),
            options={"verify": verify_ssl},
        )

    return JIRA(server=server, token_auth=api_token, options={"verify": verify_ssl})


def main() -> None:
    """Load environment settings and print issues for the requested user."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch Jira issues or worklogs")
    parser.add_argument(
        "user", nargs="?", help="Jira user identifier, email, or accountId"
    )
    parser.add_argument(
        "--field",
        choices=("assignee", "reporter"),
        default="assignee",
        help="Which Jira field to search against",
    )
    parser.add_argument(
        "--worklogs", action="store_true", help="Fetch worklogs instead of issues"
    )
    parser.add_argument("--person", help="Filter worklogs by person")
    parser.add_argument("--group", help="Filter worklogs by Jira group")
    parser.add_argument(
        "--per-person",
        action="store_true",
        help="Aggregate worklogs per person and print totals",
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        help="Only include worklogs on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        dest="to_date",
        help="Only include worklogs on or before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--issue",
        action="append",
        dest="issue_keys",
        help="Restrict worklogs to a specific issue key. Can be repeated.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Probe JIRA connectivity (status / Content-Type / body) and exit. "
        "Run this to diagnose the JSONDecodeError without starting the server.",
    )
    args = parser.parse_args()

    if args.check:
        missing = [name for name in ("JIRA_URL", "JIRA_TOKEN") if not os.getenv(name)]
        if missing:
            raise SystemExit("Missing required env var(s): " + ", ".join(missing))
        try:
            info = preflight(
                os.environ["JIRA_URL"],
                os.environ.get("JIRA_TOKEN"),
                os.getenv("JIRA_USERNAME"),
                _env_bool("JIRA_VERIFY_SSL", False),
            )
        except JiraConnectionError as exc:
            raise SystemExit(str(exc))
        sys.stdout.write(
            f"OK  {os.environ['JIRA_URL']} -> {info.get('serverTitle')} "
            f"v{info.get('version')} (baseUrl={info.get('baseUrl')})\n"
        )
        return

    jira_client = build_jira_client()

    if args.worklogs:
        worklogs = get_worklogs(
            jira_client,
            person=args.person,
            group=args.group,
            issue_keys=args.issue_keys,
            from_date=_parse_date(args.from_date),
            to_date=_parse_date(args.to_date),
        )

        if args.per_person:
            totals: dict[str, dict[str, Any]] = {}
            for w in worklogs:
                author = w.get("author") or "(unknown)"
                entry = totals.setdefault(
                    author, {"seconds": 0, "count": 0, "issues": set()}
                )
                entry["seconds"] += w.get("time_spent_seconds") or 0
                entry["count"] += 1
                issue_key = w.get("issue_key")
                if issue_key:
                    entry["issues"].add(issue_key)

            for author, data in sorted(totals.items(), key=lambda x: x[0].lower()):
                issues_list = ",".join(sorted(data["issues"])) if data["issues"] else ""
                sys.stdout.write(
                    f"{author}: {data['seconds']}s across {data['count']} entries; issues={issues_list}\n"
                )
        else:
            for worklog in worklogs:
                sys.stdout.write(
                    f"{worklog['issue_key']} | {worklog['author']} | {worklog['started']} | "
                    f"{worklog['time_spent_seconds']}s | {worklog['comment']}\n"
                )
        return

    if not args.user:
        raise SystemExit("user is required unless --worklogs is used")

    issues = get_user_issues(jira_client, args.user, field=args.field)

    for issue in issues:
        sys.stdout.write(f"{issue['key']}: {issue['summary']} [{issue['status']}]\n")


if __name__ == "__main__":
    main()
