import pytest

from app.posting_availability import html_status, http_failure, wanted_status


def test_status_requires_matching_job_and_known_source_state():
    payload = {"data": {"job": {"id": 123, "status": "active"}}}
    assert wanted_status(payload, "123")[0] == "open"
    assert wanted_status(payload, "999")[0] == "unknown"
    payload["data"]["job"]["status"] = "closed"
    assert wanted_status(payload, "123")[0] == "closed"
    payload["data"]["job"]["status"] = "unknown-new-state"
    assert wanted_status(payload, "123")[0] == "unknown"


def test_closed_notice_is_not_inferred_from_generic_words_or_scripts():
    assert html_status("<p>지원 마감일은 추후 안내합니다.</p>")[0] == "unknown"
    assert (
        html_status("<script>채용이 마감되었습니다</script><p>Python developer</p>")[0] == "unknown"
    )
    assert html_status("<h2>채용이 마감되었습니다.</h2>")[0] == "closed"
    assert html_status("<p>Access denied</p><p>채용이 마감되었습니다</p>")[0] == "unknown"


@pytest.mark.parametrize(
    "code,status,pause",
    [
        (404, "unknown", False),
        (410, "closed", False),
        (401, "unknown", True),
        (403, "unknown", True),
        (429, "unknown", True),
        (503, "unknown", True),
    ],
)
def test_access_failure_never_closes_a_posting(code, status, pause):
    assert http_failure(code) == (status, f"http_{code}", pause)


def test_hidden_closed_template_is_not_a_closure_notice():
    assert html_status("<div hidden><p>채용이 마감되었습니다</p></div>")[0] == "unknown"
    assert (
        html_status('<div style="display: none"><span>마감된 공고입니다</span></div>')[0]
        == "unknown"
    )
