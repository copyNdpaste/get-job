from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.daily_recommendations import generate_daily_recommendations
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Application, CandidateProfile, Company, JobPosting, JobScore, JobSource


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _add_scored_job(
    session: Session,
    source: JobSource,
    company: Company,
    candidate: CandidateProfile,
    number: int,
    fit: float,
    value: float,
    *,
    hidden: bool = False,
    active: bool = True,
    hard_requirement_gaps: list[dict] | None = None,
    strict_required_gaps: list[str] | None = None,
    tech_stack: list[str] | None = None,
) -> JobPosting:
    now = datetime.now(UTC)
    job = JobPosting(
        source_id=source.id,
        external_job_id=str(number),
        company_id=company.id,
        title=f"Python Backend Engineer {number}",
        normalized_title=f"python backend engineer {number}",
        url=f"https://example.com/jobs/{number}",
        canonical_url=f"https://example.com/jobs/{number}",
        tech_stack=tech_stack or ["Python", "TypeScript"],
        first_seen_at=now - timedelta(days=number),
        last_seen_at=now,
        last_changed_at=now,
        posted_at=now - timedelta(days=number),
        is_active=active,
        is_hidden=hidden,
        content_hash=f"{number:064d}",
    )
    session.add(job)
    session.flush()
    session.add(
        JobScore(
            job_posting_id=job.id,
            candidate_profile_id=candidate.id,
            total_fit_score=fit,
            application_value_score=value,
            application_probability_score=fit,
            grade="A" if fit >= 70 else "C",
            evidence_json={
                "hard_requirement_gaps": hard_requirement_gaps or [],
                "rank_factors": {"strict_required_gaps": strict_required_gaps or []},
            },
            scored_at=now,
            scoring_version="test",
        )
    )
    return job


def _seed(session: Session) -> list[JobPosting]:
    source = JobSource(name="jumpit", base_url="https://example.com", crawler_type="http")
    company = Company(name="Example", normalized_name="example")
    candidate = CandidateProfile(name="local", profile_json={})
    session.add_all([source, company, candidate])
    session.flush()
    jobs = [
        _add_scored_job(session, source, company, candidate, 1, 91, 95),
        _add_scored_job(session, source, company, candidate, 2, 95, 90),
        _add_scored_job(session, source, company, candidate, 3, 99, 99, hidden=True),
        _add_scored_job(session, source, company, candidate, 4, 60, 95),
        _add_scored_job(session, source, company, candidate, 5, 98, 98, active=False),
    ]
    session.flush()
    return jobs


def test_daily_generation_ranks_only_active_visible_jobs_and_applies_cooldown() -> None:
    engine = _engine()
    settings = Settings(
        ai_enabled=False,
        daily_recommendation_limit=10,
        daily_recommendation_min_fit=70,
        daily_recommendation_min_value=70,
        daily_recommendation_cooldown_days=14,
    )
    with Session(engine) as session:
        jobs = _seed(session)
        first = generate_daily_recommendations(session, settings, date(2026, 7, 13))
        session.commit()
        assert [item.job_posting_id for item in first.items] == [jobs[0].id, jobs[1].id]

        second = generate_daily_recommendations(session, settings, date(2026, 7, 14))
        session.commit()
        assert second.items == []

        refreshed = generate_daily_recommendations(session, settings, date(2026, 7, 13))
        session.commit()
        assert [item.rank for item in refreshed.items] == [1, 2]

    Base.metadata.drop_all(engine)


