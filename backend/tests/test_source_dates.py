import json
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from app.crawler.adapters import get_adapter
from app.crawler.job_provider_fetcher import normalize_jobplanet_rows
from app.crawler.jobplanet_fetcher import JobPlanetApiClient
from app.crawler.source_dates import jobposting_dates, jumpit_position, korean_source_datetime


def flight_html(position):
    ld = {
        "@type": "JobPosting",
        "title": "Python Engineer",
        "hiringOrganization": {"name": "Synthetic"},
    }
    state = {"queries": [{"state": {"data": position}}]}
    packet = [1, "9:" + json.dumps(["$", "$L1", None, {"state": state}]) + "\n"]
    return (
        f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        f"<script>self.__next_f.push({json.dumps(packet)})</script>"
    )


def test_jumpit_extracts_publication_and_closure_for_exact_position():
    html = flight_html(
        {"id": 17, "publishedAt": "2026-10-01 00:00:00", "closedAt": "2026-10-31 23:59:59"}
    )
    job = get_adapter("jumpit").parse_detail(html, "https://jumpit.saramin.co.kr/position/17")
    assert job.posted_at == datetime(2026, 9, 30, 15, tzinfo=UTC)
    assert job.deadline_at == datetime(2026, 10, 31, 14, 59, 59, tzinfo=UTC)
    assert not jumpit_position(
        BeautifulSoup(html, "html.parser"), "https://jumpit.saramin.co.kr/position/18"
    )


def test_jumpit_legacy_next_data_and_invalid_packets():
    data = {"props": {"pageProps": {"position": {"id": 17, "publishedAt": "2026-10-01"}}}}
    html = '<script id="__NEXT_DATA__">' + json.dumps(data) + "</script>"
    assert (
        jumpit_position(
            BeautifulSoup(html, "html.parser"), "https://jumpit.saramin.co.kr/position/17"
        )["id"]
        == 17
    )
    malformed = "<script>self.__next_f.push(not_json)</script>"
    assert (
        jumpit_position(
            BeautifulSoup(malformed, "html.parser"), "https://jumpit.saramin.co.kr/position/17"
        )
        == {}
    )


def test_jobplanet_dates_survive_every_conversion_and_ignore_updates():
    payload = {
        "data": {
            "postings": [
                {
                    "id": 17,
                    "title": "Python Engineer",
                    "company": {"name": "Synthetic"},
                    "created_at": "2026-10-02T08:10:00+09:00",
                    "updated_at": "2026-10-12T10:00:00+09:00",
                    "start_at": "2026-10-01",
                    "end_at": "2026-10-31",
                }
            ]
        }
    }
    rows = JobPlanetApiClient().parse_postings(payload)
    job = normalize_jobplanet_rows(rows, max_jobs=10)[0]
    assert job.posted_at == datetime(2026, 10, 1, 23, 10, tzinfo=UTC)
    assert job.deadline_at == datetime(2026, 10, 31, 14, 59, 59, 999999, tzinfo=UTC)


def test_invalid_dates_remain_unknown_and_date_only_deadline_is_inclusive():
    for value in [None, "", "not-a-date", 1790000000, True]:
        assert korean_source_datetime(value) is None
    assert korean_source_datetime("2026-10-31", end_of_day=True) == datetime(
        2026, 10, 31, 14, 59, 59, 999999, tzinfo=UTC
    )


def test_wanted_reads_source_json_ld_and_rejects_another_job_url():
    url = "https://www.wanted.co.kr/wd/17"
    data = [
        {
            "@type": "JobPosting",
            "url": "https://www.wanted.co.kr/wd/18",
            "datePosted": "2026-10-12",
        },
        {"@type": "JobPosting", "url": url, "datePosted": "2026-09-03"},
    ]
    html = '<script type="application/ld+json">' + json.dumps(data) + "</script>"
    posted, deadline = jobposting_dates(BeautifulSoup(html, "html.parser"), url)
    assert posted == datetime(2026, 9, 2, 15, tzinfo=UTC)
    assert deadline is None


def test_missing_date_on_later_collection_preserves_verified_publication_date():
    from dataclasses import replace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.crawler.domain import CollectedJob
    from app.crawler.persistence import upsert_collected_job
    from app.db.base import Base
    from app.models import JobPosting, JobSource

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(
            name="wanted", base_url="https://www.wanted.co.kr", crawler_type="browser"
        )
        session.add(source)
        session.flush()
        known = datetime(2026, 10, 1, tzinfo=UTC)
        data = CollectedJob(
            source_name="wanted",
            external_job_id="17",
            company_name="Synthetic",
            title="Python Backend",
            url="https://www.wanted.co.kr/wd/17",
            description_raw="synthetic",
            description_text="original",
            posted_at=known,
        )
        result = upsert_collected_job(session, source, data)
        upsert_collected_job(
            session, source, replace(data, description_text="changed", posted_at=None)
        )
        saved = session.get(JobPosting, result.job_posting_id)
        assert saved.posted_at.replace(tzinfo=UTC) == known
    engine.dispose()
