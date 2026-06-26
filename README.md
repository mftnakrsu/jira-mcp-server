# JIRA MCP Server

A small, **read-only** [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a JIRA Data Center / Server (or Cloud) instance to MCP clients such as Claude Code, Cursor, and Open WebUI.

It is **stateless** — no database, no volumes. It connects out to your JIRA over the REST API and serves over **Streamable HTTP** at `http://<host>:8002/mcp`. Every tool is read-only; the server never writes to JIRA.

## Tools

13 tools across five areas:

**Issues**
- `search_issues` — search by JQL (weekly summaries, per-person reports, blocked issues, …)
- `get_issue_detail` — full issue: description, comments, subtasks, links, changelog
- `get_change_request` — a full change request: standard fields **plus** the custom "Details" panel and attachment metadata
- `search_change_requests` — list/search change requests in a project, newest first

**Worklogs**
- `get_issue_worklogs` — all worklogs for one issue (with comments)
- `get_worklogs_updated_since` — bulk-fetch worklogs across all projects for the last N days

**Sprints**
- `get_active_sprint` — the active sprint for a board
- `get_sprint_issues` — all issues in a sprint
- `get_board_sprints` — list sprints for a board by state

**Users & Groups**
- `get_group_members` — members of a JIRA group
- `find_user` — resolve a name/email to a JIRA accountId

**Projects & Metadata**
- `list_projects` — projects the token can see
- `get_project_statuses` — valid status names for a project

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
JIRA_URL=https://jira.example.com      # or https://your-domain.atlassian.net for Cloud
JIRA_TOKEN=your-read-only-personal-access-token
JIRA_USERNAME=                          # leave empty for DC PAT; set for Cloud basic_auth
JIRA_VERIFY_SSL=false                   # false for internal self-signed certs
```

- **JIRA Data Center / Server (8.14+):** create a read-only **Personal Access Token**, put it in `JIRA_TOKEN`, and leave `JIRA_USERNAME` empty (Bearer auth).
- **JIRA Cloud:** set `JIRA_USERNAME` to your email and `JIRA_TOKEN` to an API token (basic auth).

The `.env` file is gitignored — never commit real credentials.

## Run

### With Docker (recommended)

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

The server listens on `:8002` (override with `JIRA_MCP_PORT`). MCP endpoint: `http://<host>:8002/mcp`.

### From source

```bash
pip install -r requirements.txt      # or: uv sync
python main.py --check               # verify JIRA connectivity, then exit
python server.py                     # serve MCP on :8002
```

`python main.py --check` runs a connectivity preflight against `/rest/api/2/serverInfo` and prints the real HTTP status / body on failure — handy for distinguishing a bad token from a wrong URL before the server starts.

## Connect an MCP client

Claude Code:

```bash
claude mcp add --transport http jira http://<host>:8002/mcp
```

Point any other Streamable-HTTP MCP client at the same URL.

## CLI

`main.py` doubles as a small CLI for ad-hoc queries:

```bash
python main.py --check                                       # connectivity preflight
python main.py "alice" --field assignee                      # issues assigned to a user
python main.py --worklogs --person you@example.com \
    --from-date 2026-06-01 --to-date 2026-06-10              # worklogs for a person
python main.py --worklogs --group engineering --per-person   # per-person totals
```

## Tests

```bash
pytest -q
```

The suite is fully mock-driven — no live JIRA connection required.

## Notes

- All tools are **read-only**; the server never writes to JIRA.
- `get_change_request` returns attachment **metadata** only (no bytes).
- Behind a corporate firewall, build with an internal PyPI mirror:
  `docker compose build --build-arg PIP_INDEX_URL=https://pypi.example.com/simple`

## License

MIT — see [LICENSE](LICENSE).
