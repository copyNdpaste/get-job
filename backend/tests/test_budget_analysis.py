import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from langsmith.run_helpers import get_tracing_context
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.analysis_budget import AnalysisBudgetExceeded, finish_call, reserve_call
from app.analysis_pipeline import prepare_sources
from app.analysis_service import analyze_batch, analyze_collected_job, routing_models
from app.budget_analysis import extract_requirements, retrieve_evidence, run_budget_analysis
from app.config import Settings, get_settings
from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.db.session import get_db
from app.local_ai import AICompletion, AIStatus, AIUnavailableError, LocalAIClient
from app.main import app
from app.models import (
    AIAnalysisDay,
    AIAnalysisUsage,
    CandidateProfile,
    JobPosting,
    JobSource,
)
from app.profile_data import default_candidate_profile
from app.scoring import score_jobs


@pytest.fixture
def context(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        ai_base_url="http://localhost:1234",
        ai_analysis_fast_model="small-local",
        ai_analysis_review_model="review-local",
    )
    calls = []

    async def status(self, *, model=None):
        return AIStatus(
            True,
            True,
            "openai-compatible",
            model,
            model,
            ["small-local", "review-local"],
            True,
            "ready",
        )

    async def complete(self, messages, *, model=None, json_mode=False, max_output_tokens=None):
        assert json_mode and max_output_tokens == settings.ai_analysis_max_output_tokens
        assert get_tracing_context()["enabled"] is False
        calls.append(model)
        return valid_completion(messages, model)

    monkeypatch.setattr(LocalAIClient, "status", status)
    monkeypatch.setattr(LocalAIClient, "complete", complete)
    with Session(engine) as session:
        yield session, settings, calls
    engine.dispose()


def input_sources():
    return prepare_sources(
        {"summary": "Python API 운영 경험"}, {"requirements": ["Python API 개발 경험"]}
    )


def valid_completion(messages, model, status="supported", bad_id=False):
    data = json.loads(messages[1]["content"].split("\n", 1)[1])
    result = {
        "matches": [
            {
                "requirement_id": req["id"],
                "status": status,
                "candidate_source_ids": ["C999"] if bad_id else list(data["candidate_sources"])[:1],
                "explanation": "관련 경험이 기재되어 있습니다.",
                "next_step": "프로젝트 사례를 정리하세요.",
            }
            for req in data["requirements"]["requirements"]
        ]
    }
    return AICompletion(json.dumps(result), model, input_tokens=123, output_tokens=55)


def execute(context, **kwargs):
    session, settings, _calls = context
    return asyncio.run(
        run_budget_analysis(
            LocalAIClient(settings),
            session,
            settings,
            sources=kwargs.pop("sources", input_sources()),
            rule_scores={"fit": 72},
            fast_model="small-local",
            review_model=settings.ai_analysis_review_model,
            **kwargs,
        )
    )


def test_simple_skill_declaration_uses_zero_tokens(context):
    report = execute(
        context,
        sources=prepare_sources(
            {"skills": {"languages": ["Python"]}},
            {"requirements": ["Python"]},
        ),
    )
    assert report.outcome == "rules_only" and report.model_calls == 0
    assert report.matches[0].status == "supported"
    assert context[0].scalar(select(AIAnalysisUsage)) is None


