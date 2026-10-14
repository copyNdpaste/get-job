from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.crawler.adapters import POLICIES, get_adapter
from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.models import CandidateProfile, JobPosting, JobScore, JobSource
from app.profile_data import default_candidate_profile
from app.scoring import (
    JOBPLANET_MAX_EXCLUDED_FIT_SCORE,
    SCORING_VERSION,
    _experience_eligibility,
    score_jobs,
)


def test_experience_range_uses_the_lowest_accepted_level() -> None:
    score, risk = _experience_eligibility("미들 (4~8년), 주니어 (1~3년)", 6)

    assert score == 95
    assert risk is None


def test_collected_job_is_scored_against_default_profile() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    fixture = Path(__file__).parent / "fixtures" / "wanted_detail.html"

    with Session(engine) as session:
        source = JobSource(
            name="wanted",
            base_url=POLICIES["wanted"].base_url,
            crawler_type="browser_url",
        )
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        job = get_adapter("wanted").parse_detail(
            fixture.read_text(encoding="utf-8"), "https://www.wanted.co.kr/wd/287697"
        )
        upsert_collected_job(session, source, job)

        assert score_jobs(session) == 1
        score = session.scalar(select(JobScore))
        assert score is not None
        assert 0 <= score.total_fit_score <= 100
        assert score.grade in {"S", "A", "B", "C"}
        assert score.scoring_version == SCORING_VERSION
        python_reason = next(
            reason for reason in score.matching_reasons if reason["skill"] == "Python"
        )
        assert python_reason["profile_evidence"]
        assert python_reason["job_evidence"]
        assert score.evidence_json["score_breakdown"]
        assert "필수기술 22%" in score.evidence_json["formula"]
        assert "우대·인접기술 8%" in score.evidence_json["formula"]
        assert score.evidence_json["confidence"] in {"high", "medium", "low"}


def test_incremental_scoring_only_processes_new_job_ids() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="jumpit", base_url=POLICIES["jumpit"].base_url, crawler_type="http")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        first = upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jumpit",
                external_job_id="incremental-first",
                company_name="첫 회사",
                title="Python Backend Engineer",
                url="https://jumpit.saramin.co.kr/position/1001",
                description_raw="Python FastAPI",
                description_text="Python FastAPI API development",
            ),
        )
        second = upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jumpit",
                external_job_id="incremental-second",
                company_name="둘째 회사",
                title="Python Server Engineer",
                url="https://jumpit.saramin.co.kr/position/1002",
                description_raw="Python Django",
                description_text="Python Django API development",
            ),
        )

        assert score_jobs(session, job_ids={second.job_posting_id}, skip_existing=True) == 1
        assert score_jobs(session, job_ids={first.job_posting_id}, skip_existing=True) == 1
        assert score_jobs(session, job_ids={first.job_posting_id}, skip_existing=True) == 0
        first_score = session.scalar(
            select(JobScore).where(JobScore.job_posting_id == first.job_posting_id)
        )
        assert first_score is not None
        first_score.scoring_version = "rules-v0-old"
        assert score_jobs(session, job_ids={first.job_posting_id}, skip_existing=True) == 1
        assert first_score.scoring_version == SCORING_VERSION
        assert session.scalars(select(JobScore)).all()


def test_android_job_is_deactivated_instead_of_receiving_a_high_score() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        source = JobSource(
            name="jumpit",
            base_url=POLICIES["jumpit"].base_url,
            crawler_type="http",
        )
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jumpit",
                external_job_id="54417657",
                company_name="러닝포인트",
                title="안드로이드 러닝 앱 개발자 경력 (1~3년)",
                url="https://jumpit.saramin.co.kr/position/54417657",
                description_raw="Android Kotlin REST API Firebase",
                description_text="Android Kotlin REST API Firebase",
                tech_stack=["REST API"],
                experience_text="경력 1~3년",
            ),
        )

        assert score_jobs(session) == 1
        posting = session.scalar(select(JobPosting))
        assert posting is not None
        assert posting.is_active is False


