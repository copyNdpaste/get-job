from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.crawler.adapters import POLICIES
from app.crawler.domain import CollectedJob
from app.crawler.job_profile import (
    GO_SEARCH_TERMS,
    JOB_SEARCH_TERMS,
    NODE_TYPESCRIPT_SEARCH_TERMS,
    PRODUCT_ENGINEER_SEARCH_TERMS,
)
from app.crawler.persistence import upsert_collected_job
from app.crawler.relevance import assess_relevance, extract_tech_stack
from app.db.base import Base
from app.models import CandidateProfile, JobPosting, JobScore, JobSource
from app.scoring import score_jobs


def _profile() -> dict[str, object]:
    return {
        "years_experience": 6,
        "summary": "Python이 주력이고 Node.js TypeScript 실무 경험이 있는 백엔드 엔지니어",
        "skills": {
            "backend": ["Python", "Django", "FastAPI", "Node.js", "TypeScript", "REST API"],
            "database": ["PostgreSQL", "MySQL", "Redis"],
            "infrastructure": ["AWS", "Docker", "AWS Lambda", "Serverless Framework"],
            "messaging": ["Kafka", "AWS SQS"],
            "quality": ["test automation", "GitHub Actions"],
        },
        "achievements": [
            {
                "evidence": (
                    "Python과 Node.js TypeScript API, 데이터 모델, AWS 배포 자동화를 운영한 "
                    "익명 예시 성과"
                )
            }
        ],
        "skill_gaps": {
            "limited": ["NestJS"],
            "no_professional_experience": [],
            "none": ["Spring"],
        },
        "skill_experience_years": {"Node.js": 1.5, "TypeScript": 1.5},
    }


def _scored_cases(cases: list[dict[str, object]]) -> dict[str, JobScore]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="test", base_url="https://example.test", crawler_type="test")
        profile = CandidateProfile(name="익명 후보자", profile_json=_profile())
        session.add_all([source, profile])
        session.flush()
        for index, case in enumerate(cases, start=1):
            requirements = list(case.get("requirements", []))
            preferred = list(case.get("preferred", []))
            tasks = list(
                case.get(
                    "tasks",
                    ["백엔드 API와 데이터 모델을 설계하고 AWS에서 배포·운영합니다."],
                )
            )
            text = "\n".join([str(case["title"]), *tasks, *requirements, *preferred])
            upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name="test",
                    external_job_id=str(case["id"]),
                    company_name=f"익명 회사 {index}",
                    title=str(case["title"]),
                    url=f"https://example.test/jobs/{index}",
                    description_raw=text,
                    description_text=text,
                    main_tasks=tasks,
                    requirements=requirements,
                    preferred_requirements=preferred,
                    tech_stack=list(case.get("stack", [])),
                    experience_text=str(case.get("experience", "경력 5~7년")),
                ),
            )
        score_jobs(session)
        scores = {
            score.job_posting.external_job_id: score
            for score in session.scalars(select(JobScore)).all()
        }
        for score in scores.values():
            session.expunge(score)
        return scores


def test_node_typescript_nest_backend_is_collected_and_extracted() -> None:
    description = "TypeScript와 NestJS, Fastify로 API 서버와 PostgreSQL을 개발합니다."

    decision = assess_relevance("Node 백엔드 개발자", description, "경력 2년 이상")
    stack = extract_tech_stack(f"Node 백엔드 개발자 {description}")

    assert decision.included is True
    assert {"Node.js", "TypeScript", "NestJS", "Fastify", "PostgreSQL"}.issubset(stack)


def test_python_node_mixed_job_scores_above_node_only_job() -> None:
    scores = _scored_cases(
        [
            {
                "id": "node-only",
                "title": "Node.js TypeScript Backend Engineer",
                "requirements": ["Node.js TypeScript 백엔드 실무 2년 이상"],
                "stack": ["Node.js", "TypeScript", "AWS", "PostgreSQL"],
            },
            {
                "id": "python-node",
                "title": "Python Node.js Backend Engineer",
                "requirements": ["Python 또는 Node.js 기반 API 개발 경험"],
                "stack": ["Python", "Node.js", "TypeScript", "AWS", "PostgreSQL"],
            },
        ]
    )

    assert scores["node-only"].total_fit_score >= 70
    assert scores["python-node"].total_fit_score > scores["node-only"].total_fit_score
    assert scores["python-node"].recommended_resume_version == "python_typescript_backend"


def test_node_two_years_and_optional_nestjs_are_recommended() -> None:
    scores = _scored_cases(
        [
            {
                "id": "node-two",
                "title": "Backend Engineer",
                "requirements": ["Node.js TypeScript 실무 2년 이상", "RDB와 AWS 운영 경험"],
                "preferred": ["NestJS 경험 우대 또는 입사 후 학습 가능"],
                "stack": ["Node.js", "TypeScript", "NestJS", "AWS", "PostgreSQL"],
            }
        ]
    )

    score = scores["node-two"]
    career_fit = score.evidence_json["career_fit"]
    assert career_fit["recommendation_grade"] in {"최우선", "추천", "도전 지원"}
    assert career_fit["node_typescript_transition"].startswith("높음")
    assert not any(
        gap["skill"] == "NestJS" and gap["severity"] == "high" for gap in score.missing_skills
    )


