from models import Attachment, ChangeRequestDetail, ChangeRequestSummary


def test_attachment_defaults_are_none():
    a = Attachment(filename="d.png", mime_type="image/png", size=10, attachment_id="5")
    assert a.filename == "d.png"
    assert a.content_url is None  # not provided -> default None


def test_change_request_detail_extends_issue_detail():
    crd = ChangeRequestDetail(
        key="PROJE1SCR-403",
        custom_fields={"Classification": "Safety"},
        attachments=[Attachment(filename="d.png")],
    )
    assert crd.key == "PROJE1SCR-403"
    assert crd.custom_fields == {"Classification": "Safety"}
    assert crd.attachments[0].filename == "d.png"
    # inherited IssueDetail fields default cleanly
    assert crd.comments == [] and crd.links == []


def test_change_request_summary_minimal():
    s = ChangeRequestSummary(key="PROJ1SYCR-425", project="PROJ1SYCR")
    assert s.key == "PROJ1SYCR-425"
    assert s.project == "PROJ1SYCR"
    assert s.priority is None
