from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.collection_timing import aware, build_timing_report
from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.models import JobPosting, JobPostingSnapshot, JobSource


def test_observation_does_not_make_unchanged_job_look_updated():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://www.wanted.co.kr", crawler_type="http")
        session.add(source)
        session.flush()
        first_time = datetime.now(UTC) - timedelta(minutes=10)
        job = CollectedJob(
            "wanted",
            "1",
            "Example",
            "Python Backend",
            "https://www.wanted.co.kr/wd/1",
            "Python",
            "Python",
            observed_at=first_time,
        )
        first = upsert_collected_job(session, source, job)
        again = upsert_collected_job(session, source, replace(job, observed_at=datetime.now(UTC)))
        assert first.status == "created"
        assert again.status == "unchanged"
        snapshots = session.scalars(select(JobPostingSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].structured_content["collection_timing"]["observed_at"] == (
            first_time.isoformat()
        )
        saved = session.get(JobPosting, first.job_posting_id)
        assert aware(saved.first_seen_at) > first_time


def test_timing_preserves_timezone_lag_and_sampling_uncertainty():
    parsed = datetime(2026, 10, 8, 0, 59, tzinfo=UTC)  # 09:59 KST
    saved = parsed + timedelta(minutes=2)
    report = build_timing_report(
        [
            {
                "id": 1,
                "source": "wanted",
                "url": "https://www.wanted.co.kr/wd/1",
                "first_seen_at": saved,
                "snapshot": {"collection_timing": {"observed_at": parsed.isoformat()}},
            }
        ],
        [
            {
                "source": "wanted",
                "started_at": parsed - timedelta(minutes=5),
                "finished_at": saved,
                "status": "partial",
            }
        ],
    )
    source = report["sources"][0]
    assert source["discoveries_by_observed_hour"] == {"09:00": 1}
    assert source["median_parse_to_save_seconds"] == 120
    assert source["initial_or_uncovered_postings"] == 1
    assert source["scan_status_counts"] == {"partial": 1}
    assert source["schedule_adjustment"]["ready"] is False


def test_old_rows_and_invalid_observation_do_not_claim_precise_times():
    saved = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
    report = build_timing_report(
        [
            {
                "id": n,
                "source": "groupby",
                "url": "https://groupby.kr/positions/1",
                "first_seen_at": saved,
                "snapshot": snapshot,
            }
            for n, snapshot in enumerate(
                [
                    {},
                    {"collection_timing": {"observed_at": "bad"}},
                    {
                        "collection_timing": {
                            "observed_at": (saved + timedelta(hours=1)).isoformat()
                        }
                    },
                ]
            )
        ],
        [],
    )
    source = report["sources"][0]
    assert source["legacy_save_time_estimates"] == 3
    assert source["detail_parse_timestamps"] == 0
    assert source["discoveries_by_observed_hour"] == {"13:00": 3}
