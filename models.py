"""Pydantic models for every Jira resource type returned by the tool functions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Nested / shared ───────────────────────────────────────────────────────────


class Comment(BaseModel):
    """A single comment on a Jira issue."""

    author: str | None = None
    """Display name of the comment author."""

    body: str | None = None
    """Raw comment body text (may contain Atlassian Document Format markup)."""

    created: str | None = None
    """ISO-8601 timestamp when the comment was posted."""


class Subtask(BaseModel):
    """A child issue (subtask) linked to a parent issue."""

    key: str
    """Issue key of the subtask, e.g. ``'PROJ-124'``."""

    summary: str | None = None
    """One-line summary of the subtask."""

    status: str | None = None
    """Current workflow status name, e.g. ``'In Progress'``."""


class IssueLink(BaseModel):
    """A directional relationship between two Jira issues."""

    type: str | None = None
    """Link type name, e.g. ``'blocks'``, ``'is cloned by'``, ``'relates to'``."""

    direction: Literal["inward", "outward"]
    """Whether the linked issue is the *source* (outward) or *target* (inward) of the
    relationship from the perspective of the issue being fetched."""

    key: str
    """Issue key of the linked issue, e.g. ``'PROJ-99'``."""

    summary: str | None = None
    """One-line summary of the linked issue."""

    status: str | None = None
    """Current workflow status name of the linked issue."""


class ChangelogEntry(BaseModel):
    """A single field-change event from an issue's audit history.

    The ``from_`` field is serialized as ``"from"`` in JSON output to match the
    Jira API convention. Use ``model_dump(by_alias=True)`` when serializing.
    """

    model_config = ConfigDict(populate_by_name=True)

    author: str | None = None
    """Display name of the user who made the change."""

    created: str | None = None
    """ISO-8601 timestamp of the change."""

    field: str | None = None
    """Name of the field that changed, e.g. ``'status'``, ``'assignee'``."""

    from_: str | None = Field(None, alias="from")
    """Previous value of the field (human-readable string)."""

    to: str | None = None
    """New value of the field (human-readable string)."""


# ── Issues ────────────────────────────────────────────────────────────────────


class IssueResult(BaseModel):
    """A Jira issue returned by :func:`search_issues`.

    Contains ``key`` plus whichever fields were requested. The five default
    fields are typed explicitly; any additional requested fields (e.g. custom
    fields or ``labels``) are preserved as extra attributes so no data is lost.
    """

    model_config = ConfigDict(extra="allow")

    key: str
    """Issue key, e.g. ``'PROJ-123'``."""

    summary: str | None = None
    """One-line issue title."""

    status: str | None = None
    """Current workflow status name, e.g. ``'In Progress'``."""

    assignee: str | None = None
    """Display name of the currently assigned user."""

    priority: str | None = None
    """Priority name, e.g. ``'High'``, ``'Medium'``."""

    timespent: int | None = None
    """Total seconds logged against this issue."""

    updated: str | None = None
    """ISO-8601 timestamp of the most recent update."""


class IssueDetail(BaseModel):
    """Full details of a single Jira issue, including nested sub-resources.

    Returned by :func:`get_issue_detail`. Includes every field from
    :class:`IssueResult` plus description, comments, subtasks, issue links,
    and the full changelog.
    """

    key: str
    """Issue key, e.g. ``'PROJ-123'``."""

    summary: str | None = None
    """One-line issue title."""

    status: str | None = None
    """Current workflow status name."""

    assignee: str | None = None
    """Display name of the currently assigned user."""

    reporter: str | None = None
    """Display name of the user who created the issue."""

    priority: str | None = None
    """Priority name, e.g. ``'High'``."""

    description: str | None = None
    """Full issue description (may contain Atlassian Document Format markup)."""

    created: str | None = None
    """ISO-8601 timestamp when the issue was created."""

    updated: str | None = None
    """ISO-8601 timestamp of the most recent update."""

    comments: list[Comment] = Field(default_factory=list)
    """All comments on the issue in chronological order."""

    subtasks: list[Subtask] = Field(default_factory=list)
    """Direct child issues (subtasks) of this issue."""

    links: list[IssueLink] = Field(default_factory=list)
    """All inward and outward issue links."""

    changelog: list[ChangelogEntry] = Field(default_factory=list)
    """Full audit history — one entry per individual field change."""


# ── Worklogs ──────────────────────────────────────────────────────────────────


class Worklog(BaseModel):
    """A worklog entry on a specific issue, returned by :func:`get_issue_worklogs`.

    Includes the comment text, which the bulk endpoint does not provide. Use
    this model when the worklog description matters (e.g. daily standup notes).
    """

    worklog_id: str | None = None
    """Jira internal worklog ID."""

    author_display_name: str | None = None
    """Human-readable name of the person who logged the time."""

    author_account_id: str | None = None
    """Jira accountId of the author — use this in JQL filters."""

    time_spent_seconds: int | None = None
    """Duration of the worklog in seconds."""

    started: str | None = None
    """ISO-8601 datetime when the work was started."""

    comment: str | None = None
    """Optional free-text note recorded with the worklog."""


class BulkWorklog(BaseModel):
    """A worklog entry returned by :func:`get_worklogs_updated_since`.

    Omits the ``comment`` field (not available from the bulk query path).
    Includes ``issue_key`` so results can be correlated back to the originating
    issue without a second lookup.
    """

    issue_key: str
    """Key of the issue this worklog belongs to, e.g. ``'PROJ-123'``."""

    worklog_id: str | None = None
    """Jira internal worklog ID."""

    author_display_name: str | None = None
    """Human-readable name of the person who logged the time."""

    author_account_id: str | None = None
    """Jira accountId of the author — use this in JQL assignee filters."""

    time_spent_seconds: int | None = None
    """Duration of the worklog in seconds."""

    started: str | None = None
    """ISO-8601 datetime when the work was started."""


# ── Sprints ───────────────────────────────────────────────────────────────────


class Sprint(BaseModel):
    """A Jira sprint, returned by :func:`get_active_sprint` and :func:`get_board_sprints`."""

    id: int
    """Numeric sprint ID — pass this to :func:`get_sprint_issues`."""

    name: str
    """Human-readable sprint name, e.g. ``'Sprint 42'``."""

    goal: str | None = None
    """Optional sprint goal set by the team."""

    start_date: str | None = None
    """ISO-8601 date when the sprint started."""

    end_date: str | None = None
    """ISO-8601 date when the sprint is scheduled to end."""

    state: str | None = None
    """Sprint state: ``'active'``, ``'closed'``, or ``'future'``."""


class SprintIssue(BaseModel):
    """An issue within a sprint, returned by :func:`get_sprint_issues`.

    Carries enough data to compute velocity (``time_spent_seconds``), breakdown
    by status, and per-person assignment without additional API calls.
    """

    key: str
    """Issue key, e.g. ``'PROJ-123'``."""

    summary: str | None = None
    """One-line issue title."""

    status: str | None = None
    """Current workflow status name."""

    assignee: str | None = None
    """Display name of the assigned user."""

    assignee_account_id: str | None = None
    """Jira accountId of the assigned user — useful for grouping by person."""

    time_spent_seconds: int | None = None
    """Total seconds logged against this issue."""

    priority: str | None = None
    """Priority name, e.g. ``'High'``."""


# ── Users & Groups ────────────────────────────────────────────────────────────


class GroupMember(BaseModel):
    """A member of a Jira group, returned by :func:`get_group_members`."""

    account_id: str
    """Jira accountId — the value to use in JQL ``assignee = <accountId>`` clauses."""

    display_name: str | None = None
    """Human-readable full name."""

    email: str | None = None
    """Primary email address registered in Jira."""

    active: bool | None = None
    """Whether the user account is currently active."""


class User(BaseModel):
    """A Jira user returned by :func:`find_user`.

    Use ``account_id`` — not ``display_name`` — in any subsequent JQL queries.
    """

    account_id: str | None = None
    """Jira accountId — the value required by JQL assignee filters."""

    display_name: str | None = None
    """Human-readable full name."""

    email: str | None = None
    """Primary email address registered in Jira."""

    active: bool | None = None
    """Whether the user account is currently active."""


# ── Projects & Metadata ───────────────────────────────────────────────────────


class Project(BaseModel):
    """A Jira project, returned by :func:`list_projects`."""

    key: str
    """Short project key used in issue keys and JQL, e.g. ``'PROJ'``."""

    name: str
    """Full human-readable project name."""

    id: str
    """Jira internal numeric project ID (as a string)."""


# ── Change Requests (SCR / SYCR) ──────────────────────────────────────────────


class Attachment(BaseModel):
    """Metadata for a file attached to a Jira issue. Bytes are NOT downloaded here
    (Phase 2 `describe_attachment` handles image content via the VLM)."""

    filename: str | None = None
    """Original attachment filename, e.g. ``'state_diagram.png'``."""

    mime_type: str | None = None
    """MIME type as reported by Jira, e.g. ``'image/png'``."""

    size: int | None = None
    """Size in bytes."""

    attachment_id: str | None = None
    """Jira internal attachment id (string)."""

    content_url: str | None = None
    """Authenticated download URL for the attachment bytes."""

    created: str | None = None
    """ISO-8601 timestamp when the attachment was added."""

    author: str | None = None
    """Display name of the user who attached the file."""


class ChangeRequestDetail(IssueDetail):
    """Full SCR/SYCR change request: every standard :class:`IssueDetail` field plus the
    **Details** custom-field panel and attachment metadata. Returned by
    :func:`tools.get_change_request`."""

    custom_fields: dict[str, Any] = Field(default_factory=dict)
    """The Details panel: ``{human_field_name: value}`` for every non-empty custom field
    (Classification, Configuration Item, Applicability, Block, CT Type, Analysis,
    ``impacted``, …)."""

    attachments: list[Attachment] = Field(default_factory=list)
    """Attachment metadata (no bytes)."""


class ChangeRequestSummary(BaseModel):
    """A single SCR/SYCR row from :func:`tools.search_change_requests`."""

    key: str
    """Issue key, e.g. ``'PROJE1SCR-403'``."""

    summary: str | None = None
    """One-line title."""

    status: str | None = None
    """Workflow status name."""

    priority: str | None = None
    """Priority name."""

    created: str | None = None
    """ISO-8601 creation timestamp."""

    updated: str | None = None
    """ISO-8601 last-update timestamp."""

    project: str | None = None
    """Project key the change request belongs to (SCR vs SYCR)."""
