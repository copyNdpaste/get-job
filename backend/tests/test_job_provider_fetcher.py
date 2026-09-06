import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import crawl
from app.config import Settings
from app.crawler.job_provider_fetcher import (
    MAX_QUERY_PARAMS,
    ExternalJobFetcher,
    collect_jobplanet_jobs,
    collect_jobplanet_pages,
    normalize_jobplanet_rows,
)
from app.crawler.persistence import persist_collected_jobs
from app.db.base import Base
from app.models import CrawlRun, JobPosting, JobSource

ENDPOINT_URL = "https://jobs.provider.example/api/postings"


def _standard_job_row(job_id: str, title: str = "Python Backend Engineer") -> dict:
    return {
        "job_id": job_id,
        "company_name": "Synthetic Pagination Labs",
        "company_rating": 4.0,
        "title": title,
        "job_url": (
            f"https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D={job_id}"
        ),
        "location": "서울",
    }


def test_fetch_raw_data_sends_params_with_mock_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"postings": []}})

    fetcher = ExternalJobFetcher(transport=httpx.MockTransport(handler))

    payload = asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, {"page": 2, "size": 20}))

    assert payload == {"data": {"postings": []}}
    assert requests[0].url.params["page"] == "2"
    assert requests[0].url.params["size"] == "20"
    assert requests[0].headers["accept"] == "application/json"


def test_get_processed_jobs_connects_to_jobplanet_processor() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "postings": [
                        {
                            "id": 123,
                            "title": "  Backend   Engineer ",
                            "company": {"name": " Example  Corp ", "rate": "4.5"},
                            "location": " Seoul ",
                        }
                    ]
                }
            },
        )

    fetcher = ExternalJobFetcher(transport=httpx.MockTransport(handler))

    jobs = asyncio.run(fetcher.get_processed_jobs(ENDPOINT_URL, {"query": "backend"}))

    assert jobs == [
        {
            "job_id": 123,
            "title": "Backend Engineer",
            "company_name": "Example Corp",
            "company_rating": 4.5,
            "location": "Seoul",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=123",
        }
    ]


def test_jobplanet_collection_follows_infinite_scroll_pages_until_the_end() -> None:
    requested_pages: list[int] = []
    delays: list[float] = []
    progress: list[tuple[int, int, int]] = []

    class FakeJobPlanetApiClient:
        async def get_jobs(self, page=1, per=20):
            assert per == 2
            requested_pages.append(page)
            return {
                1: [_standard_job_row("page-1-a"), _standard_job_row("page-1-b")],
                2: [_standard_job_row("page-2-a", "Infra/DevOps/SRE 개발자 모집")],
            }.get(page, [])

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    jobs = asyncio.run(
        collect_jobplanet_pages(
            FakeJobPlanetApiClient(),
            max_jobs=10,
            delay_min_seconds=0.25,
            page_size=2,
            on_progress=lambda pages, found, failed: progress.append(
                (pages, found, failed)
            ),
            sleep=fake_sleep,
        )
    )

    assert requested_pages == [1, 2]
    assert [job.external_job_id for job in jobs] == ["page-1-a", "page-1-b", "page-2-a"]
    assert delays == [0.25]
    assert progress == [(1, 2, 0), (2, 3, 0)]


def test_jobplanet_collection_stops_as_soon_as_the_relevant_limit_is_reached() -> None:
    requested_pages: list[int] = []

    class FakeJobPlanetApiClient:
        async def get_jobs(self, page=1, per=20):
            assert per == 2
            requested_pages.append(page)
            return [_standard_job_row("limit-a"), _standard_job_row("limit-b")]

    jobs = asyncio.run(
        collect_jobplanet_pages(
            FakeJobPlanetApiClient(),
            max_jobs=1,
            delay_min_seconds=2,
            page_size=2,
        )
    )

    assert requested_pages == [1]
    assert [job.external_job_id for job in jobs] == ["limit-a"]


@pytest.mark.parametrize(
    "job_url",
    [
        "https://www.jobplanet.co.kr/job/search/safe-id",
        "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=other-id",
        (
            "https://www.jobplanet.co.kr/job/search?"
            "posting_ids%5B%5D=safe-id&redirect=https://example.test"
        ),
    ],
)
def test_jobplanet_rows_reject_noncanonical_detail_links(job_url: str) -> None:
    row = _standard_job_row("safe-id")
    row["job_url"] = job_url

    assert normalize_jobplanet_rows([row], max_jobs=1) == []


@pytest.mark.parametrize(
    ("max_jobs", "delay_min_seconds", "page_size", "message"),
    [
        (0, 0.0, 20, "max_jobs"),
        (True, 0.0, 20, "max_jobs"),
        (1, -0.1, 20, "delay_min_seconds"),
        (1, float("nan"), 20, "delay_min_seconds"),
        (1, 0.0, 0, "page_size"),
    ],
)
def test_jobplanet_paginated_collection_rejects_unsafe_limits(
    max_jobs: int,
    delay_min_seconds: float,
    page_size: int,
    message: str,
) -> None:
    class FakeJobPlanetApiClient:
        async def get_jobs(self, page=1, per=20):
            pytest.fail(f"invalid pagination must not request page {page}")

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            collect_jobplanet_pages(
                FakeJobPlanetApiClient(),
                max_jobs=max_jobs,
                delay_min_seconds=delay_min_seconds,
                page_size=page_size,
            )
        )


def test_fetch_raw_data_raises_for_unsuccessful_status() -> None:
    fetcher = ExternalJobFetcher(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503))
    )

    with pytest.raises(httpx.HTTPStatusError) as error:
        asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, {}))

    assert error.value.response.status_code == 503


