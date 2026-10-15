import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.local_ai import AICompletion, AIUnavailableError
from app.models import CandidateProfile, Company, JobPosting, JobScore, PreferenceEvaluation
from app.preference_scoring import (
    VERSION,
    Evaluation,
    candidate_sources,
    job_context,
    validate_evaluation,
)
from app.preference_worker import enqueue, run_batch
from app.scoring import score_jobs


def report_for(context, candidate):
    refs = [next(iter(candidate)), next(iter(context["job"]))]
    criteria = {
        key: {"score": 50, "state": "unknown", "reason": "근거 미확인", "evidence_ids": []}
        for key in ["role", "experience", "stack", "location", "company", "workload"]
    }
    for key in ["role", "experience", "stack"]:
        criteria[key] = {
            "score": 82,
            "state": "supported",
            "reason": "합성 경력과 업무가 일치",
            "evidence_ids": refs,
        }
    return {
        "job_id": context["job_id"],
        "fit_score": 82,
        "value_score": 76,
        "confidence": "medium",
        "verdict": "review",
        "summary": "합성 Python 백엔드 적합. 회사 정보는 확인 필요.",
        "criteria": criteria,
        "risks": [],
        "unknowns": ["매출·투자 미확인"],
        "questions": ["개발팀 규모는?"],
    }


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    from app.models import JobSource
    from app.profile_data import default_candidate_profile

    with factory.begin() as session:
        profile = CandidateProfile(name="Synthetic", profile_json=default_candidate_profile())
        source = JobSource(name="wanted", base_url="https://example.invalid", crawler_type="test")
        company = Company(name="Synthetic Company", normalized_name="synthetic", source_urls=[])
        session.add_all([profile, source, company])
        session.flush()
        now = datetime.now(UTC)
        for number in range(1, 4):
            session.add(
                JobPosting(
                    id=number,
                    source_id=source.id,
                    company_id=company.id,
                    title="Python Backend",
                    normalized_title="python backend",
                    external_job_id=str(number),
                    url=f"https://example.invalid/jobs/{number}",
                    canonical_url=f"https://example.invalid/jobs/{number}",
                    content_hash=str(number),
                    requirements=["Python"],
                    main_tasks=["API 개발"],
                    tech_stack=["Python"],
                    experience_text="경력 3~7년",
                    location="서울시",
                    posted_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_changed_at=now,
                    is_active=True,
                    is_primary_posting=True,
                    is_hidden=number == 3,
                )
            )
        session.flush()
    return factory


def settings(**changes):
    return Settings(
        ai_enabled=True,
        ai_provider="openai-compatible",
        ai_preference_scoring=True,
        ai_analysis_fast_model="test-model",
        ai_analysis_daily_budget=500000,
        ai_preferences_path="/nonexistent/preferences.json",
        **changes,
    )


class FakeClient:
    calls = 0

    def __init__(self, mutation=None, invalid=False, unavailable=False):
        self.mutation, self.invalid, self.unavailable = mutation, invalid, unavailable

    async def complete(self, messages, **kwargs):
        self.calls += 1
        if self.unavailable:
            raise AIUnavailableError("Synthetic offline")
        data = json.loads(messages[1]["content"])
        reports = [report_for(context, data["candidate"]) for context in data["jobs"]]
        if self.invalid:
            reports[0]["criteria"]["role"]["evidence_ids"] = ["C_invented"]
        if self.mutation:
            self.mutation()
        return AICompletion(
            content=json.dumps({"evaluations": reports}),
            model="test-model",
            input_tokens=1000,
            output_tokens=500,
        )


def test_private_contacts_and_identity_never_enter_candidate_sources():
    sources = candidate_sources(
        {
            "name": "Synthetic Person",
            "summary": "Synthetic Person python email candidate@example.invalid "
            + "-".join(["010", "1234", "5678"]),
            "years_experience": 6,
            "skills": {"strong": ["Python"], "email": "nested@example.invalid"},
            "raw_text": "PRIVATE RESUME",
        }
    )
    text = json.dumps(sources)
    assert "Synthetic Person" not in text
    assert "@" not in text and "010-1234" not in text
    assert "PRIVATE RESUME" not in text
    assert "Python" in text


def test_unknown_company_cannot_receive_known_high_score(store):
    with store() as session:
        job = session.get(JobPosting, 1)
        company = session.get(Company, job.company_id)
        candidate = {"C1": "skills: Python"}
        context = job_context(job, company)
        report = report_for(context, candidate)
        report["criteria"]["company"]["score"] = 95
        with pytest.raises(ValueError, match="unsupported_unknown_score"):
            validate_evaluation(Evaluation.model_validate(report), candidate, context)
        report["criteria"]["company"] = {
            "score": 80,
            "state": "supported",
            "reason": "매출 성장",
            "evidence_ids": [next(iter(context["job"]))],
        }
        with pytest.raises(ValueError, match="company_requires_company_facts"):
            validate_evaluation(Evaluation.model_validate(report), candidate, context)


