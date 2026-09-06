import asyncio

import httpx
import pytest

from app.crawler.job_provider_fetcher import ExternalJobFetchError, ExternalJobStatusError
from app.crawler.jobplanet_fetcher import (
    JOBPLANET_BACKEND_OCCUPATION_ID,
    JOBPLANET_POSTINGS_ENDPOINT,
    JOBPLANET_PUBLIC_SSR_HEADER,
    JOBPLANET_SOFTWARE_OCCUPATION_ID,
    JobPlanetApiClient,
)


def test_fetch_raw_postings_uses_expected_endpoint_params_and_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"recruits": []}})

    client = JobPlanetApiClient(transport=httpx.MockTransport(handler))

    payload = asyncio.run(client.fetch_raw_postings(page=2, per=50))

    assert payload == {"data": {"recruits": []}}
    assert str(requests[0].url.copy_with(query=None)) == JOBPLANET_POSTINGS_ENDPOINT
    assert dict(requests[0].url.params) == {
        "occupation_level1": "",
        "occupation_level2": (
            f"{JOBPLANET_BACKEND_OCCUPATION_ID},{JOBPLANET_SOFTWARE_OCCUPATION_ID}"
        ),
        "years_of_experience": "",
        "review_score": "",
        "job_type": "",
        "city": "",
        "education_level_id": "",
        "order_by": "recent",
        "page": "2",
        "page_size": "50",
    }
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].headers["content-type"] == "application/json"
    assert requests[0].headers["jp-os-type"] == "desktop_web"
    assert requests[0].headers["jp-ssr-auth"] == JOBPLANET_PUBLIC_SSR_HEADER
    assert requests[0].headers["referer"] == "https://www.jobplanet.co.kr/job"


def test_parse_postings_returns_exact_null_safe_standard_schema() -> None:
    client = JobPlanetApiClient()

    jobs = client.parse_postings(
        {
            "data": {
                "recruits": [
                    {
                        "id": 101,
                        "title": "  Backend   Engineer ",
                        "company": {"name": " Synthetic  Labs ", "grade": "4.3"},
                        "cities": [" 서울 ", " 경기 "],
                    },
                    {
                        "id": "job-102",
                        "title": None,
                        "company": {"city_name": " 부산 "},
                        "location": None,
                    },
                    {"id": None, "title": "invalid"},
                    "invalid-row",
                ]
            }
        }
    )

    assert jobs == [
        {
            "job_id": "101",
            "title": "Backend Engineer",
            "company_name": "Synthetic Labs",
            "company_rating": 4.3,
            "location": "서울, 경기",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=101",
        },
        {
            "job_id": "job-102",
            "title": "",
            "company_name": "",
            "company_rating": 0.0,
            "location": "부산",
            "job_url": (
                "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=job-102"
            ),
        },
    ]
    assert set(jobs[0]) == {
        "job_id",
        "title",
        "company_name",
        "company_rating",
        "location",
        "job_url",
    }


def test_parse_postings_preserves_jobplanet_analysis_metadata() -> None:
    jobs = JobPlanetApiClient().parse_postings(
        {
            "data": {
                "recruits": [
                    {
                        "id": 700,
                        "title": "Node/Nest 백엔드 개발자",
                        "company": {"name": "Synthetic Backend Labs"},
                        "cities": ["서울"],
                        "skills": ["Python", "Node.js", "NestJS", "Go"],
                        "occupation_names": {
                            "level1": ["개발"],
                            "level2": ["백엔드 개발", "소프트웨어 개발"],
                        },
                        "career_text": "경력 3년 이상",
                        "recruitment_text": ["Node.js 또는 Go 기반 서버 개발 경험"],
                        "job_type": "정규직",
                    }
                ]
            }
        }
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert {"Python", "Node.js", "NestJS", "Go"}.issubset(set(job["tech_stack"]))
    assert "백엔드 개발" in job["description_text"]
    assert "소프트웨어 개발" in job["description_text"]
    assert job["requirements"] == ["Node.js 또는 Go 기반 서버 개발 경험"]
    assert job["experience_text"] == "경력 3년 이상"
    assert job["employment_type"] == "정규직"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {}},
        {"data": {"recruits": None}},
        {"data": {"recruits": "invalid"}},
        {"data": {"postings": None}},
        {"data": {"postings": "invalid"}},
    ],
)
def test_parse_postings_returns_empty_list_for_missing_container(payload: dict) -> None:
    assert JobPlanetApiClient().parse_postings(payload) == []


def test_get_jobs_fetches_then_parses() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "recruits": [
                        {
                            "id": 501,
                            "title": "Python Backend Engineer",
                            "company": {
                                "name": "Synthetic Pipeline",
                                "grade": None,
                            },
                            "cities": ["부산"],
                        }
                    ]
                }
            },
        )

    client = JobPlanetApiClient(transport=httpx.MockTransport(handler))

    jobs = asyncio.run(client.get_jobs(page=1))

    assert jobs[0]["job_id"] == "501"
    assert jobs[0]["company_rating"] == 0.0


@pytest.mark.parametrize(
    ("page", "per", "message"),
    [
        (0, 20, "page must be a positive integer"),
        (True, 20, "page must be a positive integer"),
        (1, 0, "per must be an integer"),
        (1, 101, "per must be an integer"),
    ],
)
def test_fetch_rejects_invalid_pagination(page: int, per: int, message: str) -> None:
    client = JobPlanetApiClient(
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("invalid pagination must not make a request")
        )
    )

    with pytest.raises(ValueError, match=message):
        asyncio.run(client.fetch_raw_postings(page=page, per=per))


def test_fetch_propagates_sanitized_status_error() -> None:
    client = JobPlanetApiClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(429))
    )

    with pytest.raises(ExternalJobStatusError) as error:
        asyncio.run(client.fetch_raw_postings())

    assert error.value.response.status_code == 429


def test_fetch_propagates_sanitized_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = JobPlanetApiClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ExternalJobFetchError):
        asyncio.run(client.fetch_raw_postings())
