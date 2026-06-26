"""MCP server exposing all 11 Jira tools via stdio transport."""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from main import build_jira_client
from tools import dispatch_tool

load_dotenv()
_jira = build_jira_client()

mcp = FastMCP(
    name="jira",
    host="0.0.0.0",
    port=8001,
    instructions=(
        "Jira assistant. Always resolve user names to accountId with find_user before "
        "writing JQL assignee filters. Call get_project_statuses before using status "
        "values in JQL to avoid invalid-status errors."
    ),
)


# ── Issues ────────────────────────────────────────────────────────────────────


@mcp.tool(
    description=(
        "Search Jira issues using JQL. Use for weekly summaries, per-person reports, "
        "sprint status, blocked issues, or anything filtered by assignee/date/status. "
        "Always use accountId (not displayName) in JQL assignee filters."
    )
)
def search_issues(
    jql: str,
    fields: list[str] | None = None,
    max_results: int = 50,
) -> Any:
    """Search issues with JQL."""
    return dispatch_tool(
        _jira,
        "search_issues",
        {"jql": jql, "fields": fields, "max_results": max_results},
    )


@mcp.tool(
    description=(
        "Fetch full details for a single issue: description, all comments, "
        "subtasks, linked issues, and changelog. Use when the user asks about "
        "a specific ticket or needs comment/blocker context."
    )
)
def get_issue_detail(issue_key: str) -> Any:
    """Get full issue details including comments and changelog."""
    return dispatch_tool(_jira, "get_issue_detail", {"issue_key": issue_key})


@mcp.tool(
    description=(
        "Fetch a full SCR/SYCR change request: every standard field plus the Details "
        "custom-field panel (Classification, Configuration Item, Applicability, Block, "
        "CT Type, Analysis, impacted, ...) and attachment metadata. Use to read a change "
        "request's full content before tracing it to related requirements or source control."
    )
)
def get_change_request(issue_key: str) -> Any:
    """Fetch a full SCR/SYCR change request with custom fields and attachment metadata."""
    return dispatch_tool(_jira, "get_change_request", {"issue_key": issue_key})


@mcp.tool(
    description=(
        "Search/list SCR or SYCR change requests in a JIRA project, newest first by "
        "default. Use for 'latest SCRs/SYCRs' or full-text change-request search. "
        "'project' is the SCR or SYCR project key (e.g. PROJE1SCR, PROJ1SYCR)."
    )
)
def search_change_requests(
    project: str,
    text: str | None = None,
    status: str | None = None,
    created_since: str | None = None,
    updated_since: str | None = None,
    order_by: str = "created DESC",
    max_results: int = 50,
) -> Any:
    """Search/list SCR or SYCR change requests, newest first by default."""
    return dispatch_tool(
        _jira,
        "search_change_requests",
        {
            "project": project,
            "text": text,
            "status": status,
            "created_since": created_since,
            "updated_since": updated_since,
            "order_by": order_by,
            "max_results": max_results,
        },
    )


# ── Worklogs ──────────────────────────────────────────────────────────────────


@mcp.tool(
    description=(
        "Get all worklogs for a single issue including author, time spent, "
        "start time, and comment. Use when you need worklog notes alongside hours."
    )
)
def get_issue_worklogs(issue_key: str) -> Any:
    """Get all worklogs for an issue."""
    return dispatch_tool(_jira, "get_issue_worklogs", {"issue_key": issue_key})


@mcp.tool(
    description=(
        "Bulk-fetch ALL worklogs updated across all projects in the last N days. "
        "Best tool for weekly time reports and per-person hour summaries. "
        "Returns author accountId, timeSpentSeconds, and started date."
    )
)
def get_worklogs_updated_since(days_ago: int) -> Any:
    """Bulk-fetch worklogs from the past N days across all projects."""
    return dispatch_tool(_jira, "get_worklogs_updated_since", {"days_ago": days_ago})


# ── Sprints ───────────────────────────────────────────────────────────────────


@mcp.tool(
    description=(
        "Get the currently active sprint for a board: name, goal, start date, end date. "
        "Call this first for any sprint status or velocity report."
    )
)
def get_active_sprint(board_id: int) -> Any:
    """Get the active sprint for a board."""
    return dispatch_tool(_jira, "get_active_sprint", {"board_id": board_id})


@mcp.tool(
    description=(
        "Get all issues in a specific sprint with status, assignee, and time spent. "
        "Use to calculate done/in-progress/blocked counts and velocity."
    )
)
def get_sprint_issues(board_id: int, sprint_id: int) -> Any:
    """Get all issues in a sprint."""
    return dispatch_tool(
        _jira, "get_sprint_issues", {"board_id": board_id, "sprint_id": sprint_id}
    )


@mcp.tool(
    description=(
        "List all sprints for a board filtered by state. "
        "Use to find sprint IDs for historical reports or to list past sprints."
    )
)
def get_board_sprints(board_id: int, state: str = "active") -> Any:
    """List sprints for a board (state: active | closed | future)."""
    return dispatch_tool(
        _jira, "get_board_sprints", {"board_id": board_id, "state": state}
    )


# ── Users & Groups ────────────────────────────────────────────────────────────


@mcp.tool(
    description=(
        "Get all Jira users in a group (e.g. 'backend-team'). "
        "Returns displayName and accountId. Call this first for any group-level report, "
        "then use the accountIds in search_issues JQL."
    )
)
def get_group_members(group_name: str) -> Any:
    """Get all members of a Jira group."""
    return dispatch_tool(_jira, "get_group_members", {"group_name": group_name})


@mcp.tool(
    description=(
        "Resolve a person's name or email to their Jira accountId. "
        "Always call this before filtering issues by assignee — "
        "JQL requires accountId, not display name."
    )
)
def find_user(query: str) -> Any:
    """Find a Jira user by name or email and return their accountId."""
    return dispatch_tool(_jira, "find_user", {"query": query})


# ── Projects & Metadata ───────────────────────────────────────────────────────


@mcp.tool(
    description=(
        "List all Jira projects the API token has access to. "
        "Use when the user doesn't specify a project key."
    )
)
def list_projects() -> Any:
    """List all accessible Jira projects."""
    return dispatch_tool(_jira, "list_projects", {})


@mcp.tool(
    description=(
        "Get all valid issue status names for a project (e.g. 'In Progress', 'Code Review', 'Done'). "
        "Call this before writing JQL status filters to avoid invalid status errors."
    )
)
def get_project_statuses(project_key: str) -> Any:
    """Get all valid status names for a project."""
    return dispatch_tool(_jira, "get_project_statuses", {"project_key": project_key})


if __name__ == "__main__":
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    app = CORSMiddleware(
        mcp.streamable_http_app(),
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, host="0.0.0.0", port=8002)