def test_fetch_errors_do_not_expose_request_parameters() -> None:
    fetcher = ExternalJobFetcher(
        transport=httpx.MockTransport(lambda _request: httpx.Response(401))
    )

    with pytest.raises(httpx.HTTPStatusError) as error:
        asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, {"access_key": "do-not-log"}))

    assert "do-not-log" not in str(error.value)


def test_fetch_raw_data_propagates_http_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    fetcher = ExternalJobFetcher(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPError):
        asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, {}))


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://jobs.provider.example/api/postings",
        "https://localhost/api/postings",
        "https://127.0.0.1/api/postings",
        "https://user:secret@jobs.provider.example/api/postings",
        "https://jobs.provider.example/api/postings?token=secret",
    ],
)
def test_fetch_raw_data_rejects_unsafe_provider_urls(endpoint_url: str) -> None:
    fetcher = ExternalJobFetcher(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    )

    with pytest.raises(ValueError):
        asyncio.run(fetcher.fetch_raw_data(endpoint_url, {}))


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="not-json"), "invalid JSON"),
        (httpx.Response(200, json=[]), "must be a JSON object"),
    ],
)
def test_fetch_raw_data_rejects_invalid_payloads(response: httpx.Response, message: str) -> None:
    fetcher = ExternalJobFetcher(transport=httpx.MockTransport(lambda _request: response))

    with pytest.raises(ValueError, match=message):
        asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, {}))


def test_collection_rejects_an_invalid_jobplanet_envelope() -> None:
    fetcher_transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"data": {"items": []}})
    )

    with pytest.raises(ValueError, match="invalid JobPlanet envelope"):
        asyncio.run(
            collect_jobplanet_jobs(
                ENDPOINT_URL,
                {},
                max_jobs=10,
                transport=fetcher_transport,
            )
        )


def test_fetch_raw_data_rejects_oversized_parameter_sets() -> None:
    fetcher = ExternalJobFetcher(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    )
    params = {f"key-{index}": index for index in range(MAX_QUERY_PARAMS + 1)}

    with pytest.raises(ValueError, match="too many parameters"):
        asyncio.run(fetcher.fetch_raw_data(ENDPOINT_URL, params))


def test_jobplanet_collection_is_normalized_filtered_and_persistable() -> None:
    progress: list[tuple[int, int, int]] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "postings": [
                        {
                            "id": 100,
                            "title": "Python FastAPI Backend Engineer",
                            "company": {"name": "Synthetic Labs", "rate": 4.4},
                            "location": "서울",
                        },
                        {
                            "id": 101,
                            "title": "Product Designer",
                            "company": {"name": "Synthetic Design", "rate": 4.0},
                            "location": "서울",
                        },
                        {
                            "id": None,
                            "title": "Backend Engineer",
                            "company": {"name": "Invalid Row"},
                        },
                    ]
                }
            },
        )

    jobs = asyncio.run(
        collect_jobplanet_jobs(
            ENDPOINT_URL,
            {"page": 1},
            max_jobs=10,
            on_progress=lambda visited, found, failed: progress.append((visited, found, failed)),
            transport=httpx.MockTransport(handler),
        )
    )

    assert len(jobs) == 1
    assert jobs[0].source_name == "jobplanet"
    assert jobs[0].external_job_id == "100"
    assert jobs[0].company_name == "Synthetic Labs"
    assert {"Python", "FastAPI"}.issubset(jobs[0].tech_stack)
    assert progress == [(3, 3, 1)]

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            JobSource(
                name="jobplanet",
                base_url="https://www.jobplanet.co.kr",
                crawler_type="configured_api",
            )
        )
        session.commit()

        counts = persist_collected_jobs(session, "jobplanet", jobs)
        session.commit()

        assert counts == {"created": 1, "updated": 0, "unchanged": 0}
        assert session.scalar(select(func.count(JobPosting.id))) == 1


def test_jobplanet_background_collection_persists_and_completes_run(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        source = JobSource(
            name="jobplanet",
            base_url="https://www.jobplanet.co.kr",
            crawler_type="public_json",
        )
        session.add(source)
        session.flush()
        run = CrawlRun(source_id=source.id, started_at=datetime.now(UTC), status="running")
        session.add(run)
        session.commit()
        run_id = run.id

    class FakeJobPlanetApiClient:
        async def get_jobs(self, page=1, per=20):
            assert page == 1
            assert per == 100
            return [
                {
                    "job_id": "501",
                    "company_name": "Synthetic Pipeline",
                    "company_rating": 0.0,
                    "title": "Python Backend Engineer",
                    "job_url": (
                        "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=501"
                    ),
                    "location": "서울",
                }
            ]

    monkeypatch.setattr(crawl, "SessionLocal", sessions)
    monkeypatch.setattr(crawl, "JobPlanetApiClient", FakeJobPlanetApiClient)
    monkeypatch.setattr(crawl, "score_jobs", lambda *_args, **_kwargs: 1)
    deduplication_calls: list[bool] = []
    monkeypatch.setattr(
        crawl,
        "refresh_duplicate_groups",
        lambda _session: deduplication_calls.append(True),
    )

    asyncio.run(
        crawl._run_collection(
            run_id,
            "jobplanet",
            crawl.CrawlRequest(max_jobs=10),
            Settings(ai_enabled=False),
        )
    )

    with sessions() as session:
        completed = session.get(CrawlRun, run_id)
        posting = session.scalar(select(JobPosting))
        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.pages_visited == 1
        assert completed.jobs_found == 1
        assert completed.jobs_created == 1
        assert posting is not None
        assert posting.external_job_id == "501"
        assert deduplication_calls == [True]
