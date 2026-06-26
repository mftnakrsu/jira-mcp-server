import pathlib

import tools

_NEW = {"get_change_request", "search_change_requests"}
_SERVER = pathlib.Path(__file__).resolve().parents[1] / "server.py"


def test_new_tools_registered_in_dispatch():
    assert _NEW <= set(tools._TOOL_REGISTRY)


def test_new_tools_have_schema_entries():
    schema_names = {t["name"] for t in tools.TOOLS}
    assert _NEW <= schema_names


def test_tool_count_is_thirteen():
    # 11 original + 2 new. Guards against accidental drops.
    assert len(tools._TOOL_REGISTRY) == 13
    assert len(tools.TOOLS) == 13


def test_server_exposes_new_tools():
    # server.py calls build_jira_client() at import (live connection), so we scan the
    # source instead of importing it — proves the @mcp.tool wrappers exist.
    src = _SERVER.read_text(encoding="utf-8")
    assert "def get_change_request(" in src
    assert "def search_change_requests(" in src
