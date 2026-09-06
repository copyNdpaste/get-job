import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.crawler.domain import CollectedJob
from app.db.base import Base
from app.deduplication import DeduplicationSummary
from app.jobplanet_sync import JobPlanetSyncPipeline, build_parser
from app.models import CandidateProfile, Company, JobPosting, JobSource


def _job() -> CollectedJob:
    return CollectedJob(
        source_name="jobplanet",
        external_job_id="sync-101",
        company_name="Synthetic Sync Labs",
        title="Python Backend Engineer",
        url="https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=sync-101",
        description_raw='{"job_id":"sync-101"}',
        description_text="Python Backend Engineer FastAPI PostgreSQL",
        tech_stack=["Python", "FastAPI", "PostgreSQL"],
        location="서울",
    )


def _row() -> dict[str, object]:
    return {
        "job_id": "sync-101",
        "company_name": "Synthetic Sync Labs",
        "company_rating": 0.0,
        "title": "Python Backend Engineer",
        "job_url": (
            "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=sync-101"
        ),
        "location": "서울",
    }


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                JobSource(
                    name="jobplanet",
                    base_url="https://www.jobplanet.co.kr",
                    crawler_type="public_json",
                ),
                CandidateProfile(name="테스트 후보자", profile_json={}),
            ]
        )
    return sessions


def test_pipeline_collects_persists_analyzes_and_is_idempotent(monkeypatch) -> None:
    sessions = _session_factory()
    collected_pages: list[int] = []
    scored_job_ids: list[set[int]] = []

    class FakeJobPlanetApiClient:
        async def get_jobs(self, page=1, per=20):
            assert per == 100
            collected_pages.append(page)
            return [_row()]

    def fake_score(_session, *, job_ids, skip_existing):
        assert skip_existing is False
        scored_job_ids.append(job_ids)
        return len(job_ids)

    monkeypatch.setattr("app.jobplanet_sync.JobPlanetApiClient", FakeJobPlanetApiClient)
    monkeypatch.setattr("app.jobplanet_sync.score_jobs", fake_score)
    monkeypatch.setattr(
        "app.jobplanet_sync.refresh_duplicate_groups",
        lambda _session: DeduplicationSummary(groups=0, grouped_postings=0),
    )
    pipeline = JobPlanetSyncPipeline(
        Settings(ai_enabled=False),
        session_factory=sessions,
    )

    first = asyncio.run(pipeline.run(max_jobs=25))
    second = asyncio.run(pipeline.run(max_jobs=25))

    assert collected_pages == [1, 1]
    assert first.created == 1
    assert first.unchanged == 0
    assert first.analyzed == 1
    assert second.created == 0
    assert second.unchanged == 1
    assert second.analyzed == 1
    assert len(scored_job_ids[0]) == 1
    assert scored_job_ids[1] == scored_job_ids[0]
    with sessions() as session:
        assert session.scalar(select(func.count(JobPosting.id))) == 1
        assert session.scalar(select(func.count(Company.id))) == 1


def test_pipeline_rolls_back_persistence_when_analysis_fails(monkeypatch) -> None:
    sessions = _session_factory()
    pipeline = JobPlanetSyncPipeline(
        Settings(ai_enabled=False),
        session_factory=sessions,
    )

    def fail_score(*_args, **_kwargs):
        raise RuntimeError("analysis failed")

    monkeypatch.setattr("app.jobplanet_sync.score_jobs", fail_score)

    with pytest.raises(RuntimeError, match="analysis failed"):
        pipeline.persist_and_analyze([_job()], started_at=datetime.now(UTC))

    with sessions() as session:
        assert session.scalar(select(func.count(JobPosting.id))) == 0
        assert session.scalar(select(func.count(Company.id))) == 0


def test_pipeline_validates_configuration_and_seeded_context() -> None:
    sessions = _session_factory()
    pipeline = JobPlanetSyncPipeline(
        Settings(ai_enabled=False),
        session_factory=sessions,
    )

    with pytest.raises(ValueError, match="1 이상"):
        asyncio.run(pipeline.run(max_jobs=0))

    empty_engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(empty_engine)
    empty_sessions = sessionmaker(bind=empty_engine)
    missing_seed = JobPlanetSyncPipeline(
        Settings(ai_enabled=False),
        session_factory=empty_sessions,
    )

    with pytest.raises(RuntimeError, match="app.seed"):
        asyncio.run(missing_seed.run(max_jobs=10))


def test_cli_parser_uses_safe_default_and_accepts_limit() -> None:
    parser = build_parser()

    assert parser.parse_args([]).max_jobs == 5_000
    assert parser.parse_args(["--max-jobs", "25"]).max_jobs == 25