def test_jobplanet_verified_development_role_is_scored_with_source_skill_tags() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        source = JobSource(
            name="jobplanet",
            base_url="https://www.jobplanet.co.kr",
            crawler_type="public_json",
        )
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        result = upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jobplanet",
                external_job_id="verified-devops",
                company_name="Synthetic Platform Labs",
                title="Infra/DevOps/SRE 개발자 모집",
                url=(
                    "https://www.jobplanet.co.kr/job/search?"
                    "posting_ids%5B%5D=verified-devops"
                ),
                description_raw='{"job_id":"verified-devops"}',
                description_text=(
                    "Infra DevOps SRE 개발자 백엔드 개발 소프트웨어 개발 "
                    "Python Node.js NestJS Go Docker Kubernetes AWS"
                ),
                requirements=["Python, Node.js, NestJS 또는 Go 기반 서비스 개발 경험"],
                tech_stack=[
                    "Python",
                    "Node.js",
                    "NestJS",
                    "Go",
                    "Docker",
                    "Kubernetes",
                    "AWS",
                ],
                experience_text="경력 3년 이상",
            ),
        )
        posting = session.get(JobPosting, result.job_posting_id)
        assert posting is not None
        posting.is_active = False

        assert score_jobs(
            session,
            job_ids={result.job_posting_id},
            skip_existing=False,
        ) == 1
        score = session.scalar(
            select(JobScore).where(JobScore.job_posting_id == result.job_posting_id)
        )
        assert posting.is_active is False
        assert score is not None
        assert score.grade in {"S", "A", "B", "C"}
        evaluated_skills = {
            reason["skill"] for reason in [*score.matching_reasons, *score.missing_skills]
        }
        assert {"Python", "Node.js", "NestJS", "Go"}.issubset(evaluated_skills)
        for check in (
            {"status": "closed", "reason": "http_410"},
            {"status": "unknown", "reason": "previously_inactive_not_reopened"},
        ):
            posting.is_active = False
            posting.availability_check = check
            score_jobs(session, job_ids={posting.id}, skip_existing=True)
            assert posting.is_active is False

        upsert_collected_job(session, source, CollectedJob(
            source_name="jobplanet", external_job_id="verified-devops",
            company_name="Synthetic Platform Labs", title=posting.title, url=posting.url,
            description_raw=posting.description_raw or "",
            description_text=posting.description_text or "",
            tech_stack=posting.tech_stack,
        ))
        assert posting.availability_check is None
        score_jobs(session, job_ids={posting.id}, skip_existing=True)
        assert posting.is_active is True



def test_jobplanet_fit_score_at_cutoff_is_deactivated_when_score_is_reused() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        sources = {
            name: JobSource(name=name, base_url=f"https://{name}.example.test", crawler_type="test")
            for name in ("jobplanet", "wanted")
        }
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([*sources.values(), profile])
        session.flush()

        posting_ids: dict[str, int] = {}
        for name, source in sources.items():
            result = upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name=name,
                    external_job_id=f"{name}-cutoff",
                    company_name=f"{name} Synthetic Labs",
                    title="Python Backend Engineer",
                    url=f"https://{name}.example.test/jobs/cutoff",
                    description_raw="Python FastAPI backend",
                    description_text="Python FastAPI 백엔드 개발 소프트웨어 개발",
                    requirements=["Python FastAPI 실무 경험"],
                    tech_stack=["Python", "FastAPI"],
                    experience_text="경력 3년 이상",
                ),
            )
            posting_ids[name] = result.job_posting_id

        assert score_jobs(session) == 2
        for score in session.scalars(select(JobScore)):
            score.total_fit_score = JOBPLANET_MAX_EXCLUDED_FIT_SCORE
            score.scoring_version = SCORING_VERSION
            score.job_posting.is_active = True
        session.flush()

        assert score_jobs(session, skip_existing=True) == 0
        jobplanet = session.get(JobPosting, posting_ids["jobplanet"])
        wanted = session.get(JobPosting, posting_ids["wanted"])
        assert jobplanet is not None and jobplanet.is_active is False
        assert wanted is not None and wanted.is_active is True


