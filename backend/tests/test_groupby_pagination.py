import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api import crawl
from app.config import Settings
from app.crawler import browser_groupby as groupby
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.models import CrawlRun, JobPosting, JobSource


def listing(ids, total=None):
    result = {"items": [{"id": value, "name": "Backend Engineer"} for value in ids]}
    if total is not None:
        result["total"] = total
    return result


@pytest.mark.parametrize(
    ("pages", "limit", "expected_ids", "offsets", "complete"),
    [
        ([listing([1, 2], 3), listing([3], 3)], 2, [1, 2, 3], [0, 2], True),
        ([listing([1, 2]), listing([3])], 3, [1, 2, 3], [0, 2], True),
        ([listing([1, 2]), listing([])], 3, [1, 2], [0, 2], True),
        ([listing([1], 2), listing([2], 2)], 2, [1, 2], [0, 1], True),
        ([listing([1, 2], 9), listing([3, 4], 9)], 2, [1, 2, 3, 4], [0, 2], False),
        ([listing([1, 2], 4), listing([1, 2], 4)], 5, [1, 2], [0, 2], False),
        ([listing([1, 2]), listing([1, 2])], 5, [1, 2], [0, 2], False),
        ([listing([1, 2], 3), listing([2, 3], 3)], 3, [1, 2, 3], [0, 2], True),
        ([listing([1, 2], 4), listing([])], 3, [1, 2], [0, 2], False),
        ([{"items": [None, {"id": 1}], "total": 3}, listing([2], 3)], 3, [1, 2], [0, 2], False),
        ([listing([True, 0, "1"], 3)], 3, [], [0], False),
        ([listing([], 0)], 3, [], [0], True),
    ],
)
def test_discovery_stops_with_explicit_coverage(
    monkeypatch, pages, limit, expected_ids, offsets, complete
) -> None:
    monkeypatch.setattr(groupby, "LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(groupby, "MAX_LIST_PAGES", limit)
    requested_offsets = []

    def respond(request):
        assert request.url.params["limit"] == "2"
        assert request.url.params["parentPositionTypes"] == "17"
        requested_offsets.append(int(request.url.params["offset"]))
        return httpx.Response(200, json={"status": 200, "data": pages[len(requested_offsets) - 1]})

    async def discover():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await groupby._discover_groupby_candidates(client, delay_min_seconds=0)

    result = asyncio.run(discover())
    assert [item["id"] for item in result.candidates] == expected_ids
    assert requested_offsets == offsets
    assert result.complete is complete
    assert bool(result.warning) is not complete


def test_missing_list_is_still_a_protocol_error() -> None:
    async def discover():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": 200, "data": {}})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await groupby._discover_groupby_candidates(client, delay_min_seconds=0)

    with pytest.raises(RuntimeError, match="returned no position list"):
        asyncio.run(discover())


def detail(position_id):
    return {
        "id": position_id,
        "name": f"Backend Engineer {position_id}",
        "task": "Python FastAPI 서버 개발",
        "startup": {"id": 1, "name": "테스트 회사"},
    }


@pytest.mark.parametrize("mode", ["cap", "repeat", "complete", "job_limit"])
def test_collection_persists_partial_results_without_closing_unseen_jobs(monkeypatch, mode):
    monkeypatch.setattr(groupby, "LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(groupby, "MAX_LIST_PAGES", 1 if mode == "cap" else 3)
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.path == "/startup-positions":
            data = listing([1, 2], 10 if mode in {"cap", "repeat"} else 2)
        else:
            data = detail(int(request.url.path.rsplit("/", 1)[-1]))
        return httpx.Response(200, json={"status": 200, "data": data})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        groupby.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(crawl, "SessionLocal", sessions)
    monkeypatch.setattr(crawl, "score_jobs", lambda *_args, **_kwargs: None)
    with sessions.begin() as session:
        source = JobSource(
            name="groupby", base_url="https://groupby.kr", crawler_type="browser_assisted"
        )
        session.add(source)
        session.flush()
        old = upsert_collected_job(session, source, groupby.parse_groupby_api_detail(detail(99)))
        old_job = session.get(JobPosting, old.job_posting_id)
        old_job.last_seen_at = datetime.now(UTC) - timedelta(days=1)
        run = CrawlRun(source_id=source.id, status="running", started_at=datetime.now(UTC))
        session.add(run)
        session.flush()
        run_id, old_job_id = run.id, old_job.id

    asyncio.run(
        crawl._run_collection(
            run_id,
            "groupby",
            crawl.CrawlRequest(max_jobs=1 if mode == "job_limit" else 50),
            Settings(_env_file=None, ai_analysis_after_crawl=False, crawler_delay_min_seconds=0),
        )
    )

    with sessions() as session:
        run = session.get(CrawlRun, run_id)
        assert run.status == ("partial" if mode in {"cap", "repeat"} else "succeeded")
        assert bool(run.error_log) is (mode in {"cap", "repeat"})
        assert run.jobs_created == (1 if mode == "job_limit" else 2)
        assert session.get(JobPosting, old_job_id).is_active is (mode != "complete")
        new_job = session.scalar(select(JobPosting).where(JobPosting.external_job_id == "1"))
        assert new_job is not None and new_job.is_active
        assert run.finished_at is not None
    assert requested.count("/startup-positions") == (2 if mode == "repeat" else 1)
