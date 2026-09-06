import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import JobPosting, JobSource
from app.tasks.sync_and_analyze import (
    UNKNOWN_LOCATION,
    analyze_job_statistics,
    build_parser,
    bulk_upsert_jobs,
    load_job_records,
    record_to_collected_job,
    sync_and_analyze,
)

SOURCE_NAME = "local-provider"
SOURCE_BASE_URL = "https://jobs.example.test"


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                JobSource(
                name=SOURCE_NAME,
                base_url=SOURCE_BASE_URL,
                crawler_type="local_json",
                ),
                JobSource(
                    name="jobplanet",
                    base_url="https://www.jobplanet.co.kr",
                    crawler_type="public_json",
                ),
            ]
        )
    return sessions


def _record(
    external_job_id: str,
    *,
    company_name: str = "Synthetic Labs",
    title: str = "Backend Engineer",
    location: str | None = "서울",
) -> dict[str, object]:
    return {
        "source_name": SOURCE_NAME,
        "external_job_id": external_job_id,
        "company_name": company_name,
        "title": title,
        "url": f"{SOURCE_BASE_URL}/jobs/{external_job_id}",
        "description_text": f"{title} Python FastAPI",
        "main_tasks": ["API 개발"],
        "requirements": ["Python 경험"],
        "tech_stack": ["Python", "FastAPI", "Python"],
        "location": location,
        "employment_type": "정규직",
        "posted_at": "2026-08-01T09:00:00+09:00",
    }


def test_record_is_converted_to_collected_job_without_network_data() -> None:
    job = record_to_collected_job(_record("job-1"))

    assert job.source_name == SOURCE_NAME
    assert job.external_job_id == "job-1"
    assert job.description_raw.startswith("{")
    assert job.tech_stack == ["Python", "FastAPI"]
    assert job.posted_at is not None
    assert job.posted_at.utcoffset() is not None


def test_jobplanet_standard_dicts_connect_directly_with_default_source() -> None:
    sessions = _session_factory()
    rows = [
        {
            "job_id": "501",
            "title": "Python Backend Engineer",
            "company_name": "Synthetic JobPlanet",
            "company_rating": 4.1,
            "location": "서울",
            "job_url": "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=501",
        }
    ]

    result = sync_and_analyze(
        rows,
        session_factory=sessions,
        default_source_name="jobplanet",
    )

    assert result.upsert.created == 1
    assert result.statistics.by_company == {"Synthetic JobPlanet": 1}


def test_sync_upserts_batch_and_returns_company_and_location_statistics() -> None:
    sessions = _session_factory()
    records = [
        _record("job-1"),
        _record("job-2", company_name="Synthetic Data", location="부산"),
        _record("job-3", title="Platform Engineer", location=None),
    ]

    first = sync_and_analyze(records, session_factory=sessions)
    second = sync_and_analyze(records, session_factory=sessions)

    assert first.upsert.received == 3
    assert first.upsert.created == 3
    assert first.upsert.updated == 0
    assert first.statistics.total_postings == 3
    assert first.statistics.by_company == {
        "Synthetic Labs": 2,
        "Synthetic Data": 1,
    }
    assert first.statistics.by_location == {
        "서울": 1,
        "부산": 1,
        UNKNOWN_LOCATION: 1,
    }
    assert second.upsert.created == 0
    assert second.upsert.unchanged == 3


def test_bulk_upsert_updates_existing_posting_in_one_transaction() -> None:
    sessions = _session_factory()
    with sessions.begin() as session:
        created = bulk_upsert_jobs(session, [_record("job-1")])
    with sessions.begin() as session:
        updated = bulk_upsert_jobs(
            session,
            [_record("job-1", title="Senior Backend Engineer", location="경기")],
        )

    assert created.created == 1
    assert updated.updated == 1
    with sessions() as session:
        posting = session.scalar(select(JobPosting))
        assert posting is not None
        assert posting.title == "Senior Backend Engineer"
        assert posting.location == "경기"


def test_bulk_upsert_rejects_duplicate_identity_before_writing() -> None:
    sessions = _session_factory()

    with pytest.raises(ValueError, match="duplicates source_name/external_job_id"):
        sync_and_analyze(
            [_record("job-1"), _record("job-1", title="Conflicting title")],
            session_factory=sessions,
        )

    with sessions() as session:
        assert session.scalar(select(JobPosting.id)) is None


@pytest.mark.parametrize(
    ("record_update", "message"),
    [
        ({"title": ""}, "title must not be empty"),
        ({"tech_stack": "Python"}, "tech_stack must be a list"),
        ({"has_coding_test": "yes"}, "has_coding_test must be a boolean"),
        ({"interview_count": -1}, "interview_count must be a non-negative integer"),
        ({"posted_at": "not-a-date"}, "posted_at must be an ISO-8601"),
    ],
)
def test_input_validation_identifies_the_failing_record(
    record_update: dict[str, object], message: str
) -> None:
    sessions = _session_factory()
    record = _record("job-1")
    record.update(record_update)

    with pytest.raises(ValueError, match=rf"jobs\[0\].*{message}"):
        sync_and_analyze([record], session_factory=sessions)


def test_upsert_requires_enabled_seeded_source_and_exact_https_host() -> None:
    sessions = _session_factory()
    wrong_host = _record("job-1")
    wrong_host["url"] = "https://other.example.test/jobs/job-1"

    with pytest.raises(ValueError, match="configured HTTPS host"):
        sync_and_analyze([wrong_host], session_factory=sessions)

    missing_source = _record("job-2")
    missing_source["source_name"] = "missing"
    with pytest.raises(ValueError, match="source is not seeded"):
        sync_and_analyze([missing_source], session_factory=sessions)


def test_statistics_can_include_inactive_postings() -> None:
    sessions = _session_factory()
    sync_and_analyze([_record("job-1")], session_factory=sessions)
    with sessions.begin() as session:
        posting = session.scalar(select(JobPosting))
        assert posting is not None
        posting.is_active = False

    with sessions() as session:
        active = analyze_job_statistics(session)
        all_rows = analyze_job_statistics(session, active_only=False)

    assert active.total_postings == 0
    assert all_rows.total_postings == 1


def test_local_json_loader_requires_an_array_of_objects(tmp_path: Path) -> None:
    valid = tmp_path / "jobs.json"
    valid.write_text(json.dumps([_record("job-1")], ensure_ascii=False), encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"jobs": []}', encoding="utf-8")

    assert load_job_records(valid)[0]["external_job_id"] == "job-1"
    with pytest.raises(ValueError, match="root must be an array"):
        load_job_records(invalid)


def test_cli_parser_requires_input_and_supports_inactive_statistics() -> None:
    args = build_parser().parse_args(
        [
            "--input",
            "jobs.local.json",
            "--source",
            "jobplanet",
            "--include-inactive",
        ]
    )

    assert args.input == Path("jobs.local.json")
    assert args.source == "jobplanet"
    assert args.include_inactive is True