def test_daily_generation_excludes_hard_gaps_but_keeps_optional_java_stack() -> None:
    engine = _engine()
    settings = Settings(
        ai_enabled=False,
        daily_recommendation_limit=10,
        daily_recommendation_min_fit=70,
        daily_recommendation_min_value=70,
        daily_recommendation_cooldown_days=0,
    )
    with Session(engine) as session:
        source = JobSource(name="jumpit", base_url="https://example.com", crawler_type="http")
        company = Company(name="Example", normalized_name="example")
        candidate = CandidateProfile(name="local", profile_json={})
        session.add_all([source, company, candidate])
        session.flush()
        safe = _add_scored_job(session, source, company, candidate, 10, 85, 88)
        _add_scored_job(
            session,
            source,
            company,
            candidate,
            11,
            95,
            96,
            hard_requirement_gaps=[{"key": "security_certification", "severity": "high"}],
        )
        _add_scored_job(
            session,
            source,
            company,
            candidate,
            12,
            94,
            95,
            strict_required_gaps=["Celery"],
        )
        optional_java = _add_scored_job(
            session,
            source,
            company,
            candidate,
            13,
            99,
            99,
            tech_stack=["Java", "SpringBoot", "LLM"],
        )

        batch = generate_daily_recommendations(session, settings, date(2026, 8, 11))
        session.commit()

        assert [item.job_posting_id for item in batch.items] == [optional_java.id, safe.id]

    Base.metadata.drop_all(engine)


def test_daily_generation_excludes_already_submitted_and_rejected_jobs() -> None:
    engine = _engine()
    settings = Settings(
        ai_enabled=False,
        daily_recommendation_min_fit=70,
        daily_recommendation_min_value=70,
        daily_recommendation_cooldown_days=0,
    )
    with Session(engine) as session:
        jobs = _seed(session)
        session.add_all(
            [
                Application(job_posting_id=jobs[0].id, status="applied"),
                Application(job_posting_id=jobs[1].id, status="rejected"),
            ]
        )
        batch = generate_daily_recommendations(session, settings, date(2026, 8, 28))
        session.commit()

        assert batch.items == []

    Base.metadata.drop_all(engine)


def test_daily_recommendation_api_lists_dates_and_public_job_data() -> None:
    engine = _engine()
    settings = Settings(ai_enabled=False, daily_recommendation_cooldown_days=0)
    with Session(engine) as session:
        _seed(session)
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        generated = client.post("/api/daily-recommendations/generate", json={"notify_slack": False})
        assert generated.status_code == 200
        body = generated.json()
        assert len(body["items"]) == 2
        assert body["slack_status"] == "not_requested"
        assert body["items"][0]["title"] == "Python Backend Engineer 1"
        assert "candidate" not in str(body).casefold()

        dates = client.get("/api/daily-recommendations/dates").json()
        assert dates[0]["date"] == body["date"]
        assert dates[0]["item_count"] == 2
        report = client.get("/api/daily-recommendations/report", params={"date": body["date"]})
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/markdown")
        assert report.headers["content-disposition"].endswith(f'{body["date"]}.md"')
        assert "Python Backend Engineer 1" in report.text
        assert "적합도:" in report.text
        assert "candidate" not in report.text.casefold()
        assert "profile_evidence" not in report.text
        assert (
            client.get("/api/daily-recommendations", params={"date": "2020-01-01"}).json()["items"]
            == []
        )
        assert (
            client.get(
                "/api/daily-recommendations/report", params={"date": "2020-01-01"}
            ).status_code
            == 404
        )

        with Session(engine) as session:
            assert session.scalar(select(func.count(JobPosting.id))) == 5
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_established_company_preference_keeps_unknown_size_above_known_tiny() -> None:
    with Session(_engine()) as session:
        _seed(session)
        source = session.scalar(select(JobSource))
        candidate = session.scalar(select(CandidateProfile))
        funded = Company(name="Funded", normalized_name="funded",
                         employee_count=60, investment_stage="Series B")
        tiny = Company(name="Tiny", normalized_name="tiny",
                       employee_count=9, investment_stage="Pre-A")
        session.add_all([funded, tiny])
        session.flush()
        funded_job = _add_scored_job(session, source, funded, candidate, 10, 80, 80)
        tiny_job = _add_scored_job(session, source, tiny, candidate, 11, 99, 99)
        session.flush()
        batch = generate_daily_recommendations(
            session, Settings(ai_enabled=False, daily_recommendation_prefer_established=True,
                              daily_recommendation_cooldown_days=0), date(2026, 10, 8)
        )
        ordered = [item.job_posting_id for item in batch.items]
        assert ordered[0] == funded_job.id
        assert ordered[-1] == tiny_job.id
