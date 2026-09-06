from pathlib import Path

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
from app.models import CandidateProfile, JobPosting, JobScore, JobSource
from app.profile_data import default_candidate_profile
from app.resume_recommendation import build_resume_recommendation
from app.scoring import score_jobs


def _job(session: Session, *, title: str, tasks: list[str], requirements: list[str]):
    source = JobSource(name="test-source", base_url="https://example.com", crawler_type="http")
    session.add(source)
    session.flush()
    result = upsert_collected_job(
        session,
        source,
        CollectedJob(
            source_name="test-source",
            external_job_id=title,
            company_name="테스트 스타트업",
            title=title,
            url=f"https://example.com/jobs/{len(title)}",
            description_raw="\n".join([title, *tasks, *requirements]),
            description_text="\n".join([title, *tasks, *requirements]),
            main_tasks=tasks,
            requirements=requirements,
            tech_stack=["Python", "AWS", "Docker"],
            experience_text="경력 3년 이상",
        ),
    )
    posting = session.get(JobPosting, result.job_posting_id)
    assert posting is not None
    return posting


def test_backend_job_recommends_python_backend_resume() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        posting = _job(
            session,
            title="Python Backend Engineer",
            tasks=["REST API와 데이터 모델을 설계하고 비동기 메시징을 운영합니다."],
            requirements=["Python Django 또는 FastAPI 서버 개발 경험"],
        )
        result = build_resume_recommendation(
            posting,
            default_candidate_profile(),
            fit_score=82,
            missing_skills=[],
        )

    assert result["recommended_id"] == "python_backend"
    assert {item["id"] for item in result["resumes"]} == {
        "python_backend",
        "python_typescript_backend",
        "server_infra",
        "product_builder",
    }
    assert sum(result["resumes"][0]["breakdown"][index]["max_score"] for index in range(5)) == 100


def test_platform_job_recommends_server_infra_resume() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        posting = _job(
            session,
            title="Platform Engineer (DevOps)",
            tasks=["AWS 인프라 운영과 배포 자동화, 모니터링 체계를 구축합니다."],
            requirements=["Docker, AWS, CI/CD 운영 경험"],
        )
        result = build_resume_recommendation(
            posting,
            default_candidate_profile(),
            fit_score=77,
            missing_skills=[],
        )

    assert result["recommended_id"] == "server_infra"


def test_technical_product_job_recommends_product_builder_resume() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        posting = _job(
            session,
            title="Product Owner · 초기 팀원",
            tasks=["사용자 문제 정의부터 핵심 지표 수립, 실험과 제품 구현까지 주도합니다."],
            requirements=["Python 기반 프로토타입을 직접 구현할 수 있는 분"],
        )
        result = build_resume_recommendation(
            posting,
            default_candidate_profile(),
            fit_score=74,
            missing_skills=[],
        )

    assert result["recommended_id"] == "product_builder"


def test_job_detail_exposes_ranked_resumes_and_local_pdf(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    pdf_path = resume_dir / "01_Python_서버_백엔드_이력서.local.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

    with Session(engine) as session:
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add(profile)
        posting = _job(
            session,
            title="Python Backend Engineer",
            tasks=["FastAPI로 REST API를 개발합니다."],
            requirements=["Python FastAPI 실무 경험"],
        )
        score_jobs(session)
        session.commit()
        job_id = posting.id
        score = session.scalar(select(JobScore))
        assert score is not None
        assert score.recommended_resume_version == "python_backend"

    def override_get_db():
        with Session(engine) as session:
            yield session

    settings = Settings(ai_enabled=False, resume_directory=str(resume_dir))
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        detail = client.get(f"/api/jobs/{job_id}")
        assert detail.status_code == 200
        recommendation = detail.json()["resume_recommendation"]
        assert recommendation["recommended_id"] == "python_backend"
        assert detail.json()["recommendation_grade"] in {"최우선", "추천", "도전 지원"}
        assert detail.json()["backend_work_share"] >= 50
        assert detail.json()["java_spring_status"] == "아님"
        assert 2 <= len(detail.json()["recommendation_reasons"]) <= 4
        assert detail.json()["recommended_resume_type"] == "Python 백엔드 이력서"
        assert len(recommendation["resumes"]) == 4
        backend_resume = next(
            item for item in recommendation["resumes"] if item["id"] == "python_backend"
        )
        assert backend_resume["available"] is True
        assert backend_resume["file_url"] == "/api/resumes/python_backend/file"

        catalog = client.get("/api/resumes")
        assert catalog.status_code == 200
        assert len(catalog.json()) == 4
        file_response = client.get("/api/resumes/python_backend/file")
        assert file_response.status_code == 200
        assert file_response.headers["content-type"] == "application/pdf"
        assert "no-store" in file_response.headers["cache-control"]
        assert client.get("/api/resumes/unknown/file").status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
