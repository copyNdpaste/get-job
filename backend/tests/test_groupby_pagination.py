import asyncio
import json
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


def public_html(props):
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": props}})
        + "</script>"
    )


@pytest.mark.parametrize(
    "mode", ["cap", "repeat", "complete", "job_limit", "restricted_list", "restricted_detail"]
)
def test_collection_persists_partial_results_without_closing_unseen_jobs(
    monkeypatch, tmp_path, mode
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(groupby, "LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(groupby, "MAX_LIST_PAGES", 1 if mode == "cap" else 3)
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.host == "groupby.kr":
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            if request.url.path == "/jobs/engineering":
                return httpx.Response(
                    200, text=public_html({"positions": listing([3, 4])["items"]})
                )
            return httpx.Response(
                200,
                text=public_html(
                    {
                        "fallbackDataRaw": json.dumps(
                            detail(int(request.url.path.rsplit("/", 1)[-1]))
                        )
                    }
                ),
            )
        if request.url.path == "/startup-positions":
            data = listing([1, 2], 10 if mode in {"cap", "repeat"} else 2)
            if mode == "restricted_list":
                data["total"] = 180000
                data["items"][0]["name"] = "[표시 제한] Backend Engineer"
        else:
            data = detail(int(request.url.path.rsplit("/", 1)[-1]))
            if mode == "restricted_detail" and data["id"] == 2:
                data["startup"]["name"] = "[표시 제한] 테스트 회사"
        return httpx.Response(200, json={"status": 200, "data": data})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        groupby.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(**{**kwargs, "transport": httpx.MockTransport(respond)}),
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
        partial = mode in {"cap", "repeat", "restricted_list", "restricted_detail"}
        assert run.status == ("partial" if partial else "succeeded")
        assert bool(run.error_log) is partial
        assert run.jobs_created == (1 if mode == "job_limit" else 2)
        assert session.get(JobPosting, old_job_id).is_active is (mode != "complete")
        expected_id = "3" if mode.startswith("restricted") else "1"
        new_job = session.scalar(
            select(JobPosting).where(JobPosting.external_job_id == expected_id)
        )
        assert new_job is not None and new_job.is_active
        assert run.finished_at is not None
        if mode.startswith("restricted"):
            assert (
                session.scalar(select(JobPosting).where(JobPosting.external_job_id == "1")) is None
            )
            assert "표시 제한" in run.error_log
    assert requested.count("/startup-positions") == (2 if mode == "repeat" else 1)
    if mode == "restricted_list":
        assert "/startup-positions/1" not in requested
    if mode.startswith("restricted"):
        assert requested.count("/robots.txt") == 1
        assert "/jobs/engineering" in requested


@pytest.mark.parametrize("blocked", [True, False])
def test_public_fallback_checks_robots_and_rejects_cross_host_redirects(
    monkeypatch, tmp_path, blocked
):
    monkeypatch.chdir(tmp_path)
    requested = []

    def respond(request):
        requested.append(str(request.url))
        if request.url.path == "/startup-positions":
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": {
                        "items": [{"id": 1, "name": "[표시 제한] Backend Engineer"}],
                        "total": 180000,
                    },
                },
            )
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\n" + ("Disallow: /\n" if blocked else "Allow: /\n")
            )
        return httpx.Response(302, headers={"location": "https://untrusted.example/positions/1"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        groupby.httpx,
        "AsyncClient",
        lambda **kw: original(**{**kw, "transport": httpx.MockTransport(respond)}),
    )
    with pytest.raises((ValueError, groupby.RobotsDeniedError)):
        asyncio.run(groupby.collect_groupby_browser(delay_min_seconds=0))
    assert not any("untrusted.example" in url for url in requested)
    assert len(requested) == (2 if blocked else 3)


def test_public_detail_rejects_mismatched_and_restricted_postings():
    with pytest.raises(ValueError, match="ID"):
        groupby.parse_groupby_public_detail(public_html({"fallbackDataRaw": detail(2)}), 1)
    restricted = detail(1)
    restricted["name"] = "[표시 제한] Backend Engineer"
    with pytest.raises(groupby.GroupbyRestrictedResponseError):
        groupby.parse_groupby_public_detail(public_html({"fallbackDataRaw": restricted}), 1)


@pytest.mark.parametrize("max_jobs", [1, 10])
def test_public_fallback_bounds_candidate_and_detail_requests(monkeypatch, tmp_path, max_jobs):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(groupby, "MAX_PUBLIC_POSITIONS", 2)
    requested = []
    coverage = []

    def respond(request):
        assert request.url.host == "groupby.kr"
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/jobs/engineering":
            return httpx.Response(200, text=public_html({"positions": listing([1, 2, 3])["items"]}))
        return httpx.Response(
            200,
            text=public_html({"fallbackDataRaw": detail(int(request.url.path.rsplit("/", 1)[-1]))}),
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        groupby.httpx,
        "AsyncClient",
        lambda **kw: original(**{**kw, "transport": httpx.MockTransport(respond)}),
    )
    jobs = asyncio.run(
        groupby.collect_groupby_public_pages(
            max_jobs=max_jobs,
            delay_min_seconds=0,
            user_agent="test-collector",
            on_discovery=lambda complete, warning: coverage.append(complete),
        )
    )
    assert len(jobs) == min(max_jobs, 2)
    assert len(requested) == 2 + min(max_jobs, 2)
    assert "/positions/3" not in requested
    assert coverage == [False]
