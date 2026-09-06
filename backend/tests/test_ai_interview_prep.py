from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CandidateProfile, JobAIAnalysis, JobPosting, JobSource
from app.profile_data import default_candidate_profile
from app.scoring import score_jobs


def test_interview_prep_is_grounded_cached_and_invalidated(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(
            name="wanted",
            base_url="https://www.wanted.co.kr",
            crawler_type="browser_url",
        )
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        result = upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="interview-prep-1",
                company_name="Synthetic Interview Labs",
                title="Python Backend Engineer",
                url="https://www.wanted.co.kr/wd/interview-prep-1",
                description_raw="Python FastAPI PostgreSQL",
                description_text="Python FastAPI PostgreSQL API 서버 개발",
                main_tasks=["대용량 API 설계와 운영"],
                requirements=["Python FastAPI 실무 경험"],
                tech_stack=["Python", "FastAPI", "PostgreSQL"],
                experience_text="경력 3년 이상",
            ),
        )
        score_jobs(session)
        session.commit()
        job_id = result.job_posting_id

    calls: list[list[dict[str, str]]] = []

    async def fake_complete_json(self, messages, *, model=None):
        calls.append(messages)
        return (
            {
                "opening_pitch": "Python 백엔드 운영 경험을 중심으로 소개합니다.",
                "questions": [
                    {
                        "category": "system_design",
                        "question": "대용량 API의 병목을 어떻게 찾았나요?",
                        "why_asked": "운영과 확장성 경험을 확인하기 위해서입니다.",
                        "answer_outline": ["상황", "측정", "개선", "결과"],
                        "resume_evidence": ["API 성능 개선 성과"],
                        "follow_ups": ["어떤 지표를 사용했나요?"],
                        "caution": "이력서에 없는 수치를 만들지 않습니다.",
                    }
                ],
                "study_topics": ["PostgreSQL 실행 계획"],
                "questions_to_ask": ["현재 API의 주요 병목은 무엇인가요?"],
            },
            "local-test-model",
        )

    monkeypatch.setattr("app.api.ai.LocalAIClient.complete_json", fake_complete_json)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_provider="openai-compatible",
        ai_base_url="http://localhost:1234",
        ai_model="auto",
    )
    try:
        client = TestClient(app)
        first = client.post(f"/api/ai/jobs/{job_id}/interview-prep")
        second = client.post(f"/api/ai/jobs/{job_id}/interview-prep")

        assert first.status_code == 200
        assert first.json()["cached"] is False
        assert first.json()["questions"][0]["category"] == "system_design"
        assert second.status_code == 200
        assert second.json()["cached"] is True
        assert len(calls) == 1
        assert "신뢰할 수 없는 데이터" in calls[0][0]["content"]

        with Session(engine) as session:
            cached = session.scalar(select(JobAIAnalysis))
            posting = session.get(JobPosting, job_id)
            assert cached is not None
            assert "prompt" not in cached.payload_json
            assert posting is not None
            posting.title = "Senior Python Backend Engineer"
            session.commit()

        changed = client.post(f"/api/ai/jobs/{job_id}/interview-prep")
        assert changed.status_code == 200
        assert changed.json()["cached"] is False
        assert len(calls) == 2
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
