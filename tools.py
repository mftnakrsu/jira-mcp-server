"""Tool implementations and dispatch for the Jira summarizer LLM interface."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from jira import JIRA
from pydantic import BaseModel

from main import _coerce_worklog_date, _escape_jql_value
from models import (
    Attachment,
    BulkWorklog,
    ChangeRequestDetail,
    ChangeRequestSummary,
    ChangelogEntry,
    Comment,
    GroupMember,
    IssueDetail,
    IssueLink,
    IssueResult,
    Project,
    Sprint,
    SprintIssue,
    Subtask,
    User,
    Worklog,
)

TOOLS = [
    # ── Issues ──────────────────────────────────────────────────
    {
        "name": "search_issues",
        "description": (
            "Search Jira issues using JQL. Use for weekly summaries, per-person reports, "
            "sprint status, blocked issues, or anything filtered by assignee/date/status. "
            "Always use accountId (not displayName) in JQL assignee filters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jql": {
                    "type": "string",
                    "description": "JQL query e.g. 'assignee = 5b10a2844c20165700ede21g AND updated >= -7d'",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to return. Default: summary, status, assignee, priority, timespent, updated",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max issues to return (default 50, max 100)",
                },
            },
            "required": ["jql"],
        },
    },
    {
        "name": "get_issue_detail",
        "description": (
            "Fetch full details for a single issue: description, all comments, "
            "subtasks, linked issues, and changelog. Use when the user asks about "
            "a specific ticket or needs comment/blocker context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "e.g. PROJ-123"},
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "get_change_request",
        "description": (
            "Fetch a full SCR/SYCR change request: every standard field plus the Details "
            "custom-field panel (Classification, Configuration Item, Applicability, Block, "
            "CT Type, Analysis, impacted, ...) and attachment metadata. Use to read a change "
            "request's full content before tracing it to related requirements or source control."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Change-request key, e.g. 'PROJE1SCR-403' or 'PROJ1SYCR-425'.",
                },
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "search_change_requests",
        "description": (
            "Search/list SCR or SYCR change requests in a JIRA project, newest first by "
            "default. Use for 'latest SCRs/SYCRs' or full-text change-request search. "
            "'project' is the SCR or SYCR project key (e.g. PROJE1SCR for SCR, PROJ1SYCR "
            "for SYCR)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "SCR or SYCR project key, e.g. 'PROJE1SCR' or 'PROJ1SYCR'.",
                },
                "text": {"type": "string", "description": "Optional free-text JQL 'text ~' filter."},
                "status": {"type": "string", "description": "Optional status filter."},
                "created_since": {
                    "type": "string",
                    "description": "Optional lower bound on created date: '-30d' or '2026-01-01'.",
                },
                "updated_since": {
                    "type": "string",
                    "description": "Optional lower bound on updated date: '-7d' or '2026-01-01'.",
                },
                "order_by": {
                    "type": "string",
                    "description": "JQL ORDER BY clause (default 'created DESC').",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max rows (default 50, cap 100).",
                },
            },
            "required": ["project"],
        },
    },
    # ── Worklogs ─────────────────────────────────────────────────
    {
        "name": "get_issue_worklogs",
        "description": (
            "Get all worklogs for a single issue including author, time spent, "
            "start time, and comment. Use when you need worklog notes alongside hours."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "get_worklogs_updated_since",
        "description": (
            "Bulk-fetch ALL worklogs updated across all projects in the last N days. "
            "Best tool for weekly time reports and per-person hour summaries. "
            "Returns author accountId, timeSpentSeconds, and started date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ago": {
                    "type": "integer",
                    "description": "How many days back to look (e.g. 7 for weekly report)",
                },
            },
            "required": ["days_ago"],
        },
    },
    # ── Sprints ──────────────────────────────────────────────────
    {
        "name": "get_active_sprint",
        "description": (
            "Get the currently active sprint for a board: name, goal, start date, end date. "
            "Call this first for any sprint status or velocity report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "board_id": {"type": "integer"},
            },
            "required": ["board_id"],
        },
    },
    {
        "name": "get_sprint_issues",
        "description": (
            "Get all issues in a specific sprint with status, assignee, and time spent. "
            "Use to calculate done/in-progress/blocked counts and velocity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "board_id": {"type": "integer"},
                "sprint_id": {"type": "integer"},
            },
            "required": ["board_id", "sprint_id"],
        },
    },
    {
        "name": "get_board_sprints",
        "description": (
            "List all sprints for a board filtered by state. "
            "Use to find sprint IDs for historical reports or to list past sprints."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "board_id": {"type": "integer"},
                "state": {
                    "type": "string",
                    "enum": ["active", "closed", "future"],
                    "description": "Default: active",
                },
            },
            "required": ["board_id"],
        },
    },
    # ── Users & Groups ───────────────────────────────────────────
    {
        "name": "get_group_members",
        "description": (
            "Get all Jira users in a group (e.g. 'backend-team'). "
            "Returns displayName and accountId. Call this first for any group-level report, "
            "then use the accountIds in search_issues JQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_name": {"type": "string"},
            },
            "required": ["group_name"],
        },
    },
    {
        "name": "find_user",
        "description": (
            "Resolve a person's name or email to their Jira accountId. "
            "Always call this before filtering issues by assignee — "
            "JQL requires accountId, not display name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or email, e.g. 'ali' or 'ali@company.com'",
                },
            },
            "required": ["query"],
        },
    },
    # ── Projects & Metadata ──────────────────────────────────────
    {
        "name": "list_projects",
        "description": (
            "List all Jira projects the API token has access to. "
            "Use when the user doesn't specify a project key."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_project_statuses",
        "description": (
            "Get all valid issue status names for a project (e.g. 'In Progress', 'Code Review', 'Done'). "
            "Call this before writing JQL status filters to avoid invalid status errors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_key": {"type": "string", "description": "e.g. PROJ"},
            },
            "required": ["project_key"],
        },
    },
]


def _serialize_field(value: Any) -> Any:
    """Convert a Jira resource field to a plain JSON-serializable value."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_serialize_field(v) for v in value]
    if hasattr(value, "name"):
        return value.name
    if hasattr(value, "displayName"):
        return value.displayName
    return str(value)