def test_nestjs_five_years_required_is_capped_and_not_recommended() -> None:
    score = _scored_cases(
        [
            {
                "id": "nest-five",
                "title": "Senior NestJS Backend Engineer",
                "requirements": ["NestJS 실무 5년 이상 필수", "TypeScript Node.js API 개발"],
                "stack": ["Node.js", "TypeScript", "NestJS"],
            }
        ]
    )["nest-five"]

    assert score.total_fit_score <= 58
    assert score.evidence_json["career_fit"]["recommendation_grade"] == "비추천"


def test_frontend_and_ambiguous_node_contexts_are_excluded() -> None:
    frontend = assess_relevance(
        "Full Stack Engineer",
        "React Next.js TypeScript UI와 화면 컴포넌트, CSS 구현이 주 업무입니다.",
    )
    blockchain = assess_relevance(
        "Blockchain Node Engineer", "validator node와 blockchain infrastructure를 운영합니다."
    )
    dom_stack = extract_tech_stack("React TypeScript DOM node와 UI 컴포넌트를 구현합니다.")

    assert frontend.included is False
    assert blockchain.included is False
    assert "Node.js" not in dom_stack


def test_java_required_is_low_but_optional_java_mixed_stack_is_kept() -> None:
    required_decision = assess_relevance(
        "Backend Engineer",
        "Java Spring Boot 필수이며 Python 마이그레이션 서비스도 운영합니다.",
    )
    scores = _scored_cases(
        [
            {
                "id": "java-required",
                "title": "Backend Engineer",
                "requirements": ["Java와 Spring Boot 실무 경험 필수", "Python 서비스 운영"],
                "stack": ["Java", "Spring", "Python", "AWS"],
            },
            {
                "id": "java-optional",
                "title": "Python Node.js Backend Engineer",
                "requirements": ["Python 또는 Node.js API 개발 경험"],
                "preferred": ["Java Spring 경험 우대"],
                "stack": ["Python", "Node.js", "Java", "Spring", "AWS"],
            },
        ]
    )

    required = scores["java-required"]
    optional = scores["java-optional"]
    assert required_decision.included is True
    assert required.total_fit_score <= 58
    assert required.evidence_json["career_fit"]["java_spring_required"] is True
    assert optional.total_fit_score > required.total_fit_score
    assert optional.evidence_json["career_fit"]["java_spring_status"] == "일부 포함 · 필수 아님"


def test_shared_search_profile_is_available_to_every_source() -> None:
    assert {"Python", "Django", "FastAPI", "Flask"}.issubset(JOB_SEARCH_TERMS)
    assert set(NODE_TYPESCRIPT_SEARCH_TERMS).issubset(JOB_SEARCH_TERMS)
    assert set(GO_SEARCH_TERMS).issubset(JOB_SEARCH_TERMS)
    assert set(PRODUCT_ENGINEER_SEARCH_TERMS).issubset(JOB_SEARCH_TERMS)
    assert all(policy.search_terms == JOB_SEARCH_TERMS for policy in POLICIES.values())
    assert any("search=Node.js" in url for url in POLICIES["demoday"].list_urls)
    assert any("search=TypeScript" in url for url in POLICIES["demoday"].list_urls)
    assert any("search=Golang" in url for url in POLICIES["demoday"].list_urls)
    assert any("search=Go+Backend" in url for url in POLICIES["demoday"].list_urls)
    assert any("search=Product+Engineer" in url for url in POLICIES["demoday"].list_urls)


def test_go_software_engineering_roles_are_collected_without_matching_english_verb() -> None:
    go_backend = assess_relevance(
        "Software Engineer",
        "Go language services, PostgreSQL, AWS, and gRPC production operations",
    )
    unrelated = assess_relevance(
        "Software Engineer",
        "Go to market planning and stakeholder communication without software development",
    )

    assert go_backend.included is True
    assert "Go" in extract_tech_stack("Go language services with gRPC")
    assert "Go" not in extract_tech_stack("Go to market planning")
    assert unrelated.included is False


def test_product_oriented_engineering_titles_are_collected() -> None:
    product_minded = assess_relevance(
        "Product-minded Engineer",
        "Python FastAPI와 TypeScript로 고객 문제를 발견하고 제품을 직접 구현·운영합니다.",
    )
    founding = assess_relevance(
        "Founding Engineer",
        "Python 백엔드 API부터 React 화면과 배포까지 제품 전체를 맡습니다.",
    )

    assert product_minded.included is True
    assert founding.included is True


def test_same_posting_found_by_multiple_keywords_is_merged() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="test", base_url="https://example.test", crawler_type="test")
        session.add(source)
        session.flush()
        for external_id, query in (("node-search", "Node.js"), ("ts-search", "TypeScript")):
            upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name="test",
                    external_job_id=external_id,
                    company_name="익명 중복 회사",
                    title="Node.js TypeScript Backend Engineer",
                    url=f"https://example.test/jobs/42?utm_keyword={query}",
                    description_raw="Node.js TypeScript API",
                    description_text="Node.js TypeScript API",
                    tech_stack=["Node.js", "TypeScript"],
                ),
            )

        assert session.scalar(select(func.count(JobPosting.id))) == 1


def test_existing_python_backend_scoring_remains_high_priority() -> None:
    score = _scored_cases(
        [
            {
                "id": "python-regression",
                "title": "Python Backend Engineer",
                "requirements": ["Python Django 또는 FastAPI 실무 경험", "PostgreSQL AWS Docker"],
                "stack": ["Python", "Django", "FastAPI", "PostgreSQL", "AWS", "Docker"],
            }
        ]
    )["python-regression"]

    assert score.total_fit_score >= 76
    assert score.evidence_json["career_fit"]["recommendation_grade"] in {"최우선", "추천"}
    assert score.recommended_resume_version == "python_backend"
