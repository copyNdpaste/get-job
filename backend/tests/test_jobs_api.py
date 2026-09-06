from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.crawler.adapters import POLICIES, get_adapter
from app.crawler.domain import CollectedJob
from app.crawler.hiring_process import analyze_hiring_process
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Application, CandidateProfile, CrawlRun, JobPosting, JobScore, JobSource
from app.profile_data import default_candidate_profile
from app.scoring import score_jobs

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_jobs_can_be_listed_filtered_and_compared() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        for source_name, url in (
            ("jumpit", "https://jumpit.saramin.co.kr/position/52642030"),
            ("rallit", "https://www.rallit.com/positions/4279/server-developer"),
        ):
            source = JobSource(
                name=source_name,
                base_url=POLICIES[source_name].base_url,
                crawler_type=POLICIES[source_name].collection_mode,
            )
            session.add(source)
            session.flush()
            html = (FIXTURE_DIR / f"{source_name}_detail.html").read_text(encoding="utf-8")
            upsert_collected_job(session, source, get_adapter(source_name).parse_detail(html, url))
        jumpit_source = session.scalar(select(JobSource).where(JobSource.name == "jumpit"))
        jumpit_job = session.scalar(
            select(JobPosting).join(JobSource).where(JobSource.name == "jumpit")
        )
        rallit_job = session.scalar(
            select(JobPosting).join(JobSource).where(JobSource.name == "rallit")
        )
        assert jumpit_source is not None
        assert jumpit_job is not None
        assert rallit_job is not None
        now = datetime.now(UTC)
        jumpit_job.first_seen_at = now - timedelta(days=1)
        jumpit_job.posted_at = now - timedelta(days=60)
        rallit_job.first_seen_at = now - timedelta(days=10)
        rallit_job.posted_at = now - timedelta(hours=1)
        known_deadline = datetime(2099, 1, 15, tzinfo=UTC)
        jumpit_job.deadline_at = known_deadline
        run = CrawlRun(
            source_id=jumpit_source.id,
            started_at=jumpit_job.first_seen_at - timedelta(seconds=1),
            finished_at=datetime.now(UTC) + timedelta(seconds=1),
            status="succeeded",
            pages_visited=1,
            jobs_found=1,
            jobs_created=1,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=False)
    try:
        client = TestClient(app)
        response = client.get("/api/jobs", params={"limit": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {item["source"] for item in body["items"]} == {"jumpit", "rallit"}
        assert all(item["is_favorite"] is False for item in body["items"])
        jumpit_item = next(item for item in body["items"] if item["source"] == "jumpit")
        assert jumpit_item["deadline_at"].startswith("2099-01-15T")

        recently_collected = client.get(
            "/api/jobs",
            params={"collected_within_days": 7, "sort": "collected"},
        ).json()
        assert recently_collected["total"] == 1
        assert recently_collected["items"][0]["source"] == "jumpit"
        assert client.get("/api/jobs/stats").json()["new_last_7_days"] == 1

        recently_posted_by_fit = client.get(
            "/api/jobs",
            params={"posted_within_days": 30, "sort": "fit"},
        ).json()
        assert recently_posted_by_fit["total"] == 1
        assert recently_posted_by_fit["items"][0]["source"] == "rallit"
        assert client.get("/api/jobs", params={"posted_within_days": 366}).status_code == 422

        favorite_id = body["items"][0]["id"]
        favorited = client.patch(f"/api/jobs/{favorite_id}/favorite", json={"is_favorite": True})
        assert favorited.status_code == 200
        assert favorited.json() == {"job_id": favorite_id, "is_favorite": True}
        favorites = client.get("/api/jobs", params={"favorite_only": True}).json()
        assert favorites["total"] == 1
        assert favorites["items"][0]["id"] == favorite_id
        assert client.get("/api/jobs/stats").json()["favorite"] == 1
        favorite_item = next(
            item for item in client.get("/api/jobs").json()["items"] if item["id"] == favorite_id
        )
        assert favorite_item["is_favorite"] is True
        assert client.get(f"/api/jobs/{favorite_id}").json()["is_favorite"] is True

        unfavorited = client.patch(f"/api/jobs/{favorite_id}/favorite", json={"is_favorite": False})
        assert unfavorited.status_code == 200
        assert unfavorited.json() == {"job_id": favorite_id, "is_favorite": False}
        assert client.get("/api/jobs", params={"favorite_only": True}).json()["total"] == 0
        assert client.get("/api/jobs/stats").json()["favorite"] == 0
        assert (
            client.patch("/api/jobs/999999/favorite", json={"is_favorite": True}).status_code == 404
        )

        applied = client.patch(f"/api/jobs/{favorite_id}/application", json={"status": "applied"})
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"
        assert applied.json()["applied_at"] is not None
        applied_jobs = client.get(
            "/api/jobs",
            params={"applied_only": True, "active_only": False, "include_hidden": True},
        ).json()
        assert applied_jobs["total"] == 1
        assert applied_jobs["items"][0]["id"] == favorite_id
        assert applied_jobs["items"][0]["application_status"] == "applied"
        assert client.get("/api/jobs/stats").json()["applied"] == 1

        advanced = client.patch(
            f"/api/jobs/{favorite_id}/application", json={"status": "interview"}
        )
        assert advanced.status_code == 200
        assert client.get("/api/jobs", params={"applied_only": True}).json()["total"] == 1
        with Session(engine) as session:
            application = session.scalar(
                select(Application).where(Application.job_posting_id == favorite_id)
            )
            assert application is not None
            first_applied_at = application.applied_at

        reset = client.patch(
            f"/api/jobs/{favorite_id}/application", json={"status": "not_reviewed"}
        )
        assert reset.status_code == 200
        assert reset.json()["status"] == "not_reviewed"
        assert reset.json()["applied_at"] == first_applied_at.isoformat()
        assert client.get("/api/jobs", params={"applied_only": True}).json()["total"] == 0
        assert client.get("/api/jobs/stats").json()["applied"] == 0
        assert (
            client.patch("/api/jobs/999999/application", json={"status": "applied"}).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/jobs/{favorite_id}/application", json={"status": "invalid"}
            ).status_code
            == 422
        )

        filtered = client.get("/api/jobs", params={"tech": "Python"}).json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["source"] == "jumpit"

        detail = client.get(f"/api/jobs/{body['items'][0]['id']}")
        assert detail.status_code == 200
        assert "main_tasks" in detail.json()
        assert "requirements" in detail.json()
        assert "score_breakdown" in detail.json()
        assert "candidate_summary" in detail.json()
        assert "deadline_at" in detail.json()
        assert "company_summary" in detail.json()
        assert "company_profile" in detail.json()
        assert detail.json()["company_summary"]["profitability_status"] == "undisclosed"

        stats = client.get("/api/jobs/stats").json()
        assert stats["total"] == 2
        assert stats["hidden"] == 0
        assert stats["source_counts"] == {"jumpit": 1, "rallit": 1}

        crawl_results = client.get(f"/api/crawl/runs/{run_id}/results")
        assert crawl_results.status_code == 200
        assert crawl_results.json()[0]["title"] == "백엔드 개발자 - python, Django"
        assert crawl_results.json()[0]["status"] == "created"

        hidden_id = body["items"][0]["id"]
        hidden = client.patch("/api/jobs/visibility", json={"job_ids": [hidden_id], "hidden": True})
        assert hidden.status_code == 200
        assert hidden.json() == {"updated": 1, "hidden": True}
        assert client.get("/api/jobs").json()["total"] == 1

        hidden_only = client.get(
            "/api/jobs", params={"hidden_only": True, "active_only": False}
        ).json()
        assert hidden_only["total"] == 1
        assert hidden_only["items"][0]["id"] == hidden_id
        assert hidden_only["items"][0]["is_hidden"] is True

        with_hidden = client.get("/api/jobs", params={"include_hidden": True}).json()
        assert with_hidden["total"] == 2
        hidden_item = next(item for item in with_hidden["items"] if item["id"] == hidden_id)
        assert hidden_item["is_hidden"] is True
        assert client.get("/api/jobs/stats").json()["hidden"] == 1

        restored = client.patch(
            "/api/jobs/visibility", json={"job_ids": [hidden_id], "hidden": False}
        )
        assert restored.status_code == 200
        assert client.get("/api/jobs").json()["total"] == 2
        assert (
            client.get("/api/jobs", params={"hidden_only": True, "active_only": False}).json()[
                "total"
            ]
            == 0
        )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_jobs_can_filter_experience_years_and_excluded_technologies() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    jobs = (
        ("java-intern", "Java Spring 인턴", ["Java", "Spring"], "인턴", None),
        (
            "typescript-career",
            "TypeScript 백엔드",
            ["JavaScript", "TypeScript"],
            "경력 2~5년",
            None,
        ),
        ("python-senior", "Python 시니어", ["Python", "Django"], "경력 7년 이상", None),
        ("entry-ai", "신입 AI 엔지니어", ["Python", "AI"], "신입", None),
        ("open-backend", "경력무관 백엔드", ["Node.js"], "경력무관", None),
        ("spring-api", "Spring API 개발자", ["Spring Boot"], "경력 1년", None),
        (
            "wanted-intern",
            "[인턴] Backend Engineer",
            ["Python"],
            "신입-경력 1년",
            "intern",
        ),
    )
    with Session(engine) as session:
        source = JobSource(
            name="jumpit",
            base_url=POLICIES["jumpit"].base_url,
            crawler_type="http",
        )
        session.add(source)
        session.flush()
        for external_id, title, tech_stack, experience_text, employment_type in jobs:
            upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name="jumpit",
                    external_job_id=external_id,
                    company_name=f"{external_id} 회사",
                    title=title,
                    url=f"https://jumpit.saramin.co.kr/position/{external_id}",
                    description_raw=title,
                    description_text=title,
                    tech_stack=tech_stack,
                    experience_text=experience_text,
                    employment_type=employment_type,
                ),
            )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        java_only = client.get("/api/jobs", params={"tech": "Java"}).json()
        assert java_only["total"] == 1
        assert java_only["items"][0]["title"] == "Java Spring 인턴"

        without_java = client.get("/api/jobs", params={"exclude_tech": "Java"}).json()
        assert without_java["total"] == 6
        assert "TypeScript 백엔드" in {item["title"] for item in without_java["items"]}

        without_spring = client.get("/api/jobs", params={"exclude_tech": "Spring"}).json()
        assert without_spring["total"] == 5
        assert not any("Spring" in item["title"] for item in without_spring["items"])

        multi_tech = client.get("/api/jobs", params=[("tech", "Java"), ("tech", "Python")]).json()
        assert {item["title"] for item in multi_tech["items"]} == {
            "Java Spring 인턴",
            "Python 시니어",
            "신입 AI 엔지니어",
            "[인턴] Backend Engineer",
        }

        interns = client.get("/api/jobs", params={"experience": "intern"}).json()
        assert {item["title"] for item in interns["items"]} == {
            "Java Spring 인턴",
            "[인턴] Backend Engineer",
        }

        early_career = client.get(
            "/api/jobs",
            params=[("experience", "entry"), ("experience", "no_experience")],
        ).json()
        assert {item["title"] for item in early_career["items"]} == {
            "신입 AI 엔지니어",
            "경력무관 백엔드",
        }

        entry_only = client.get("/api/jobs", params={"experience": "entry"}).json()
        assert [item["title"] for item in entry_only["items"]] == ["신입 AI 엔지니어"]

        middle_career = client.get(
            "/api/jobs",
            params={"experience": "career", "min_years": 3, "max_years": 6},
        ).json()
        assert [item["title"] for item in middle_career["items"]] == ["TypeScript 백엔드"]

        senior = client.get("/api/jobs", params={"experience": "career", "min_years": 8}).json()
        assert [item["title"] for item in senior["items"]] == ["Python 시니어"]

        invalid_range = client.get("/api/jobs", params={"min_years": 8, "max_years": 3})
        assert invalid_range.status_code == 400
        assert client.get("/api/jobs", params={"experience": "unknown"}).status_code == 400
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_jobs_can_filter_structured_hiring_process() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    jobs = (
        (
            "coding-two",
            "코딩테스트와 면접 2회",
            ["서류 → 코딩테스트 → 1차 실무 면접 → 2차 컬처 면접"],
        ),
        ("no-coding-one", "코딩테스트 없이 면접 1회", ["코딩테스트 없이 → 면접 1회"]),
        ("no-interview", "면접 없는 전형", ["코딩테스트 없음 → 면접 없음"]),
        ("unknown", "채용 절차 미기재", []),
    )
    with Session(engine) as session:
        source = JobSource(
            name="jumpit",
            base_url=POLICIES["jumpit"].base_url,
            crawler_type="http",
        )
        session.add(source)
        session.flush()
        for external_id, title, process_text in jobs:
            process = analyze_hiring_process(process_text)
            upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name="jumpit",
                    external_job_id=external_id,
                    company_name=f"{external_id} 회사",
                    title=title,
                    url=f"https://jumpit.saramin.co.kr/position/{external_id}",
                    description_raw=title,
                    description_text=title,
                    hiring_process=list(process.steps),
                    has_coding_test=process.has_coding_test,
                    interview_count=process.interview_count,
                ),
            )
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        coding_test = client.get("/api/jobs", params={"coding_test": "yes"}).json()
        assert [item["title"] for item in coding_test["items"]] == ["코딩테스트와 면접 2회"]
        assert coding_test["items"][0]["has_coding_test"] is True
        assert coding_test["items"][0]["interview_count"] == 2
        assert coding_test["items"][0]["hiring_process"][1] == "코딩테스트"

        coding_or_unknown = client.get(
            "/api/jobs",
            params=[("coding_test", "yes"), ("coding_test", "unknown")],
        ).json()
        assert {item["title"] for item in coding_or_unknown["items"]} == {
            "코딩테스트와 면접 2회",
            "채용 절차 미기재",
        }

        one_interview = client.get("/api/jobs", params={"interview_count": "one"}).json()
        assert [item["title"] for item in one_interview["items"]] == ["코딩테스트 없이 면접 1회"]

        two_interviews = client.get("/api/jobs", params={"interview_count": "two_plus"}).json()
        assert [item["title"] for item in two_interviews["items"]] == ["코딩테스트와 면접 2회"]

        one_or_two_interviews = client.get(
            "/api/jobs",
            params=[("interview_count", "one"), ("interview_count", "two_plus")],
        ).json()
        assert {item["title"] for item in one_or_two_interviews["items"]} == {
            "코딩테스트와 면접 2회",
            "코딩테스트 없이 면접 1회",
        }

        no_interview = client.get("/api/jobs", params={"interview_count": "none"}).json()
        assert [item["title"] for item in no_interview["items"]] == ["면접 없는 전형"]

        unknown = client.get(
            "/api/jobs",
            params={"coding_test": "unknown", "interview_count": "unknown"},
        ).json()
        assert [item["title"] for item in unknown["items"]] == ["채용 절차 미기재"]

        assert client.get("/api/jobs", params={"coding_test": "maybe"}).status_code == 400
        assert client.get("/api/jobs", params={"interview_count": "three"}).status_code == 400
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_crawl_request_returns_immediately_and_schedules_background_work(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            JobSource(
                name="jumpit",
                base_url=POLICIES["jumpit"].base_url,
                crawler_type=POLICIES["jumpit"].collection_mode,
            )
        )
        session.commit()

    scheduled: list[tuple[int, str]] = []

    def fake_schedule(run_id, source_name, _payload, _settings) -> None:
        scheduled.append((run_id, source_name))

    monkeypatch.setattr("app.api.crawl.schedule_collection", fake_schedule)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/crawl/jumpit",
            json={"max_jobs": 5, "urls": [], "headless": True},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "running"
        assert scheduled == [(response.json()["id"], "jumpit")]

        runs = client.get("/api/crawl/runs").json()
        assert runs[0]["source"] == "jumpit"
        assert runs[0]["status"] == "running"

        with Session(engine) as session:
            orphaned = session.get(CrawlRun, response.json()["id"])
            assert orphaned is not None
            orphaned.started_at = datetime.now(UTC) - timedelta(minutes=1)
            session.commit()
        recovered = client.get("/api/crawl/runs").json()
        assert recovered[0]["status"] == "failed"
        assert "백엔드 재시작" in recovered[0]["error"]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_jobplanet_manual_collection_schedules_without_endpoint_config(
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            JobSource(
                name="jobplanet",
                base_url="https://www.jobplanet.co.kr",
                crawler_type="public_json",
            )
        )
        session.commit()

    scheduled: list[tuple[int, str]] = []

    def fake_schedule(run_id, source_name, _payload, _settings) -> None:
        scheduled.append((run_id, source_name))

    monkeypatch.setattr("app.api.crawl.schedule_collection", fake_schedule)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=False)
        client = TestClient(app)
        started = client.post(
            "/api/crawl/jobplanet",
            json={"max_jobs": 10, "urls": [], "headless": False},
        )

        assert started.status_code == 202
        assert started.json()["source"] == "jobplanet"
        assert scheduled == [(started.json()["id"], "jobplanet")]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_recommendation_chat_filters_database_jobs_by_natural_language() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(
            name="jumpit",
            base_url=POLICIES["jumpit"].base_url,
            crawler_type="http",
        )
        session.add_all(
            [source, CandidateProfile(name="기본 후보자", profile_json=default_candidate_profile())]
        )
        session.flush()
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jumpit",
                external_job_id="python-chat",
                company_name="파이썬회사",
                title="Python Django 백엔드 개발자",
                url="https://jumpit.saramin.co.kr/position/100",
                description_raw="Python Django REST API AWS",
                description_text="Python Django REST API AWS",
                requirements=["Python Django REST API 실무 경험"],
                tech_stack=["Python", "Django", "REST API", "AWS"],
                experience_text="경력 3년 이상",
            ),
        )
        upsert_collected_job(
            session,
            source,
            CollectedJob(
                source_name="jumpit",
                external_job_id="java-chat",
                company_name="자바회사",
                title="Java Spring 백엔드 개발자",
                url="https://jumpit.saramin.co.kr/position/101",
                description_raw="Java Spring",
                description_text="Java Spring backend",
                requirements=["Java Spring 실무 경험"],
                tech_stack=["Java", "Spring"],
                experience_text="경력 3년 이상",
            ),
        )
        score_jobs(session)
        for score in session.scalars(select(JobScore)).all():
            job = session.get(JobPosting, score.job_posting_id)
            if job and "Python" in job.title:
                score.total_fit_score = 88
                score.application_value_score = 82
            else:
                score.total_fit_score = 45
                score.application_value_score = 35
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=False)
    try:
        client = TestClient(app)
        high_fit = client.get("/api/jobs", params={"min_fit_score": 80}).json()
        assert [item["title"] for item in high_fit["items"]] == ["Python Django 백엔드 개발자"]
        high_value = client.get("/api/jobs", params={"min_value_score": 80}).json()
        assert [item["title"] for item in high_value["items"]] == ["Python Django 백엔드 개발자"]
        assert client.get("/api/jobs", params={"min_fit_score": 101}).status_code == 422

        response = client.post(
            "/api/recommendations/chat",
            json={"message": "Java는 빼고 Python Django 백엔드 공고 추천해줘", "limit": 5},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"]
        assert body["items"][0]["title"] == "Python Django 백엔드 개발자"
        assert body["interpreted_filters"]["excluded_technologies"] == ["Java"]
        assert body["items"][0]["why"]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
