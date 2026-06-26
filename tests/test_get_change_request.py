import tools
from tools import dispatch_tool


class _FakeFields:
    def __init__(self):
        self.summary = "Engine SCR"
        self.status = type("S", (), {"name": "Open"})()
        self.assignee = None
        self.reporter = None
        self.priority = type("P", (), {"name": "High"})()
        self.description = "the description body"
        self.created = "2026-06-01T00:00:00.000+0000"
        self.updated = "2026-06-02T00:00:00.000+0000"
        self.comment = type("C", (), {"comments": []})()
        self.subtasks = []
        self.issuelinks = []


class _FakeIssue:
    def __init__(self):
        self.key = "PROJE1SCR-403"
        self.fields = _FakeFields()
        self.changelog = type("CL", (), {"histories": []})()
        self.raw = {
            "fields": {
                "customfield_10001": {"value": "Safety"},
                "customfield_10002": "SUBSYS_A.R100",
                "customfield_10003": None,
                "summary": "Engine SCR",
                "attachment": [
                    {
                        "filename": "diagram.png",
                        "mimeType": "image/png",
                        "size": 1234,
                        "id": 555,
                        "content": "https://jira/secure/attachment/555/diagram.png",
                        "created": "2026-06-01T00:00:00.000+0000",
                        "author": {"displayName": "Ali"},
                    }
                ],
            }
        }


class _FakeClient:
    def __init__(self, issue):
        self._issue = issue
        self.last_call = None

    def issue(self, key, fields=None, expand=None):
        self.last_call = {"key": key, "fields": fields, "expand": expand}
        return self._issue

    def fields(self):
        return [
            {"id": "customfield_10001", "name": "Classification", "custom": True},
            {"id": "customfield_10002", "name": "impacted", "custom": True},
            {"id": "customfield_10003", "name": "Analysis", "custom": True},
            {"id": "summary", "name": "Summary", "custom": False},
        ]


def test_get_change_request_returns_full_detail():
    client = _FakeClient(_FakeIssue())
    result = dispatch_tool(client, "get_change_request", {"issue_key": "PROJE1SCR-403"})

    assert result["key"] == "PROJE1SCR-403"
    assert result["description"] == "the description body"
    # Details panel — custom fields by human name, empty Analysis omitted
    assert result["custom_fields"] == {
        "Classification": "Safety",
        "impacted": "SUBSYS_A.R100",
    }
    # Attachment metadata, no bytes
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["filename"] == "diagram.png"
    assert result["attachments"][0]["attachment_id"] == "555"
    # fetched with all fields
    assert client.last_call["fields"] == "*all"


def test_issue_detail_refactor_still_works():
    client = _FakeClient(_FakeIssue())
    detail = dispatch_tool(client, "get_issue_detail", {"issue_key": "PROJE1SCR-403"})
    assert detail["key"] == "PROJE1SCR-403"
    assert detail["priority"] == "High"
    assert "custom_fields" not in detail  # plain IssueDetail, unchanged shape