def test_model_training_ai_job_is_capped_by_explicit_resume_gaps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="ml-1",
                company_name="모델랩",
                title="AI 엔지니어 (모델 학습)",
                url="https://groupby.kr/positions/999",
                description_raw="PyTorch model training fine-tuning",
                description_text="PyTorch model training fine-tuning TensorFlow",
                requirements=["PyTorch 기반 모델 학습 및 fine-tuning 실무 경험"],
                tech_stack=["Python", "PyTorch", "TensorFlow"],
                experience_text="경력 3년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 68
        assert {gap["skill"] for gap in score.missing_skills} >= {"PyTorch"}
        assert any("상한" in risk for risk in score.risk_notes)


def test_go_required_backend_role_is_scored_as_a_growth_gap() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="go-backend-1",
                company_name="익명 Go 서버 회사",
                title="Go Backend Engineer",
                url="https://groupby.kr/positions/1000",
                description_raw="Go language PostgreSQL AWS gRPC backend",
                description_text="Go language 기반 API 서버를 PostgreSQL과 AWS에서 운영",
                requirements=["Go language 백엔드 API 개발 및 운영 경험"],
                tech_stack=["Go", "PostgreSQL", "AWS", "gRPC"],
                experience_text="경력 3년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        go_gap = next(gap for gap in score.missing_skills if gap["skill"] == "Go")
        assert go_gap["severity"] == "medium"
        assert "실무 경험이 없는" in go_gap["profile_note"]
        assert score.evidence_json["career_fit"]["transition_bonus"] == 0
        assert score.evidence_json["career_fit"]["go_transition"].startswith("보통")


def test_go_specific_required_years_cap_transition_score() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="go-backend-years-1",
                company_name="익명 Go 플랫폼 회사",
                title="Senior Go Backend Engineer",
                url="https://groupby.kr/positions/1001",
                description_raw="Go language PostgreSQL AWS backend",
                description_text="Go language 기반 고가용성 API 서버 설계와 운영",
                requirements=["Go language 백엔드 개발 실무 4년 이상"],
                tech_stack=["Go", "PostgreSQL", "AWS"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        career_fit = score.evidence_json["career_fit"]
        assert score.total_fit_score <= 58
        assert score.application_value_score <= 58
        assert career_fit["recommendation_grade"] == "비추천"
        assert career_fit["go_transition"].startswith("낮음")
        assert career_fit["go_required_years"] == 4


def test_unverified_security_qualifications_cap_braindive_like_job() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="security-saas-1",
                company_name="보안 SaaS 회사",
                title="Python 공공 SaaS 서비스 백엔드 개발자 (5년 이상)",
                url="https://wanted.co.kr/wd/security-saas-1",
                description_raw="Python MySQL AWS backend security SaaS",
                description_text="Python MySQL AWS 공공 SaaS 백엔드 보안 운영",
                requirements=[
                    "클라우드 환경에서 보안 실무 또는 백엔드 개발 경험 5년 이상",
                    "ISMS-P 또는 ISO27001 등 보안 인증의 실제 심사 대응 경험",
                    "NCP 또는 AWS 환경의 VPC 및 보안 설정 운영 경험",
                    "Python으로 서비스 로직이나 관리 도구 개발 역량",
                    "RDB(MySQL 등) 설계 및 보안 관리 경험",
                ],
                tech_stack=["Python", "MySQL", "AWS"],
                experience_text="경력 5년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 65
        assert score.application_value_score <= 65
        assert score.grade == "C"
        hard_gaps = score.evidence_json["hard_requirement_gaps"]
        assert {gap["key"] for gap in hard_gaps} >= {
            "security_certification",
            "security_audit",
            "cloud_network_security",
        }
        assert {gap["skill"] for gap in score.missing_skills} >= {
            "보안 인증 실무(ISMS-P·ISO27001·CSAP·KCMVP 등)",
            "보안 인증·감사 심사 대응",
            "클라우드 네트워크·보안 설정 운영",
        }


def test_unverified_required_server_tools_lower_and_cap_score() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(
            name="익명 후보자",
            profile_json={
                "years_experience": 6,
                "summary": "Python FastAPI 백엔드 개발자",
                "skills": {
                    "backend": ["Python", "FastAPI", "REST API"],
                    "database": ["PostgreSQL"],
                    "infra": ["AWS", "Docker"],
                    "quality": ["pytest"],
                },
                "achievements": [{"evidence": "Python FastAPI API 서비스를 AWS에 배포"}],
                "skill_gaps": {
                    "limited": [],
                    "no_professional_experience": [],
                    "none": [],
                },
            },
        )
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="server-tools-1",
                company_name="익명 서버 회사",
                title="Python Backend Engineer",
                url="https://wanted.co.kr/wd/server-tools-1",
                description_raw="Python FastAPI Celery Prometheus",
                description_text="Python FastAPI Celery Prometheus 서버 개발",
                requirements=[
                    "Python FastAPI 서버 개발 경험",
                    "Celery 작업 큐 설계 및 운영 경험",
                    "Prometheus 모니터링 구축 경험",
                ],
                tech_stack=["Python", "FastAPI", "Celery", "Prometheus"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert {"Celery", "Prometheus"}.issubset({gap["skill"] for gap in score.missing_skills})
        assert score.total_fit_score <= 72
        assert score.evidence_json["rank_factors"]["strict_required_gaps"] == [
            "Celery",
            "Prometheus",
        ]


def test_java_spring_only_backend_is_deactivated_without_scoring() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="java-1",
                company_name="자바회사",
                title="Backend Engineer",
                url="https://wanted.co.kr/wd/1",
                description_raw="Java Spring backend",
                description_text="Java Spring backend REST API",
                requirements=["Java와 Spring Boot 실무 경험 필수"],
                tech_stack=["Java", "Spring", "REST API"],
                experience_text="경력 3년 이상",
            ),
        )

        score_jobs(session)
        posting = session.scalar(select(JobPosting))
        score = session.scalar(select(JobScore))

        assert posting is not None
        assert posting.is_active is False
        assert score is None