def test_other_postings_citations_are_rejected(store):
    with store() as session:
        company = session.scalar(select(Company))
        first = job_context(session.get(JobPosting, 1), company)
        other = job_context(session.get(JobPosting, 2), company)
        candidate = {"C1": "skills: Python"}
        report = report_for(first, candidate)
        report["criteria"]["role"]["evidence_ids"] = [next(iter(other["job"]))]
        with pytest.raises(ValueError, match="invented_citation"):
            validate_evaluation(Evaluation.model_validate(report), candidate, first)


def test_queue_is_idempotent_and_applies_real_model_scores_without_rule_override(store):
    config = settings()
    client = FakeClient()
    with store() as session:
        score_jobs(session)
        session.commit()
        assert enqueue(session, config) == 2
        assert enqueue(session, config) == 2
        assert len(session.scalars(select(PreferenceEvaluation)).all()) == 2
    result = asyncio.run(run_batch(config, session_factory=store, client=client))
    assert result["completed"] == 2 and client.calls == 1
    with store() as session:
        score = session.scalar(select(JobScore).where(JobScore.job_posting_id == 1))
        assert score.total_fit_score == 82 and score.application_value_score == 76
        assert score.scoring_version == VERSION
        assert score.evidence_json["rule_scores"]["version"] != VERSION
        score_jobs(session, skip_existing=False)
        session.commit()
        assert score.total_fit_score == 82 and score.scoring_version == VERSION
        enqueue(session, config)
    assert asyncio.run(run_batch(config, session_factory=store, client=client))["outcome"] == "idle"
    assert client.calls == 1


def test_profile_change_during_inference_cannot_publish_stale_scores(store):
    config = settings()
    with store() as session:
        enqueue(session, config)

    def mutate():
        with store.begin() as session:
            profile = session.scalar(select(CandidateProfile))
            profile.profile_json = {**profile.profile_json, "summary": "changed synthetic profile"}

    result = asyncio.run(
        run_batch(config, session_factory=store, client=FakeClient(mutation=mutate))
    )
    assert result["completed"] == 0
    with store() as session:
        assert session.scalar(select(JobScore)) is None
        assert {task.status for task in session.scalars(select(PreferenceEvaluation))} == {
            "pending"
        }


@pytest.mark.parametrize("failure", ["invalid", "unavailable"])
def test_failure_never_replaces_scores_and_is_retryable(store, failure):
    config = settings()
    with store() as session:
        score_jobs(session)
        session.commit()
        enqueue(session, config)
        before = session.scalar(
            select(JobScore).where(JobScore.job_posting_id == 1)
        ).total_fit_score
    client = FakeClient(invalid=failure == "invalid", unavailable=failure == "unavailable")
    assert asyncio.run(run_batch(config, session_factory=store, client=client))["completed"] == 0
    with store() as session:
        score = session.scalar(select(JobScore).where(JobScore.job_posting_id == 1))
        assert score.total_fit_score == before and score.scoring_version != VERSION
        assert {task.status for task in session.scalars(select(PreferenceEvaluation))} == {"failed"}
        assert all(
            task.next_attempt_at.replace(tzinfo=UTC) > datetime.now(UTC)
            for task in session.scalars(select(PreferenceEvaluation))
        )


def test_exhausted_budget_does_not_call_model_or_replace_scores(store):
    config = settings()
    config.ai_analysis_daily_budget = 1
    from app.models import AIAnalysisDay

    client = FakeClient()
    with store() as session:
        enqueue(session, config)
        session.add(AIAnalysisDay(day=datetime.now(UTC).date(), reserved_tokens=1))
        session.commit()
    result = asyncio.run(run_batch(config, session_factory=store, client=client))
    assert result["outcome"] == "budget_limited"
    assert client.calls == 0
    with store() as session:
        assert session.scalar(select(JobScore)) is None


def test_ai_only_list_map_and_detail_report_consistent_provenance(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.jobs import router
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(router)

    def db():
        with store() as session:
            yield session

    app.dependency_overrides[get_db] = db
    config = settings()
    with store() as session:
        enqueue(session, config)
    asyncio.run(run_batch(config, session_factory=store, client=FakeClient()))
    with TestClient(app) as client:
        for suffix in ("", "&map_view=true"):
            response = client.get("/api/jobs?ai_scored_only=true" + suffix)
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert all(row["score_origin"] == "ai" for row in data["items"])
        detail = client.get("/api/jobs/1").json()
        assert detail["score_model"] == "test-model"
        assert detail["ai_evaluation"]["questions"] == ["개발팀 규모는?"]