# ── Change-request field helpers (pure, deterministic) ────────────────────────

_FIELDS_MAP_CACHE: dict[int, dict[str, dict]] = {}


def _simplify_field_value(value: Any) -> Any:
    """Collapse a raw JIRA field value (from ``issue.raw['fields']``) to a lean,
    JSON-serializable form: option dicts → their ``value``/``name``, user dicts →
    ``displayName``, lists → element-wise, scalars unchanged."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_simplify_field_value(v) for v in value]
    if isinstance(value, dict):
        for key in ("value", "name", "displayName"):
            inner = value.get(key)
            if isinstance(inner, (str, int, float, bool)):
                return inner
        return {k: _simplify_field_value(v) for k, v in value.items()}
    return str(value)


def _fields_map(client: Any) -> dict[str, dict]:
    """Return ``{field_id: {"name": str, "custom": bool}}`` from ``client.fields()``,
    cached per client (field definitions are static within a process)."""
    cache_key = id(client)
    cached = _FIELDS_MAP_CACHE.get(cache_key)
    if cached is None:
        cached = {
            f["id"]: {"name": f.get("name", f["id"]), "custom": bool(f.get("custom"))}
            for f in client.fields()
        }
        _FIELDS_MAP_CACHE[cache_key] = cached
    return cached


def _collect_custom_fields(
    raw_fields: dict[str, Any], fields_map: dict[str, dict]
) -> dict[str, Any]:
    """Map non-empty **custom** fields (the Details panel) to
    ``{human_name: simplified_value}``. Standard fields and null/empty values are omitted."""
    out: dict[str, Any] = {}
    for field_id, meta in fields_map.items():
        if not meta.get("custom"):
            continue
        simplified = _simplify_field_value(raw_fields.get(field_id))
        if simplified in (None, "", [], {}):
            continue
        out[meta["name"]] = simplified
    return out


def _extract_attachments(raw_fields: dict[str, Any]) -> list[Attachment]:
    """Build :class:`~models.Attachment` metadata (no bytes) from raw issue fields."""
    result: list[Attachment] = []
    for att in raw_fields.get("attachment") or []:
        att_id = att.get("id")
        result.append(
            Attachment(
                filename=att.get("filename"),
                mime_type=att.get("mimeType"),
                size=att.get("size"),
                attachment_id=str(att_id) if att_id is not None else None,
                content_url=att.get("content"),
                created=att.get("created"),
                author=(att.get("author") or {}).get("displayName"),
            )
        )
    return result


# ── Issues ────────────────────────────────────────────────────────────────────


def search_issues(
    client: JIRA,
    jql: str,
    fields: list[str] | None = None,
    max_results: int = 50,
) -> list[IssueResult]:
    """Search Jira issues using a JQL query and return serialized field data.

    Each result contains ``key`` plus one entry per requested field.
    Jira resource objects (status, assignee, priority, etc.) are collapsed to
    their ``name`` or ``displayName`` string so the output is JSON-serializable.

    Args:
        client: Authenticated JIRA client.
        jql: JQL query string, e.g. ``'assignee = <accountId> AND updated >= -7d'``.
            Always use ``accountId`` (not display name) in assignee filters.
        fields: Field names to include in each result. Defaults to
            ``['summary', 'status', 'assignee', 'priority', 'timespent', 'updated']``.
        max_results: Maximum number of issues to return (default 50, cap 100).

    Returns:
        List of :class:`~models.IssueResult`, one per issue. Extra requested
        fields beyond the defaults are preserved on the model via ``extra='allow'``.
    """
    field_list = fields or ["summary", "status", "assignee", "priority", "timespent", "updated"]
    issues = client.search_issues(jql, fields=field_list, maxResults=max_results)
    result = []
    for issue in issues:
        entry: dict[str, Any] = {"key": issue.key}
        for field_name in field_list:
            entry[field_name] = _serialize_field(getattr(issue.fields, field_name, None))
        result.append(IssueResult(**entry))
    return result


def _issue_detail_from_issue(issue: Any) -> IssueDetail:
    """Build an :class:`~models.IssueDetail` from an already-fetched Jira issue object
    (expanded with ``changelog``). Shared by :func:`get_issue_detail` and
    :func:`get_change_request` so the comment/subtask/link/changelog extraction lives once."""
    f = issue.fields

    comments = [
        Comment(
            author=getattr(getattr(c, "author", None), "displayName", None),
            body=getattr(c, "body", None),
            created=getattr(c, "created", None),
        )
        for c in getattr(getattr(f, "comment", None), "comments", [])
    ]

    subtasks = [
        Subtask(
            key=s.key,
            summary=getattr(s.fields, "summary", None),
            status=getattr(getattr(s.fields, "status", None), "name", None),
        )
        for s in (getattr(f, "subtasks", None) or [])
    ]

    links = []
    for link in getattr(f, "issuelinks", None) or []:
        linked = getattr(link, "inwardIssue", None) or getattr(link, "outwardIssue", None)
        if linked:
            links.append(
                IssueLink(
                    type=getattr(getattr(link, "type", None), "name", None),
                    direction="inward" if getattr(link, "inwardIssue", None) else "outward",
                    key=linked.key,
                    summary=getattr(getattr(linked, "fields", None), "summary", None),
                    status=getattr(
                        getattr(getattr(linked, "fields", None), "status", None), "name", None
                    ),
                )
            )

    changelog = [
        ChangelogEntry(**{
            "author": getattr(getattr(h, "author", None), "displayName", None),
            "created": getattr(h, "created", None),
            "field": getattr(item, "field", None),
            "from": getattr(item, "fromString", None),
            "to": getattr(item, "toString", None),
        })
        for h in getattr(getattr(issue, "changelog", None), "histories", [])
        for item in getattr(h, "items", [])
    ]

    return IssueDetail(
        key=issue.key,
        summary=getattr(f, "summary", None),
        status=getattr(getattr(f, "status", None), "name", None),
        assignee=getattr(getattr(f, "assignee", None), "displayName", None),
        reporter=getattr(getattr(f, "reporter", None), "displayName", None),
        priority=getattr(getattr(f, "priority", None), "name", None),
        description=getattr(f, "description", None),
        created=getattr(f, "created", None),
        updated=getattr(f, "updated", None),
        comments=comments,
        subtasks=subtasks,
        links=links,
        changelog=changelog,
    )


def get_issue_detail(client: JIRA, issue_key: str) -> IssueDetail:
    """Fetch full details for a single issue including comments, subtasks, links, and changelog.

    Args:
        client: Authenticated JIRA client.
        issue_key: Issue key, e.g. ``'PROJ-123'``.

    Returns:
        :class:`~models.IssueDetail`.
    """
    issue = client.issue(issue_key, expand="changelog")
    return _issue_detail_from_issue(issue)


def get_change_request(client: JIRA, issue_key: str) -> ChangeRequestDetail:
    """Fetch a full SCR/SYCR change request: every standard field PLUS the Details
    custom-field panel and attachment metadata.

    Fetches with ``fields="*all"`` so custom fields (Classification, Configuration Item,
    Applicability, Block, CT Type, Analysis, ``impacted``, …) are present, then resolves
    their human-readable names via the cached :func:`_fields_map`. Attachment *metadata*
    only — bytes are not downloaded (Phase 2 ``describe_attachment`` does the VLM step).

    Args:
        client: Authenticated JIRA client.
        issue_key: Change-request key, e.g. ``'PROJE1SCR-403'`` or ``'PROJ1SYCR-425'``.

    Returns:
        :class:`~models.ChangeRequestDetail`.
    """
    issue = client.issue(issue_key, fields="*all", expand="changelog")
    detail = _issue_detail_from_issue(issue)
    raw_fields = (getattr(issue, "raw", None) or {}).get("fields", {}) or {}
    return ChangeRequestDetail(
        **detail.model_dump(),
        custom_fields=_collect_custom_fields(raw_fields, _fields_map(client)),
        attachments=_extract_attachments(raw_fields),
    )


# ── Worklogs ──────────────────────────────────────────────────────────────────


def get_issue_worklogs(client: JIRA, issue_key: str) -> list[Worklog]:
    """Return all worklogs for a single issue.

    Prefer this over ``get_worklogs_updated_since`` when you already know the
    issue key and need the full worklog comment alongside hours — the bulk
    endpoint doesn't return comments.

    Args:
        client: Authenticated JIRA client.
        issue_key: Issue key, e.g. ``'PROJ-123'``.

    Returns:
        List of :class:`~models.Worklog` entries for the issue.
    """
    return [
        Worklog(
            worklog_id=getattr(wl, "id", None),
            author_display_name=getattr(getattr(wl, "author", None), "displayName", None),
            author_account_id=getattr(getattr(wl, "author", None), "accountId", None),
            time_spent_seconds=getattr(wl, "timeSpentSeconds", None),
            started=getattr(wl, "started", None),
            comment=getattr(wl, "comment", None),
        )
        for wl in client.worklogs(issue_key)
    ]


def get_worklogs_updated_since(client: JIRA, days_ago: int) -> list[BulkWorklog]:
    """Bulk-fetch all worklogs logged across all projects in the last N days.

    Uses JQL ``worklogDate >= -Nd`` to find candidate issues, then retrieves
    each issue's worklogs and filters to entries whose ``started`` date falls
    within the window. This is the right tool for weekly time reports or
    per-person hour summaries when you don't know the specific issue keys
    in advance.

    Note: this may be slow on large Jira instances because it fetches worklogs
    for every matching issue. For targeted queries on known issue keys, use
    ``get_issue_worklogs`` instead.

    Args:
        client: Authenticated JIRA client.
        days_ago: How many days back to include, e.g. ``7`` for a weekly report.

    Returns:
        List of dicts with keys: ``issue_key``, ``worklog_id``,
        ``author_display_name``, ``author_account_id``, ``time_spent_seconds``,
        ``started``.
    """
    from_date = (datetime.now() - timedelta(days=days_ago)).date()
    jql = f'worklogDate >= "{from_date.isoformat()}" ORDER BY updated DESC'

    issue_keys: list[str] = []
    start_at = 0
    while True:
        batch = client.search_issues(jql, fields=["summary"], startAt=start_at, maxResults=100)
        issue_keys.extend(issue.key for issue in batch)
        if len(batch) < 100:
            break
        start_at += len(batch)

    worklogs: list[BulkWorklog] = []
    for issue_key in issue_keys:
        for wl in client.worklogs(issue_key):
            wl_date = _coerce_worklog_date(getattr(wl, "started", None))
            if wl_date and wl_date >= from_date:
                worklogs.append(
                    BulkWorklog(
                        issue_key=issue_key,
                        worklog_id=getattr(wl, "id", None),
                        author_display_name=getattr(
                            getattr(wl, "author", None), "displayName", None
                        ),
                        author_account_id=getattr(
                            getattr(wl, "author", None), "accountId", None
                        ),
                        time_spent_seconds=getattr(wl, "timeSpentSeconds", None),
                        started=getattr(wl, "started", None),
                    )
                )
    return worklogs


# ── Sprints ───────────────────────────────────────────────────────────────────


def get_active_sprint(client: JIRA, board_id: int) -> Sprint | None:
    """Return the currently active sprint for a board, or None if no sprint is active.

    Call this first before any sprint status or velocity report so you have the
    sprint ID needed by ``get_sprint_issues``.

    Args:
        client: Authenticated JIRA client.
        board_id: Numeric ID of the Jira board.

    Returns:
        :class:`~models.Sprint` for the active sprint, or ``None`` if there is
        no active sprint on the board.
    """
    sprints = client.sprints(board_id, state="active")
    if not sprints:
        return None
    s = sprints[0]
    return Sprint(
        id=s.id,
        name=s.name,
        goal=getattr(s, "goal", None),
        start_date=getattr(s, "startDate", None),
        end_date=getattr(s, "endDate", None),
        state=getattr(s, "state", None),
    )


def get_sprint_issues(
    client: JIRA, board_id: int, sprint_id: int  # noqa: ARG001 board_id kept for schema parity
) -> list[SprintIssue]:
    """Return all issues in a sprint with status, assignee, and time spent.

    Sprint IDs are globally unique in Jira, so ``board_id`` is accepted for
    schema parity but is not needed in the underlying JQL query.

    Use the results to compute done/in-progress/blocked counts or sprint
    velocity (sum of ``time_spent_seconds`` for completed issues).

    Args:
        client: Authenticated JIRA client.
        board_id: Numeric board ID (accepted for schema compatibility; unused in query).
        sprint_id: Numeric sprint ID, obtained from ``get_active_sprint`` or
            ``get_board_sprints``.

    Returns:
        List of :class:`~models.SprintIssue` for every issue in the sprint.
    """
    issues = client.search_issues(
        f"sprint = {sprint_id}",
        fields=["summary", "status", "assignee", "timespent", "priority"],
        maxResults=100,
    )
    return [
        SprintIssue(
            key=issue.key,
            summary=getattr(issue.fields, "summary", None),
            status=getattr(getattr(issue.fields, "status", None), "name", None),
            assignee=getattr(getattr(issue.fields, "assignee", None), "displayName", None),
            assignee_account_id=getattr(
                getattr(issue.fields, "assignee", None), "accountId", None
            ),
            time_spent_seconds=getattr(issue.fields, "timespent", None),
            priority=getattr(getattr(issue.fields, "priority", None), "name", None),
        )
        for issue in issues
    ]


def get_board_sprints(
    client: JIRA, board_id: int, state: str = "active"
) -> list[Sprint]:
    """List all sprints for a board filtered by state.

    Use this to discover sprint IDs for historical velocity reports or to list
    upcoming sprints. Combine with ``get_sprint_issues`` to drill into any
    specific sprint.

    Args:
        client: Authenticated JIRA client.
        board_id: Numeric ID of the Jira board.
        state: One of ``'active'`` (default), ``'closed'``, or ``'future'``.

    Returns:
        List of :class:`~models.Sprint` for all matching sprints on the board.
    """
    return [
        Sprint(
            id=s.id,
            name=s.name,
            goal=getattr(s, "goal", None),
            state=getattr(s, "state", None),
            start_date=getattr(s, "startDate", None),
            end_date=getattr(s, "endDate", None),
        )
        for s in client.sprints(board_id, state=state)
    ]


# ── Users & Groups ────────────────────────────────────────────────────────────


def get_group_members(client: JIRA, group_name: str) -> list[GroupMember]:
    """Return all members of a Jira group with their accountId and display name.

    Call this first for any group-level report, then use the returned
    ``account_id`` values in JQL ``assignee in (...)`` filters via
    ``search_issues``.

    Args:
        client: Authenticated JIRA client.
        group_name: Exact Jira group name, e.g. ``'backend-team'``.

    Returns:
        List of dicts with keys: ``account_id``, ``display_name``, ``email``,
        ``active``.
    """
    members = client.group_members(group_name)
    return [
        GroupMember(
            account_id=account_id,
            display_name=data.get("displayName") or data.get("name"),
            email=data.get("emailAddress"),
            active=data.get("active"),
        )
        for account_id, data in members.items()
    ]


def find_user(client: JIRA, query: str) -> list[User]:
    """Resolve a person's name or email to their Jira accountId.

    Always call this before filtering issues by assignee — JQL requires
    ``accountId``, not a display name. The returned ``account_id`` is the
    value to use in JQL ``assignee = <accountId>`` clauses.

    Args:
        client: Authenticated JIRA client.
        query: Partial name or full email address, e.g. ``'ali'`` or
            ``'ali@company.com'``.

    Returns:
        List of matching :class:`~models.User` instances.
    """
    return [
        User(
            account_id=getattr(u, "accountId", None),
            display_name=getattr(u, "displayName", None),
            email=getattr(u, "emailAddress", None),
            active=getattr(u, "active", None),
        )
        for u in client.search_users(query)
    ]


# ── Projects & Metadata ───────────────────────────────────────────────────────


def list_projects(client: JIRA) -> list[Project]:
    """List all Jira projects accessible with the current API token.

    Use this when the user hasn't specified a project key and you need to
    present available options or build a JQL ``project in (...)`` clause.

    Args:
        client: Authenticated JIRA client.

    Returns:
        List of :class:`~models.Project` instances.

    """
    return [Project(key=p.key, name=p.name, id=p.id) for p in client.projects()]


def get_project_statuses(client: JIRA, project_key: str) -> list[str]:
    """Return the unique set of issue status names configured for a project.

    Call this before writing JQL ``status = '...'`` filters to avoid runtime
    errors from invalid or misspelled status names. Status names vary per
    project and workflow (e.g. ``'In Progress'``, ``'Code Review'``, ``'Done'``).

    The Jira API groups statuses by issue type; this function deduplicates
    across all issue types and returns a flat sorted list.

    Args:
        client: Authenticated JIRA client.
        project_key: Project key, e.g. ``'PROJ'``.

    Returns:
        Deduplicated list of status name strings in the order first encountered.

    """
    seen: set[str] = set()
    statuses: list[str] = []
    # project_issue_statuses returns raw dicts: [{name, statuses: [{id, name}]}]
    raw = client._get_json(f"project/{project_key}/statuses", base=client.JIRA_BASE_URL)
    for issue_type in raw:
        for status in issue_type.get("statuses", []):
            name = status.get("name")
            if name and name not in seen:
                seen.add(name)
                statuses.append(name)
    return statuses


# ── Change-request search ─────────────────────────────────────────────────────

_RELATIVE_DATE_RE = re.compile(r"^-?\d+[wdhm]$")


def _jql_date(value: str) -> str:
    """Return a JQL date token: a relative token (``-30d``, ``-4w``) is left UNQUOTED;
    an absolute date (``2026-01-01``) is quoted (and escaped)."""
    if _RELATIVE_DATE_RE.match(value):
        return value
    return f'"{_escape_jql_value(value)}"'


def _build_cr_jql(
    project: str,
    text: str | None = None,
    status: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    order_by: str = "created DESC",
) -> str:
    """Build a change-request JQL string. ``project`` selects SCR vs SYCR by project key."""
    clauses = [f'project = "{_escape_jql_value(project)}"']
    if text:
        clauses.append(f'text ~ "{_escape_jql_value(text)}"')
    if status:
        clauses.append(f'status = "{_escape_jql_value(status)}"')
    if created_since:
        clauses.append(f"created >= {_jql_date(created_since)}")
    if updated_since:
        clauses.append(f"updated >= {_jql_date(updated_since)}")
    return " AND ".join(clauses) + f" ORDER BY {order_by}"


def search_change_requests(
    client: JIRA,
    project: str,
    text: str | None = None,
    status: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    order_by: str = "created DESC",
    max_results: int = 50,
) -> list[ChangeRequestSummary]:
    """List / search SCR or SYCR change requests in a project, newest first by default.

    Thin wrapper over JIRA-native JQL (recency + full-text are JIRA-indexed — no local
    scan). ``project`` is the SCR or SYCR project key (e.g. ``'PROJE1SCR'`` for SCR,
    ``'PROJ1SYCR'`` for SYCR). ``created_since`` / ``updated_since`` accept relative
    tokens (``'-30d'``) or absolute dates (``'2026-01-01'``).

    Args:
        client: Authenticated JIRA client.
        project: SCR or SYCR project key.
        text: Optional free-text → JQL ``text ~ "<text>"``.
        status: Optional status filter.
        created_since: Optional lower bound on creation date.
        updated_since: Optional lower bound on last-update date.
        order_by: JQL ORDER BY clause (default ``"created DESC"`` = latest first).
        max_results: Cap on rows returned (capped at 100).

    Returns:
        List of :class:`~models.ChangeRequestSummary`.
    """
    jql = _build_cr_jql(project, text, status, created_since, updated_since, order_by)
    issues = client.search_issues(
        jql,
        fields=["summary", "status", "priority", "created", "updated", "project"],
        maxResults=min(max_results, 100),
    )
    rows: list[ChangeRequestSummary] = []
    for issue in issues:
        f = issue.fields
        rows.append(
            ChangeRequestSummary(
                key=issue.key,
                summary=getattr(f, "summary", None),
                status=_serialize_field(getattr(f, "status", None)),
                priority=_serialize_field(getattr(f, "priority", None)),
                created=getattr(f, "created", None),
                updated=getattr(f, "updated", None),
                project=getattr(getattr(f, "project", None), "key", None),
            )
        )
    return rows


# ── Dispatch ──────────────────────────────────────────────────────────────────

_TOOL_REGISTRY: dict[str, Any] = {
    "search_issues": search_issues,
    "get_issue_detail": get_issue_detail,
    "get_change_request": get_change_request,
    "search_change_requests": search_change_requests,
    "get_issue_worklogs": get_issue_worklogs,
    "get_worklogs_updated_since": get_worklogs_updated_since,
    "get_active_sprint": get_active_sprint,
    "get_sprint_issues": get_sprint_issues,
    "get_board_sprints": get_board_sprints,
    "get_group_members": get_group_members,
    "find_user": find_user,
    "list_projects": list_projects,
    "get_project_statuses": get_project_statuses,
}


def _serialize_result(value: Any) -> Any:
    """Recursively convert Pydantic model instances to plain dicts for JSON serialization.

    :class:`~pydantic.BaseModel` instances are serialized with ``by_alias=True``
    so that aliased fields (e.g. ``ChangelogEntry.from_`` → ``"from"``) appear
    with their expected names in the output.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, mode="json")
    if isinstance(value, list):
        return [_serialize_result(v) for v in value]
    return value


def dispatch_tool(client: JIRA, name: str, input_data: dict[str, Any]) -> Any:
    """Route a tool call by name to its implementation and serialize the result.

    Looks up the tool function in the registry, calls it with the provided
    input, then converts any returned Pydantic model instances to plain dicts
    so the output is ready for JSON serialization in an LLM tool-use response.

    Args:
        client: Authenticated JIRA client.
        name: Tool name matching one of the entries in :data:`TOOLS`.
        input_data: Keyword arguments to forward to the tool function, matching
            the tool's ``input_schema``.

    Returns:
        JSON-serializable result — a dict, list of dicts, list of strings, or
        ``None`` depending on the tool.

    Raises:
        ValueError: If ``name`` does not match any registered tool.

    """
    handler = _TOOL_REGISTRY.get(name)
    if handler is None:
        available = sorted(_TOOL_REGISTRY)
        raise ValueError(f"Unknown tool: {name!r}. Available tools: {available}")
    return _serialize_result(handler(client, **input_data))
