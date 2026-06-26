import tools
from tools import dispatch_tool


def test_build_cr_jql_full():
    jql = tools._build_cr_jql(
        "PROJE1SCR", text="engine", status="Open", created_since="-30d"
    )
    assert jql == (
        'project = "PROJE1SCR" AND text ~ "engine" AND status = "Open" '
        "AND created >= -30d ORDER BY created DESC"
    )


def test_build_cr_jql_absolute_date_is_quoted():
    jql = tools._build_cr_jql("PROJE1SCR", created_since="2026-01-01")
    assert jql == 'project = "PROJE1SCR" AND created >= "2026-01-01" ORDER BY created DESC'


def test_build_cr_jql_minimal():
    assert tools._build_cr_jql("PROJ1SYCR") == (
        'project = "PROJ1SYCR" ORDER BY created DESC'
    )


class _FakeSearchClient:
    def __init__(self):
        self.last_jql = None
        self.last_max = None

    def search_issues(self, jql, fields=None, maxResults=None):
        self.last_jql = jql
        self.last_max = maxResults
        fields_obj = type(
            "F",
            (),
            {
                "summary": "Engine SCR",
                "status": type("S", (), {"name": "Open"})(),
                "priority": type("P", (), {"name": "High"})(),
                "created": "2026-06-01T00:00:00.000+0000",
                "updated": "2026-06-02T00:00:00.000+0000",
                "project": type("PR", (), {"key": "PROJE1SCR"})(),
            },
        )()
        return [type("I", (), {"key": "PROJE1SCR-403", "fields": fields_obj})()]


def test_search_change_requests_maps_summaries_and_caps():
    client = _FakeSearchClient()
    rows = dispatch_tool(
        client,
        "search_change_requests",
        {"project": "PROJE1SCR", "text": "engine", "max_results": 500},
    )
    assert client.last_max == 100  # capped
    assert 'project = "PROJE1SCR"' in client.last_jql
    assert rows[0]["key"] == "PROJE1SCR-403"
    assert rows[0]["status"] == "Open"
    assert rows[0]["priority"] == "High"
    assert rows[0]["project"] == "PROJE1SCR"
