from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.deduplication import refresh_duplicate_groups
from app.main import app
from app.models import Application, Company, JobPosting, JobSource


def _posting(
    source: JobSource, company: Company, external_id: str, title: str, url: str
) -> JobPosting:
    now = datetime.now(UTC)
    return JobPosting(
        source_id=source.id,
        external_job_id=external_id,
        company_id=company.id,
        title=title,
        normalized_title=title.casefold(),
        url=url,
        canonical_url=url,
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        content_hash=(external_id * 64)[:64],
    )


def test_same_company_and_normalized_title_are_grouped_across_sources() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        wanted = JobSource(name="wanted", base_url="https://www.wanted.co.kr", crawler_type="api")
        groupby = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="api")
        company = Company(name="예시 회사", normalized_name="예시회사")
        session.add_all([wanted, groupby, company])
        session.flush()
        wanted_job = _posting(
            wanted,
            company,
            "1",
            "[제품] Tech - Backend Engineer",
            "https://www.wanted.co.kr/wd/1",
        )
        groupby_job = _posting(
            groupby,
            company,
            "2",
            "[제품] Tech- Backend Engineer",
            "https://groupby.kr/positions/2",
        )
        session.add_all([wanted_job, groupby_job])
        session.flush()
        session.add(Application(job_posting_id=wanted_job.id, status="rejected"))
        session.flush()

        summary = refresh_duplicate_groups(session)

        assert summary.groups == 1
        assert summary.grouped_postings == 2
        assert wanted_job.duplicate_group_id == groupby_job.duplicate_group_id
        assert wanted_job.is_primary_posting is True
        assert groupby_job.is_primary_posting is False
        assert wanted_job.duplicate_reason


def test_same_title_from_one_source_is_not_cross_source_duplicate() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://www.wanted.co.kr", crawler_type="api")
        company = Company(name="예시 회사", normalized_name="예시회사")
        session.add_all([source, company])
        session.flush()
        session.add_all(
            [
                _posting(source, company, "3", "Backend Engineer", "https://www.wanted.co.kr/wd/3"),
                _posting(source, company, "4", "Backend Engineer", "https://www.wanted.co.kr/wd/4"),
            ]
        )
        session.flush()

        summary = refresh_duplicate_groups(session)

        assert summary.groups == 0
        assert all(session.scalars(select(JobPosting.is_primary_posting)))


def test_similar_backend_titles_and_company_legal_forms_are_grouped() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        saramin = JobSource(
            name="saramin", base_url="https://www.saramin.co.kr", crawler_type="api"
        )
        jobkorea = JobSource(
            name="jobkorea", base_url="https://www.jobkorea.co.kr", crawler_type="api"
        )
        saramin_company = Company(name="(주)예시랩", normalized_name="주예시랩")
        jobkorea_company = Company(name="예시랩 주식회사", normalized_name="예시랩주식회사")
        session.add_all([saramin, jobkorea, saramin_company, jobkorea_company])
        session.flush()
        left = _posting(
            saramin,
            saramin_company,
            "similar-1",
            "[플레이오] Python 백엔드 개발자(경력)",
            "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1",
        )
        left.tech_stack = ["Python", "FastAPI"]
        left.experience_text = "경력 3년 이상"
        right = _posting(
            jobkorea,
            jobkorea_company,
            "similar-2",
            "백엔드 엔지니어 (Python)",
            "https://www.jobkorea.co.kr/Recruit/GI_Read/2",
        )
        right.tech_stack = ["Python", "FastAPI"]
        right.experience_text = "경력 3~8년"
        session.add_all([left, right])
        session.flush()

        summary = refresh_duplicate_groups(session)

        assert summary.groups == 1
        assert summary.grouped_postings == 2
        assert left.duplicate_group_id == right.duplicate_group_id
        assert left.duplicate_reason == "동일 회사 · 유사 포지션명·경력 조건 · 복수 공개 채용 소스"


def test_jobplanet_posting_is_grouped_with_existing_source_posting() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        jobplanet = JobSource(
            name="jobplanet",
            base_url="https://www.jobplanet.co.kr",
            crawler_type="public_json",
        )
        wanted = JobSource(
            name="wanted",
            base_url="https://www.wanted.co.kr",
            crawler_type="api",
        )
        jobplanet_company = Company(name="크림(주)", normalized_name="크림주")
        wanted_company = Company(name="크림(KREAM)", normalized_name="크림kream")
        session.add_all([jobplanet, wanted, jobplanet_company, wanted_company])
        session.flush()
        jobplanet_job = _posting(
            jobplanet,
            jobplanet_company,
            "1525304",
            "Backend Engineer 모집",
            "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D=1525304",
        )
        wanted_job = _posting(
            wanted,
            wanted_company,
            "9001",
            "크림(KREAM) - Backend Engineer",
            "https://www.wanted.co.kr/wd/9001",
        )
        session.add_all([jobplanet_job, wanted_job])
        session.flush()

        summary = refresh_duplicate_groups(session)

        assert summary.groups == 1
        assert summary.grouped_postings == 2
        assert jobplanet_job.duplicate_group_id == wanted_job.duplicate_group_id


def test_conflicting_seniority_or_role_is_not_grouped() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = JobSource(name="saramin", base_url="https://www.saramin.co.kr", crawler_type="api")
        second = JobSource(
            name="jobkorea", base_url="https://www.jobkorea.co.kr", crawler_type="api"
        )
        company = Company(name="예시 회사", normalized_name="예시회사")
        session.add_all([first, second, company])
        session.flush()
        session.add_all(
            [
                _posting(
                    first,
                    company,
                    "junior",
                    "Junior Python Backend Engineer",
                    "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=3",
                ),
                _posting(
                    second,
                    company,
                    "senior",
                    "Senior Python Backend Engineer",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/4",
                ),
                _posting(
                    second,
                    company,
                    "data",
                    "Python Data Engineer",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/5",
                ),
            ]
        )
        session.flush()

        summary = refresh_duplicate_groups(session)

        assert summary.groups == 0
        assert all(session.scalars(select(JobPosting.is_primary_posting)))


def test_rejected_duplicate_bundle_is_excluded_but_retained_in_application_history() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        wanted = JobSource(name="wanted", base_url="https://www.wanted.co.kr", crawler_type="api")
        groupby = JobSource(name="groupby", base_url="https://groupby.kr", crawler_type="api")
        company = Company(name="예시 회사", normalized_name="예시회사")
        session.add_all([wanted, groupby, company])
        session.flush()
        wanted_job = _posting(
            wanted,
            company,
            "5",
            "[제품] Tech - LLM Engineer",
            "https://www.wanted.co.kr/wd/5",
        )
        groupby_job = _posting(
            groupby,
            company,
            "6",
            "[제품] Tech- LLM Engineer",
            "https://groupby.kr/positions/6",
        )
        session.add_all([wanted_job, groupby_job])
        session.flush()
        session.add(Application(job_posting_id=wanted_job.id, status="rejected"))
        refresh_duplicate_groups(session)
        session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        assert client.get("/api/jobs", params={"active_only": False}).json()["total"] == 0

        history = client.get(
            "/api/jobs",
            params={"applied_only": True, "active_only": False, "include_hidden": True},
        ).json()
        assert history["total"] == 1
        assert history["items"][0]["application_status"] == "rejected"
        assert history["items"][0]["duplicate_count"] == 2
        assert {item["source"] for item in history["items"][0]["duplicate_postings"]} == {
            "wanted",
            "groupby",
        }
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
