import tools


def test_simplify_field_value_scalars_and_options():
    assert tools._simplify_field_value("x") == "x"
    assert tools._simplify_field_value(7) == 7
    assert tools._simplify_field_value({"value": "Safety", "id": "1"}) == "Safety"
    assert tools._simplify_field_value({"name": "High"}) == "High"
    assert tools._simplify_field_value({"displayName": "Ali"}) == "Ali"
    assert tools._simplify_field_value([{"value": "A"}, {"value": "B"}]) == ["A", "B"]


def test_collect_custom_fields_omits_standard_and_empty():
    fields_map = {
        "customfield_1": {"name": "Classification", "custom": True},
        "customfield_2": {"name": "impacted", "custom": True},
        "customfield_3": {"name": "Empty", "custom": True},
        "summary": {"name": "Summary", "custom": False},
    }
    raw = {
        "customfield_1": {"value": "Safety"},
        "customfield_2": "SUBSYS_A.R100",
        "customfield_3": None,
        "summary": "ignored standard field",
    }
    out = tools._collect_custom_fields(raw, fields_map)
    assert out == {"Classification": "Safety", "impacted": "SUBSYS_A.R100"}


def test_extract_attachments_maps_metadata():
    raw = {
        "attachment": [
            {
                "filename": "d.png",
                "mimeType": "image/png",
                "size": 1234,
                "id": 555,
                "content": "https://jira/secure/attachment/555/d.png",
                "created": "2026-06-01T00:00:00.000+0000",
                "author": {"displayName": "Ali"},
            }
        ]
    }
    atts = tools._extract_attachments(raw)
    assert len(atts) == 1
    assert atts[0].filename == "d.png"
    assert atts[0].attachment_id == "555"
    assert atts[0].content_url.endswith("/d.png")
    assert atts[0].author == "Ali"


def test_extract_attachments_empty_when_absent():
    assert tools._extract_attachments({}) == []


def test_fields_map_caches_per_client():
    calls = {"n": 0}

    class FakeClient:
        def fields(self):
            calls["n"] += 1
            return [
                {"id": "customfield_1", "name": "Classification", "custom": True},
                {"id": "summary", "name": "Summary", "custom": False},
            ]

    c = FakeClient()
    m1 = tools._fields_map(c)
    m2 = tools._fields_map(c)
    assert m1 is m2  # cached object
    assert calls["n"] == 1  # client.fields() called once
    assert m1["customfield_1"] == {"name": "Classification", "custom": True}
