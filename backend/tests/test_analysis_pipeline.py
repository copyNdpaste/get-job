import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langsmith.run_helpers import get_tracing_context
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.analysis_pipeline import (
    MAX_INPUT_BYTES,
    PipelineInputError,
    prepare_sources,
    run_analysis_pipeline,
)
from app.config import Settings, get_settings
from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.db.session import get_db
from app.local_ai import AIStatus, AIUnavailableError, LocalAIClient
from app.main import app
from app.models import CandidateProfile, JobAIAnalysis, JobPosting, JobScore, JobSource
from app.profile_data import default_candidate_profile
from app.scoring import score_jobs


def sources():
    return prepare_sources(
        {"summary": "Python API 운영 경험"}, {"requirements": ["Python API 개발"]},
    )


def output_for(messages):
    if "R1부터" in messages[1]["content"]:
        return {"requirements": [{
            "id": "R1", "title": "Python API 개발", "kind": "required",
            "source_id": "J1", "quote": "Python API 개발",
        }]}
    return {"matches": [{
        "requirement_id": "R1", "status": "supported", "candidate_source_ids": ["C1"],
        "explanation": "Python API 경험이 기재되어 있습니다.",
        "next_step": "운영 중 해결한 문제를 정리하세요.",
    }]}


def test_graph_runs_with_private_tracing_disabled_and_preserves_scores(monkeypatch):
    calls = []
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    async def complete(self, messages, *, model=None):
        assert get_tracing_context()["enabled"] is False
        assert "신뢰할 수 없는 데이터" in messages[0]["content"]
        calls.append(messages)
        return output_for(messages), model

    monkeypatch.setattr(LocalAIClient, "complete_json", complete)
    report = asyncio.run(run_analysis_pipeline(
        LocalAIClient(Settings(_env_file=None)), model="gpt-6-astra",
        sources=sources(), rule_scores={"fit": 72.0},
    ))
    assert report.rule_scores == {"fit": 72.0}
    assert report.model_calls == len(calls) == 2
    assert len(report.steps) == 3
    assert report.matches[0].status == "supported"


@pytest.mark.parametrize("failure", ["invented_quote", "wrong_kind", "missing_match",
                                     "invented_candidate", "no_citation", "score_override"])
def test_invalid_output_gets_only_one_repair(monkeypatch, failure):
    calls = []

    async def complete(self, messages, *, model=None):
        calls.append(messages)
        payload = output_for(messages)
        if "requirements" in payload:
            if failure == "invented_quote":
                payload["requirements"][0]["quote"] = "Java 전문가"
            if failure == "wrong_kind":
                payload["requirements"][0]["kind"] = "preferred"
        else:
            if failure == "missing_match":
                payload["matches"] = []
            if failure == "invented_candidate":
                payload["matches"][0]["candidate_source_ids"] = ["C999"]
            if failure == "no_citation":
                payload["matches"][0]["candidate_source_ids"] = []
            if failure == "score_override":
                payload["fit"] = 100
        return payload, model

    monkeypatch.setattr(LocalAIClient, "complete_json", complete)
    with pytest.raises(AIUnavailableError, match="검증하지 못했습니다"):
        asyncio.run(run_analysis_pipeline(
            LocalAIClient(Settings(_env_file=None)), model="synthetic-model",
            sources=sources(), rule_scores={},
        ))
    assert len(calls) == (2 if failure in {"invented_quote", "wrong_kind"} else 3)


def test_repair_recovers_without_repeating_successful_steps(monkeypatch):
    calls = []

    async def complete(self, messages, *, model=None):
        calls.append(messages)
        payload = output_for(messages)
        if len(calls) == 2:
            payload["matches"][0]["candidate_source_ids"] = ["C999"]
        return payload, model

    monkeypatch.setattr(LocalAIClient, "complete_json", complete)
    report = asyncio.run(run_analysis_pipeline(
        LocalAIClient(Settings(_env_file=None)), model="synthetic-model",
        sources=sources(), rule_scores={},
    ))
    assert report.model_calls == 3
    assert [step.attempts for step in report.steps] == [1, 2, 1]


def test_transport_failure_does_not_retry_or_switch_model(monkeypatch):
    calls = []

    async def complete(self, messages, *, model=None):
        calls.append(model)
        raise AIUnavailableError("unavailable")

    monkeypatch.setattr(LocalAIClient, "complete_json", complete)
    with pytest.raises(AIUnavailableError):
        asyncio.run(run_analysis_pipeline(
            LocalAIClient(Settings(_env_file=None)), model="gpt-6-astra",
            sources=sources(), rule_scores={},
        ))
    assert calls == ["gpt-6-astra"]