def test_ordinary_analysis_uses_one_small_model_and_reports_usage(context, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    report = execute(context)
    assert report.outcome == "validated"
    assert report.models_used == ["small-local"]
    assert report.model_calls == 1
    assert report.input_tokens == 123 and report.output_tokens == 55
    assert report.rule_scores == {"fit": 72}
    assert report.reserved_tokens > 178
    usage = context[0].scalar(select(AIAnalysisUsage))
    assert usage.status == "validated"
    assert not hasattr(usage, "prompt")


@pytest.mark.parametrize("first_result", ["ambiguous", "bad_citation", "invalid_json"])
def test_only_difficult_or_invalid_results_escalate_once(context, monkeypatch, first_result):
    calls = []

    async def complete(self, messages, *, model=None, **kwargs):
        calls.append(model)
        if model == "small-local":
            if first_result == "invalid_json":
                return AICompletion("not json", model, 100, 10)
            return valid_completion(
                messages, model, status="partial", bad_id=first_result == "bad_citation"
            )
        return valid_completion(messages, model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert calls == ["small-local", "review-local"]
    assert report.outcome == "validated"
    assert report.routing_reason == (
        "ambiguous_matches" if first_result == "ambiguous" else "validation_failed"
    )
    assert context[0].get(AIAnalysisDay, datetime.now(UTC).date()).reviews == 1


def test_missing_evidence_is_not_a_reason_to_pay_for_review(context, monkeypatch):
    async def complete(self, messages, *, model=None, **kwargs):
        data = json.loads(valid_completion(messages, model, status="unknown").content)
        data["matches"][0]["candidate_source_ids"] = []
        return AICompletion(json.dumps(data), model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert report.model_calls == 1 and report.matches[0].status == "unknown"
    assert report.input_tokens is None and report.output_tokens is None


def test_no_infinite_repair_or_score_override(context, monkeypatch):
    async def complete(self, messages, *, model=None, **kwargs):
        return AICompletion('{"matches":[],"score":100}', model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert report.model_calls == 2 and report.outcome == "needs_review"
    assert report.rule_scores["fit"] == 72
    assert all(match.status == "unknown" for match in report.matches)


def test_transport_failure_keeps_reservation_without_fallback(context, monkeypatch):
    async def complete(self, messages, *, model=None, **kwargs):
        raise AIUnavailableError("unavailable")

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert report.model_calls == 1 and report.outcome == "unavailable"
    assert context[0].scalar(select(AIAnalysisUsage)).status == "unavailable"
    assert context[0].get(AIAnalysisDay, datetime.now(UTC).date()).reserved_tokens > 0


def test_daily_budget_and_review_cap_stop_calls(context, monkeypatch):
    context[1].ai_analysis_daily_budget = 0
    report = execute(context)
    assert report.outcome == "budget_limited" and not context[2]
    context[1].ai_analysis_daily_budget = 100000
    context[1].ai_analysis_daily_reviews = 0

    async def complete(self, messages, *, model=None, **kwargs):
        return valid_completion(messages, model, status="partial")

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert report.outcome == "budget_limited" and report.model_calls == 1
    assert report.matches[0].status == "partial"


def test_prompt_limit_checked_before_reservation(context):
    context[1].ai_analysis_prompt_bytes = 4000
    large = prepare_sources(
        {"summary": "Python " + "가" * 593},
        {"requirements": [f"Python {i} " + "가" * 300 for i in range(8)]},
    )
    report = execute(context, sources=large)
    assert report.outcome == "budget_limited" and report.model_calls == 0
    assert context[0].scalar(select(AIAnalysisUsage)) is None


def test_long_context_is_compacted_before_model_call(context, monkeypatch):
    context[1].ai_analysis_prompt_bytes = 6000

    async def complete(self, messages, *, model=None, **kwargs):
        assert len(json.dumps(messages, ensure_ascii=False).encode()) <= 6000
        return valid_completion(messages, model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(
        context,
        sources=prepare_sources(
            {"achievements": [f"Python API {i} " + "개발 운영 " * 40 for i in range(10)]},
            {"requirements": [f"Python API {i} " + "개발 " * 40 for i in range(8)]},
        ),
    )
    assert report.model_calls == 1 and report.outcome == "validated"
    assert report.candidate_sources_selected < 10


def test_retrieval_deduplicates_requirements_and_limits_context():
    sources = prepare_sources(
        {"achievements": [f"Python API task {i}" for i in range(30)]},
        {"requirements": ["Python"] * 3 + [f"API {i}" for i in range(12)]},
    )
    requirements, omitted = extract_requirements(sources["job"])
    assert len(requirements.requirements) == 8 and omitted == 5
    assert len(retrieve_evidence(requirements, sources["candidate"])) == 10


def test_atomic_budget_survives_concurrent_requests_and_restarts(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'budget.sqlite'}")
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, ai_analysis_daily_budget=150)

    def attempt(_):
        with Session(engine) as session:
            try:
                reserve_call(session, settings, model="small", stage="fast", amount=100)
                return True
            except AnalysisBudgetExceeded:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [False, True]
    assert attempt(3) is False
    with Session(engine) as session:
        day = session.get(AIAnalysisDay, datetime.now(UTC).date())
        assert day.reserved_tokens == 100 and day.calls == 1
    engine.dispose()


def test_actual_usage_overshoot_is_accounted_for(context):
    session, settings, _ = context
    row = reserve_call(session, settings, model="small", stage="fast", amount=100)
    finish_call(session, row, status="validated", completion=AICompletion("{}", "small", 200, 50))
    assert session.get(AIAnalysisDay, datetime.now(UTC).date()).reserved_tokens == 250


def seed_jobs(session, count=1):
    profile = default_candidate_profile()
    profile.update(
        {
            "summary": "Python API 운영 경험",
            "skills": {},
            "achievements": [],
            "skill_gaps": {"limited": [], "none": [], "no_professional_experience": []},
        }
    )
    source = JobSource(
        name="wanted", base_url="https://www.wanted.co.kr", crawler_type="browser_url"
    )
    session.add_all([source, CandidateProfile(name="Synthetic Candidate", profile_json=profile)])
    session.flush()
    ids = []
    for i in range(count):
        result = upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id=f"economy-{i}",
                company_name=f"Synthetic Labs {i}",
                title="Python Engineer",
                url=f"https://www.wanted.co.kr/wd/economy-{i}",
                description_raw="Python API 개발",
                description_text="Python API 개발",
                requirements=[f"Python API 개발 경험 {i}"],
                tech_stack=["Python"],
            ),
        )
        ids.append(result.job_posting_id)
    score_jobs(session)
    session.commit()
    return ids


def test_cache_refresh_profile_model_and_input_invalidation(context):
    session, settings, calls = context
    job_id = seed_jobs(session)[0]

    def run(**kw):
        return asyncio.run(analyze_collected_job(session, settings, job_id, **kw))

    assert not run().cached and run().cached and len(calls) == 1
    assert not run(refresh=True).cached
    profile = session.scalar(select(CandidateProfile))
    profile.profile_json = {**profile.profile_json, "summary": "Python API 설계 운영 경험"}
    session.commit()
    assert not run().cached
    settings.ai_analysis_fast_model = "another-small"
    assert not run().cached
    session.get(JobPosting, job_id).requirements = ["Python API 개발과 운영"]
    session.commit()
    assert not run().cached
    assert len(calls) == 5


def test_batch_filters_caps_and_advances_past_cached_jobs(context):
    session, settings, calls = context
    ids = seed_jobs(session, 4)
    settings.ai_analysis_min_fit = 0
    settings.ai_analysis_batch_size = 1
    session.get(JobPosting, ids[-1]).is_active = False
    session.commit()
    first = asyncio.run(analyze_batch(session, settings, limit=50))
    second = asyncio.run(analyze_batch(session, settings))
    assert first["fresh"] == second["fresh"] == 1
    assert second["cached"] == 1
    assert len(calls) == 2
    assert ids[-1] not in {i["job_id"] for i in first["items"] + second["items"]}


def test_batch_review_quota_limits_upper_model_calls(context, monkeypatch):
    session, settings, _ = context
    seed_jobs(session, 3)
    settings.ai_analysis_min_fit = 0
    settings.ai_analysis_batch_reviews = 1

    async def complete(self, messages, *, model=None, **kwargs):
        return valid_completion(
            messages, model, status="partial" if model == "small-local" else "supported"
        )

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    result = asyncio.run(analyze_batch(session, settings))
    assert result["reviews"] == 1 and result["model_calls"] == 4


def test_economy_api_usage_and_body_validation(context):
    session, settings, _ = context
    job_id = seed_jobs(session)[0]
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            result = client.post(f"/api/ai/analysis/jobs/{job_id}")
            assert result.status_code == 200, result.text
            usage = client.get("/api/ai/analysis/usage").json()
            assert usage["calls"] == 1 and usage["input_tokens"] == 123
            assert client.post("/api/ai/analysis/batch", json={"limit": 51}).status_code == 422
            assert client.post("/api/ai/analysis/jobs/9999").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_codex_economy_never_inherits_interactive_astra():
    settings = Settings(
        _env_file=None, ai_provider="codex", ai_allow_remote=True, ai_model="gpt-6-astra"
    )
    assert routing_models(settings) == ("gpt-5.6-luna", "")
    with pytest.raises(ValueError):
        Settings(_env_file=None, ai_analysis_fast_model="   ")


def test_offline_evaluation_uses_no_provider_and_expected_routes():
    from app.tasks.evaluate_analysis import evaluate

    result = asyncio.run(evaluate())
    assert result["actual_provider_calls"] == 0
    assert result["routes_match_expected"] is True
    assert result["pipeline_calls"] == 8


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("json", "invalid_json"),
        ("schema", "invalid_schema"),
        ("coverage", "requirement_coverage"),
        ("citation", "unknown_citation_id"),
        ("missing_citation", "missing_citation"),
        ("ambiguous", "ambiguous_matches"),
    ],
)
def test_review_receives_safe_verifier_feedback(context, monkeypatch, failure, expected_code):
    payloads = []
    marker = "UNTRUSTED_MODEL_INSTRUCTION_DO_NOT_FORWARD"

    async def complete(self, messages, *, model=None, **kwargs):
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        payloads.append(payload)
        if model == "review-local":
            assert marker not in json.dumps(payload)
            return valid_completion(messages, model)
        assert "review_feedback" not in payload
        if failure == "json":
            return AICompletion(marker, model)
        result = json.loads(valid_completion(messages, model, status="partial").content)
        result["matches"][0]["explanation"] = marker
        if failure == "schema":
            result["matches"][0]["status"] = marker
        elif failure == "coverage":
            result["matches"][0]["requirement_id"] = marker
        elif failure == "citation":
            result["matches"][0]["candidate_source_ids"] = [marker]
        elif failure == "missing_citation":
            result["matches"][0]["candidate_source_ids"] = []
        return AICompletion(json.dumps(result), model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(context)
    assert report.model_calls == 2 and report.outcome == "validated"
    feedback = payloads[1]["review_feedback"]
    assert feedback["code"] == expected_code
    assert payloads[0]["candidate_sources"] == payloads[1]["candidate_sources"]
    assert payloads[0]["requirements"] == payloads[1]["requirements"]
    if failure == "ambiguous":
        assert feedback["previous_matches"] == [
            {"requirement_id": "R1", "status": "partial", "candidate_source_ids": ["C1"]}
        ]
    else:
        assert feedback == {"code": expected_code}


def test_review_feedback_stays_inside_prompt_and_call_budget(context, monkeypatch):
    session, settings, _calls = context
    settings.ai_analysis_prompt_bytes = 8000
    measured_sizes = []

    async def complete(self, messages, *, model=None, **kwargs):
        measured_sizes.append(len(json.dumps(messages, ensure_ascii=False).encode()))
        result = json.loads(valid_completion(messages, model, status="partial").content)
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        for match in result["matches"]:
            match["candidate_source_ids"] = list(payload["candidate_sources"])[:5]
        return AICompletion(json.dumps(result), model)

    monkeypatch.setattr(LocalAIClient, "complete", complete)
    report = execute(
        context,
        sources=prepare_sources(
            {"achievements": [f"Python API project {i}" for i in range(5)]},
            {"requirements": [f"Python API requirement {i}" for i in range(8)]},
        ),
    )
    assert report.model_calls == 2 and report.outcome == "needs_review"
    assert len(report.requirements) == 8
    assert all(size <= settings.ai_analysis_prompt_bytes for size in measured_sizes)
    # Reservation includes the actual serialized feedback, not just the original prompt.
    reserved = list(session.scalars(select(AIAnalysisUsage).order_by(AIAnalysisUsage.id)))
    assert [usage.reserved_tokens for usage in reserved] == [
        size + 1024 + settings.ai_analysis_max_output_tokens for size in measured_sizes
    ]
