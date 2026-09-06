import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.crawler.approved_api import (
    SARAMIN_API_URL,
    collect_saramin_api,
    parse_saramin_job,
    validate_saramin_job_url,
)


def _payload() -> dict[str, object]:
    return {
        "id": "54812345",
        "url": (
            "http://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54812345"
            "&utm_source=job-search-api"
        ),
        "active": 1,
        "company": {"detail": {"name": "예시테크(주)"}},
        "position": {
            "title": "Python Backend Engineer",
            "location": {"name": "서울 > 강남구"},
            "job-type": {"name": "정규직"},
            "industry": {"name": "소프트웨어"},
            "job-mid-code": {"name": "IT개발·데이터"},
            "job-code": {"name": "백엔드/서버개발"},
            "experience-level": {"name": "경력 3~8년", "min": 3, "max": 8},
        },
        "keyword": "Python,FastAPI,PostgreSQL,AWS",
        "salary": {"name": "면접 후 결정"},
        "posting-timestamp": "1788044400",
        "expiration-timestamp": "1790780399",
        "close-type": {"code": "1", "name": "접수마감일"},
    }


def test_saramin_official_api_payload_is_normalized_without_detail_scraping() -> None:
    job = parse_saramin_job(_payload())

    assert job.source_name == "saramin"
    assert job.external_job_id == "54812345"
    assert job.company_name == "예시테크(주)"
    assert job.url.startswith("https://www.saramin.co.kr/zf_user/jobs/relay/view?")
    assert job.tech_stack == ["Python", "FastAPI", "PostgreSQL", "AWS"]
    assert job.experience_text == "경력 3~8년"
    assert job.posted_at == datetime.fromtimestamp(1788044400, tz=UTC)
    assert job.deadline_at == datetime.fromtimestamp(1790780399, tz=UTC)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/zf_user/jobs/relay/view?rec_idx=1",
        "https://www.saramin.co.kr/zf_user/jobs/relay/view",
        "https://www.saramin.co.kr/zf_user/help?rec_idx=1",
        "https://evil.example/zf_user/jobs/relay/view?rec_idx=1",
    ],
)
def test_saramin_api_job_url_rejects_non_official_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_saramin_job_url(url)


def test_saramin_collection_uses_the_official_api_and_filters_target_roles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(SARAMIN_API_URL)
        assert request.url.params["access-key"] == "approved-secret"
        return httpx.Response(
            200,
            json={"jobs": {"count": 1, "start": 0, "total": "1", "job": [_payload()]}},
        )

    jobs = asyncio.run(
        collect_saramin_api(
            "approved-secret",
            max_jobs=1,
            delay_min_seconds=0,
            user_agent="get-job-test",
            transport=httpx.MockTransport(handler),
        )
    )

    assert [job.external_job_id for job in jobs] == ["54812345"]


def test_saramin_collection_errors_never_expose_the_access_key() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, text="denied"))

    with pytest.raises(RuntimeError) as error:
        asyncio.run(
            collect_saramin_api(
                "do-not-log-this-key",
                max_jobs=1,
                delay_min_seconds=0,
                user_agent="get-job-test",
                transport=transport,
            )
        )

    assert "do-not-log-this-key" not in str(error.value)