def test_source_allowlist_and_size_boundaries():
    result = prepare_sources({
        "summary": "Python 경험", "email": "synthetic@example.invalid", "raw_text": "OMIT_RAW",
        "achievements": [{"title": "API 개발", "phone": "OMIT_PHONE"}],
    }, {"requirements": ["Python"], "description_raw": "OMIT_DESCRIPTION"})
    serialized = json.dumps(result)
    assert "OMIT" not in serialized and "example.invalid" not in serialized
    with pytest.raises(PipelineInputError, match="너무 큽니다"):
        prepare_sources({"summary": "가" * MAX_INPUT_BYTES}, {"requirements": ["Python"]})
    with pytest.raises(PipelineInputError, match="모두 필요"):
        prepare_sources({"summary": "Python"}, {})


@pytest.fixture
def api_client(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, ai_base_url="http://localhost:1234", ai_model="auto")
    calls = []

    async def status(self, *, model=None):
        return AIStatus(True, True, settings.ai_provider, model or settings.ai_model,
                        "synthetic-model", ["synthetic-model"], True, "ready")

    async def complete(self, messages, *, model=None):
        calls.append(messages)
        return output_for(messages), model

    monkeypatch.setattr(LocalAIClient, "status", status)
    monkeypatch.setattr(LocalAIClient, "complete_json", complete)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://www.wanted.co.kr",
                           crawler_type="browser_url")
        profile = default_candidate_profile()
        profile.update({"summary": "Python API 운영 경험", "skills": {}, "achievements": [],
                        "skill_gaps": {"limited": [], "none": [],
                                       "no_professional_experience": []}})
        session.add_all([source, CandidateProfile(
            name="Synthetic Candidate", profile_json=profile,
        )])
        session.flush()
        result = upsert_collected_job(session, source, CollectedJob(
            source_name="wanted", external_job_id="pipeline-1", company_name="Synthetic Labs",
            title="Python Engineer", url="https://www.wanted.co.kr/wd/pipeline-1",
            description_raw="Python API 개발", description_text="Python API 개발",
            requirements=["Python API 개발"], tech_stack=["Python"],
        ))
        score_jobs(session)
        session.commit()
        job_id = result.job_posting_id

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client, engine, job_id, settings, calls
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_api_cache_refresh_input_and_endpoint_invalidation(api_client):
    client, engine, job_id, settings, calls = api_client
    url = f"/api/ai/jobs/{job_id}/analysis"
    with Session(engine) as session:
        before = session.scalar(select(JobScore)).total_fit_score
    first = client.post(url)
    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    assert client.post(url).json()["cached"] is True
    assert len(calls) == 2
    assert client.post(url + "?refresh=true").json()["cached"] is False
    with Session(engine) as session:
        posting = session.get(JobPosting, job_id)
        posting.requirements = ["Python API 개발 및 운영"]
        session.commit()
    assert client.post(url).json()["cached"] is False
    settings.ai_base_url = "http://localhost:1235"
    assert client.post(url).json()["cached"] is False
    assert len(calls) == 8
    with Session(engine) as session:
        cached = session.scalar(select(JobAIAnalysis))
        assert "prompt" not in cached.payload_json
        assert session.scalar(select(JobScore)).total_fit_score == before


def test_api_preconditions_no_model_calls(api_client):
    client, engine, job_id, settings, calls = api_client
    assert client.post("/api/ai/jobs/99999/analysis").status_code == 404
    assert client.post(f"/api/ai/jobs/{job_id}/analysis?model=" + "m" * 121).status_code == 422
    settings.ai_enabled = False
    assert client.post(f"/api/ai/jobs/{job_id}/analysis").status_code == 503
    settings.ai_enabled = True
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile))
        profile.profile_json = {"summary": "x" * (MAX_INPUT_BYTES + 1)}
        session.commit()
    assert client.post(f"/api/ai/jobs/{job_id}/analysis").status_code == 422
    assert calls == []


def test_astra_uses_existing_explicit_remote_opt_in():
    with pytest.raises(ValueError, match="explicit user consent"):
        Settings(_env_file=None, ai_provider="codex", ai_model="gpt-6-astra")
    settings = Settings(_env_file=None, ai_provider="codex", ai_model="gpt-6-astra",
                        ai_allow_remote=True)
    assert settings.ai_model == "gpt-6-astra"


def test_astra_bridge_transport_and_no_silent_model_fallback():
    available = ["gpt-6-astra"]
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["X-Job-Radar-Bridge"] == "codex-gpt-consent"
        assert request.url.host == "localhost"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": model} for model in available]})
        assert json.loads(request.content)["model"] == "gpt-6-astra"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    client = LocalAIClient(Settings(
        _env_file=None, ai_provider="codex", ai_allow_remote=True,
        ai_model="gpt-6-astra", ai_base_url="http://localhost:48765",
    ), transport=httpx.MockTransport(handler))
    payload, model = asyncio.run(client.complete_json([{"role": "user", "content": "synthetic"}]))
    assert payload == {"ok": True} and model == "gpt-6-astra"
    available[:] = ["different-model"]
    requests.clear()
    with pytest.raises(AIUnavailableError):
        asyncio.run(client.complete_json([{"role": "user", "content": "synthetic"}]))
    assert len(requests) == 1 and requests[0].url.path == "/v1/models"