def test_python_technical_product_owner_is_scored_with_hybrid_role_cap() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="technical-po-1",
                company_name="익명 프로덕트 회사",
                title="Product Owner (초기 팀원)",
                url="https://groupby.kr/positions/technical-po-1",
                description_raw="Python AI Product Owner full-stack",
                description_text=(
                    "Python 기반 AI 활용 및 개발 전문성으로 실험 환경 세팅부터 실행까지 풀스택 담당"
                ),
                main_tasks=[
                    "프로덕트 목표와 핵심 지표 수립",
                    "실험 환경 세팅과 풀스택 구현",
                ],
                requirements=["문제 정의부터 실행까지 주도할 수 있는 분"],
                tech_stack=["Python"],
                experience_text="경력 무관",
            ),
        )

        score_jobs(session)
        posting = session.scalar(select(JobPosting))
        score = session.scalar(select(JobScore))

        assert posting is not None and posting.is_active is True
        assert score is not None
        assert score.total_fit_score <= 82
        assert "Technical PO·Product Builder" in score.labels
        assert any("하이브리드 직무" in risk for risk in score.risk_notes)


def test_ai_research_engineer_is_capped_below_server_roles() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="demoday", base_url="https://demoday.co.kr", crawler_type="http")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="demoday",
                external_job_id="research-ai-1",
                company_name="익명 연구 회사",
                title="3D AI 리서칭 엔지니어",
                url="https://demoday.co.kr/recruits/100",
                description_raw="Python computer vision model training",
                description_text="Python 컴퓨터비전 모델 논문 재현과 학습 파이프라인 연구",
                main_tasks=["최신 모델과 논문을 재현하고 학습 파이프라인에 적용"],
                requirements=["Python과 컴퓨터비전 모델 학습 경험"],
                tech_stack=["Python", "PyTorch"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 62
        assert "모델 연구·학습 AI" in score.labels


def test_llm_inference_ai_engineer_without_backend_delivery_is_capped() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="llm-inference-ai-1",
                company_name="익명 AI 회사",
                title="AI 엔지니어 구인 · 경력",
                url="https://groupby.kr/positions/llm-inference-ai-1",
                description_raw="Python Docker LLM OCR GPU model inference",
                description_text=(
                    "프롬프트 엔지니어링 기반 LLM 품질 최적화, OCR 구조화, "
                    "GPU 환경 모델 추론 파이프라인 운영"
                ),
                main_tasks=[
                    "프롬프트 엔지니어링 기반 LLM 응답 품질 최적화",
                    "OCR 결과 개선과 오픈소스 모델 실험",
                ],
                requirements=[
                    "Python 개발 경험",
                    "Docker와 GPU 환경에서 모델 추론 파이프라인 운영 경험",
                ],
                tech_stack=["Python", "FastAPI", "Docker", "LLM"],
                experience_text="경력 3년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 62
        assert "AI 모델·추론 전담" in score.labels
        assert "응용 AI 제품" not in score.labels


def test_pure_ml_engineer_is_capped_even_when_models_ship_to_production() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="pure-ml-1",
                company_name="익명 모델 회사",
                title="ML Engineer",
                url="https://www.wanted.co.kr/wd/pure-ml-1",
                description_raw="Python ML model production",
                description_text="Python 머신러닝 모델을 학습·평가하고 상용 서비스에 배포",
                main_tasks=["모델 학습, 평가와 데이터 분석 기반 성능 개선"],
                requirements=["머신러닝 실무 경험과 Python 모델링 역량"],
                tech_stack=["Python", "PyTorch"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 62
        assert "순수 모델 AI" in score.labels


def test_ai_engineer_with_explicit_backend_delivery_remains_relevant() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="ai-backend-1",
                company_name="익명 AI 서비스 회사",
                title="AI Engineer",
                url="https://groupby.kr/positions/ai-backend-1",
                description_raw="Python FastAPI AWS LLM backend",
                description_text=(
                    "LLM을 활용한 B2B 서비스의 Python FastAPI API 서버와 "
                    "백엔드 시스템을 개발하고 AWS 클라우드 인프라를 운영"
                ),
                main_tasks=["AI 서비스 백엔드 시스템과 API 서버 개발"],
                requirements=["Python FastAPI 서버와 AWS 인프라 구축 경험"],
                tech_stack=["Python", "FastAPI", "AWS", "LLM"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score > 70
        assert "AI 활용 서버·앱" in score.labels


def test_llm_ops_engineer_is_treated_as_infrastructure_not_pure_ai() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="llm-ops-1",
                company_name="익명 AI 인프라 회사",
                title="LLM Ops Engineer",
                url="https://www.wanted.co.kr/wd/llm-ops-1",
                description_raw="Python AWS Docker Kubernetes LLM serving",
                description_text="GPU 모델 서빙 인프라와 CI/CD, 관측성 체계 구축",
                main_tasks=["LLM 배포 자동화와 클라우드 인프라 운영"],
                requirements=["Docker Kubernetes AWS 운영 경험"],
                tech_stack=["Python", "AWS", "Docker", "Kubernetes", "LLM"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert "플랫폼·DevOps" in score.labels
        assert "순수 모델 AI" not in score.labels


def test_backend_collaboration_alone_does_not_make_model_role_backend_delivery() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="applied-model-1",
                company_name="익명 모델 보안 회사",
                title="Applied AI Engineer",
                url="https://www.wanted.co.kr/wd/applied-model-1",
                description_raw="Python model research",
                description_text=(
                    "경량 모델을 연구하고 평가 체계에서 성능을 개선하며 "
                    "Backend Engineer와 협업해 서빙"
                ),
                main_tasks=["모델 연구·평가와 성능 개선"],
                requirements=["Python 모델 연구 경험"],
                tech_stack=["Python", "PyTorch"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 62
        assert "AI 모델·추론 전담" in score.labels


def test_ai_video_pipeline_title_variant_is_capped_as_pure_model_ai() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="wanted",
                external_job_id="ai-video-1",
                company_name="익명 영상 회사",
                title="AI 영상 파이프라인 엔지니어",
                url="https://www.wanted.co.kr/wd/ai-video-1",
                description_raw="Python diffusion fine tuning",
                description_text="Python 영상 생성 모델 Fine-tuning과 모델 성능 검증",
                main_tasks=["영상 모델 실험과 LoRA 파인튜닝 파이프라인 구축"],
                requirements=["Diffusion 모델 구조와 이미지 처리 경험"],
                tech_stack=["Python", "PyTorch"],
                experience_text="경력 4년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 62
        assert "순수 모델 AI" in score.labels


def test_ai_owner_without_implementation_is_capped_as_strategy_role() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="browser")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="groupby",
                external_job_id="ai-owner-1",
                company_name="익명 전략 회사",
                title="AI Owner 솔루션 개발자",
                url="https://groupby.kr/positions/ai-owner-1",
                description_raw="LLM AI strategy",
                description_text=(
                    "Python LLM 전사 AI 로드맵과 솔루션 기획을 주도하고 개발팀과 소통"
                ),
                main_tasks=["전사 AX 전략과 AI 제품 기획"],
                requirements=["IT 프로덕트 매니징 5년 이상"],
                tech_stack=["Python", "LLM"],
                experience_text="경력 5년 이상",
            ),
        )

        score_jobs(session)
        score = session.scalar(select(JobScore))

        assert score is not None
        assert score.total_fit_score <= 50
        assert "AI 기획·전략" in score.labels


def test_similar_backend_jobs_receive_distinct_scores_from_evidence_depth() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://wanted.co.kr", crawler_type="api")
        profile = CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())
        session.add_all([source, profile])
        session.flush()

        jobs = [
            CollectedJob(
                source_name="wanted",
                external_job_id="evidence-rich",
                company_name="근거회사A",
                title="Python Backend Engineer",
                url="https://wanted.co.kr/wd/101",
                description_raw="Python Django PostgreSQL REST API AWS Docker Kafka test",
                description_text=(
                    "Python Django PostgreSQL REST API AWS Docker Kafka test architecture"
                ),
                main_tasks=[
                    "Python Django REST API 설계와 성능 최적화",
                    "PostgreSQL 데이터 모델링과 AWS Docker 운영",
                    "테스트 자동화와 코드 리뷰",
                ],
                requirements=[
                    "Python과 Django 실무 경험 필수",
                    "PostgreSQL 기반 서비스 개발 경험 필수",
                ],
                preferred_requirements=["Kafka 비동기 처리 경험 우대"],
                tech_stack=["Python", "Django", "PostgreSQL", "AWS", "Docker", "Kafka"],
                experience_text="경력 3~6년",
            ),
            CollectedJob(
                source_name="wanted",
                external_job_id="evidence-medium",
                company_name="근거회사B",
                title="Python Backend Engineer",
                url="https://wanted.co.kr/wd/102",
                description_raw="Python REST API",
                description_text="Python REST API 서버 개발",
                main_tasks=["Python REST API 개발"],
                requirements=["Python 실무 경험"],
                tech_stack=["Python", "REST API"],
                experience_text="경력 3년 이상",
            ),
            CollectedJob(
                source_name="wanted",
                external_job_id="evidence-sparse",
                company_name="근거회사C",
                title="Python Backend Engineer",
                url="https://wanted.co.kr/wd/103",
                description_raw="Python backend",
                description_text="Python backend",
                tech_stack=["Python"],
            ),
        ]
        for job in jobs:
            upsert_collected_job(session, source, job)

        assert score_jobs(session) == 3
        scores = {
            score.job_posting.external_job_id: score for score in session.scalars(select(JobScore))
        }

        rich = scores["evidence-rich"]
        medium = scores["evidence-medium"]
        sparse = scores["evidence-sparse"]
        assert rich.total_fit_score > medium.total_fit_score > sparse.total_fit_score
        assert len({rich.total_fit_score, medium.total_fit_score, sparse.total_fit_score}) == 3
        assert (
            rich.evidence_json["rank_factors"]["evidence_quality"]
            > sparse.evidence_json["rank_factors"]["evidence_quality"]
        )
        assert sparse.evidence_json["caps_applied"] == []
