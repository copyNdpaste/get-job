import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crawler.adapters import POLICIES, get_adapter, validate_source_url
from app.crawler.browser_urls import (
    WANTED_DETAIL_API,
    collect_wanted_api,
    discover_wanted_urls,
    filter_wanted_candidates,
    get_json_with_retry,
)
from app.crawler.relevance import extract_tech_stack
from app.crawler.service import collect_http
from app.crawler.tracked import prioritize_tracked_urls, tracked_posting_urls
from app.db.base import Base
from app.models import Application, Company, JobPosting, JobSource


def test_applied_and_favorite_postings_are_prioritized_for_recurring_checks() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="jumpit", base_url=POLICIES["jumpit"].base_url, crawler_type="http")
        company = Company(name="테스트 회사", normalized_name="테스트 회사")
        session.add_all([source, company])
        session.flush()
        postings = []
        for index in range(1, 4):
            posting = JobPosting(
                source_id=source.id,
                external_job_id=str(index),
                company_id=company.id,
                title=f"Backend Engineer {index}",
                normalized_title=f"backend engineer {index}",
                url=f"https://jumpit.saramin.co.kr/position/{index}",
                canonical_url=f"https://jumpit.saramin.co.kr/position/{index}",
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                last_changed_at=datetime.now(UTC),
                content_hash=str(index) * 64,
            )
            postings.append(posting)
            session.add(posting)
        session.flush()
        postings[1].is_favorite = True
        session.add(Application(job_posting_id=postings[2].id, status="applied"))
        session.flush()

        tracked = tracked_posting_urls(session, source.id)
        ordered = prioritize_tracked_urls((posting.url for posting in postings), tracked)

        assert tracked == [postings[2].url, postings[1].url]
        assert ordered == [postings[1].url, postings[2].url, postings[0].url]


def _job_html(title: str, description: str, *, posted_at: str = "2026-01-01") -> str:
    return f"""
    <html><body><main>
      <script type="application/ld+json">{{
        "@type": "JobPosting",
        "title": "{title}",
        "description": "{description}",
        "datePosted": "{posted_at}",
        "hiringOrganization": {{"name": "테스트 회사"}}
      }}</script>
    </main></body></html>
    """


def test_server_and_specialized_requirement_technologies_are_extracted() -> None:
    technologies = extract_tech_stack(
        "Go GraphQL NGINX, OpenCV CUDA, CI/CD, Prometheus, Celery, ETL 데이터 파이프라인 실무 경험"
    )

    assert {
        "Go",
        "GraphQL",
        "NGINX",
        "OpenCV",
        "CUDA",
        "CI/CD",
        "Prometheus",
        "Celery",
        "Data Pipeline",
    }.issubset(technologies)


def test_collection_limit_applies_after_relevance_filter(monkeypatch, tmp_path) -> None:
    listing_url = POLICIES["jumpit"].list_urls[0]
    urls = [
        "https://jumpit.saramin.co.kr/position/1",
        "https://jumpit.saramin.co.kr/position/2",
        "https://jumpit.saramin.co.kr/position/3",
    ]
    sitemap = "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"
    pages = {
        listing_url: sitemap,
        urls[0]: _job_html("Product Designer", "Figma UX"),
        urls[1]: _job_html("Backend Engineer", "Python FastAPI PostgreSQL"),
        urls[2]: _job_html("Server Engineer", "TypeScript Node.js"),
    }
    requested: list[str] = []

    class FakeHttpClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def get(self, url: str, **_kwargs) -> str:
            requested.append(url)
            return pages[url]

    monkeypatch.setattr("app.crawler.service.CachedHttpClient", FakeHttpClient)
    engine = create_engine("sqlite+pysqlite:///:memory:")
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
        summary = asyncio.run(
            collect_http(
                session,
                Settings(crawler_cache_dir=str(tmp_path)),
                "jumpit",
                max_jobs=1,
            )
        )

        assert summary.jobs_found == 3
        assert summary.jobs_created == 1
        assert session.scalar(select(func.count(JobPosting.id))) == 1
        assert urls[0] in requested
        assert urls[1] in requested
        assert urls[2] not in requested


def test_wanted_candidates_are_prefiltered_and_deduplicated() -> None:
    candidates = [
        {"url": "https://www.wanted.co.kr/wd/1", "title": "Product Designer"},
        {"url": "https://www.wanted.co.kr/wd/2", "title": "Backend Engineer"},
        {"url": "https://www.wanted.co.kr/wd/2", "title": "Backend Engineer"},
        {"url": "https://www.wanted.co.kr/wd/3", "title": "Android Developer"},
        {"url": "https://www.wanted.co.kr/wd/4", "title": "Software Engineer"},
    ]

    assert filter_wanted_candidates(candidates, max_jobs=10) == [
        "https://www.wanted.co.kr/wd/2",
        "https://www.wanted.co.kr/wd/4",
    ]


def test_source_url_validation_blocks_cross_host_and_internal_urls() -> None:
    assert validate_source_url("demoday", "https://demoday.co.kr/recruits/28775").endswith("28775")
    assert validate_source_url("jumpit", "https://jumpit.saramin.co.kr/position/54443646").endswith(
        "54443646"
    )

    with pytest.raises(ValueError, match="must use https"):
        validate_source_url("jumpit", "http://127.0.0.1:8000/health")
    with pytest.raises(ValueError, match="URL host"):
        validate_source_url("rallit", "https://example.com/positions/3727/backend")
    with pytest.raises(ValueError, match="supported public job detail"):
        validate_source_url("wanted", "https://www.wanted.co.kr/api/v4/jobs")


def test_demoday_detail_uses_public_job_schema() -> None:
    html = """
    <html><body><main>
      <h1>테스트랩 - 백엔드 개발자</h1>
      <script type="application/ld+json">{
        "@type": "JobPosting",
        "title": "[채용] 테스트랩 - 백엔드 개발자",
        "description": "<p>Python FastAPI 기반 서버와 AWS 인프라를 운영합니다.</p>",
        "datePosted": "2026-08-10T00:00:00+00:00",
        "employmentType": "FULL_TIME",
        "experienceRequirements": "5+",
        "skills": "Python, FastAPI, AWS, Docker",
        "hiringOrganization": {"name": "테스트랩"}
      }</script>
    </main></body></html>
    """

    job = get_adapter("demoday").parse_detail(html, "https://demoday.co.kr/recruits/28775")

    assert job.external_job_id == "28775"
    assert job.title == "테스트랩 - 백엔드 개발자"
    assert job.company_name == "테스트랩"
    assert job.experience_text == "경력 5년 이상"
    assert {"Python", "FastAPI", "AWS", "Docker"}.issubset(job.tech_stack)


def test_demoday_listing_reads_nextjs_server_payload_links() -> None:
    html = r"""<script>self.__next_f.push([1,"{\"href\":\"/recruits/28775\"}"])</script>"""

    urls = get_adapter("demoday").listing_urls(html, "https://demoday.co.kr/recruits?search=Python")

    assert urls == ["https://demoday.co.kr/recruits/28775"]


def test_expired_detail_is_persisted_inactive(monkeypatch, tmp_path) -> None:
    listing_url = POLICIES["jumpit"].list_urls[0]
    detail_url = "https://jumpit.saramin.co.kr/position/99"
    expired_at = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    pages = {
        listing_url: f"<urlset><url><loc>{detail_url}</loc></url></urlset>",
        detail_url: f"""
        <html><body><main><script type="application/ld+json">{{
          "@type": "JobPosting",
          "title": "Backend Engineer",
          "description": "Python FastAPI PostgreSQL",
          "datePosted": "2026-01-01",
          "validThrough": "{expired_at}",
          "hiringOrganization": {{"name": "테스트 회사"}}
        }}</script></main></body></html>
        """,
    }

    class FakeHttpClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def get(self, url: str, **_kwargs) -> str:
            return pages[url]

    monkeypatch.setattr("app.crawler.service.CachedHttpClient", FakeHttpClient)
    engine = create_engine("sqlite+pysqlite:///:memory:")
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
        asyncio.run(
            collect_http(
                session,
                Settings(crawler_cache_dir=str(tmp_path)),
                "jumpit",
                max_jobs=10,
            )
        )

        posting = session.scalar(select(JobPosting))
        assert posting is not None
        assert posting.is_active is False


def test_wanted_public_api_discovers_only_active_target_roles(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "id": 10,
                        "position": "Backend Engineer",
                        "status": "active",
                        "hidden": False,
                    },
                    {
                        "id": 11,
                        "position": "Product Designer",
                        "status": "active",
                        "hidden": False,
                    },
                    {
                        "id": 12,
                        "position": "Software Engineer",
                        "status": "closed",
                        "hidden": False,
                    },
                ],
                "links": {"next": None},
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def get(self, *_args, **_kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.crawler.browser_urls.httpx.AsyncClient", FakeClient)
    progress: list[tuple[int, int, int]] = []

    urls = asyncio.run(
        discover_wanted_urls(
            100, lambda visited, found, failed: progress.append((visited, found, failed))
        )
    )

    assert urls == ["https://www.wanted.co.kr/wd/10"]
    assert progress == [(0, 1, 0)]


def test_wanted_public_api_detail_is_structured_without_login() -> None:
    payload = {
        "job": {
            "id": 365213,
            "position": "Backend Engineer (Consumer Service)",
            "status": "active",
            "annual_from": 3,
            "annual_to": 6,
            "due_time": "2026-07-14",
            "company": {"name": "이베이재팬(eBay)"},
            "address": {"full_location": "서울 강남구 테헤란로 142"},
            "skill_tags": [{"title": "Python"}, {"title": "AWS"}],
            "detail": {
                "intro": "글로벌 커머스 서비스를 개발합니다.",
                "main_tasks": "• 대규모 트래픽 백엔드 API 개발",
                "requirements": "• Python 기반 서버 개발 경험",
                "preferred_points": "• AWS 운영 경험",
                "benefits": "• 최신 장비 제공",
            },
        }
    }

    job = get_adapter("wanted").parse_api_detail(payload, "https://www.wanted.co.kr/wd/365213")

    assert job.external_job_id == "365213"
    assert job.company_name == "이베이재팬(eBay)"
    assert job.main_tasks == ["대규모 트래픽 백엔드 API 개발"]
    assert {"Python", "AWS"}.issubset(job.tech_stack)
    assert job.experience_text == "경력 3-6년"
    assert job.deadline_at is not None
    assert job.deadline_at.date().isoformat() == "2026-07-14"

    payload["job"]["annual_from"] = 5
    payload["job"]["annual_to"] = 100
    open_ended = get_adapter("wanted").parse_api_detail(
        payload, "https://www.wanted.co.kr/wd/365213"
    )
    assert open_ended.experience_text == "경력 5년 이상"


def test_wanted_internship_is_explicit_even_with_an_annual_range() -> None:
    payload = {
        "data": {
            "job": {
                "id": 371415,
                "annual_from": 0,
                "annual_to": 1,
                "employment_type": "intern",
                "employment_note": "정규직전환형 · 인턴 3개월",
                "company": {"name": "익명 AI 회사"},
                "detail": {
                    "position": "[인턴] Backend Engineer",
                    "main_tasks": "Python API 서버 개발",
                    "requirements": "Production 서비스 운영 경험",
                },
            }
        }
    }

    job = get_adapter("wanted").parse_api_detail(payload, "https://www.wanted.co.kr/wd/371415")

    assert job.experience_text == "인턴 · 신입-경력 1년"
    assert job.employment_type == "intern"


def test_wanted_collection_uses_screen_detail_api_and_keeps_all_skill_tags(
    monkeypatch,
) -> None:
    requested_urls: list[str] = []
    payload = {
        "data": {
            "job": {
                "id": 363967,
                "status": "active",
                "annual_from": 3,
                "annual_to": 7,
                "company": {"name": "익명 테스트 회사"},
                "address": {"full_location": "인천 연수구"},
                "detail": {
                    "position": "백엔드 개발자",
                    "intro": "정산 플랫폼을 개발합니다.",
                    "main_tasks": "Spring Boot 기반 REST API 개발",
                    "requirements": "AWS, Docker 운영 경험",
                    "preferred_points": "Python 서비스 전환과 복잡한 쿼리 최적화 경험",
                    "benefits": "교육비 지원",
                },
                "skill_tags": [
                    {"text": "MySQL"},
                    {"text": "Redis"},
                    {"text": "Java"},
                    {"text": "AWS"},
                    {"text": "JPA"},
                    {"text": "Spring Boot"},
                    {"text": "Python"},
                ],
            }
        }
    }

    async def fake_get_json(_client, url: str, **_kwargs) -> dict[str, object]:
        requested_urls.append(url)
        return payload

    monkeypatch.setattr("app.crawler.browser_urls.get_json_with_retry", fake_get_json)
    jobs = asyncio.run(collect_wanted_api(["https://www.wanted.co.kr/wd/363967"]))

    assert requested_urls == [f"{WANTED_DETAIL_API}/363967/details"]
    assert len(jobs) == 1
    assert {"MySQL", "Redis", "Java", "AWS", "JPA", "Spring Boot", "Python"}.issubset(
        jobs[0].tech_stack
    )


def test_wanted_api_retries_a_transient_disconnect() -> None:
    class RetryResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"job": {"id": 1}}

    class FlakyClient:
        calls = 0

        async def get(self, *_args, **_kwargs) -> RetryResponse:
            self.calls += 1
            if self.calls == 1:
                raise httpx.RemoteProtocolError("temporary disconnect")
            return RetryResponse()

    client = FlakyClient()
    payload = asyncio.run(get_json_with_retry(client, "https://example.test", attempts=2))

    assert payload == {"job": {"id": 1}}
    assert client.calls == 2


def test_rallit_open_older_posting_keeps_original_date_and_experience() -> None:
    html = """
    <html><body><main>
      <script type="application/ld+json" textcontent='{
        "@type": "JobPosting",
        "title": "소프트웨어 엔지니어(Backend)",
        "description": "Python FastAPI LLM API 서버 개발",
        "datePosted": "2025-08-04",
        "validThrough": "9999-12-3125340218200000000:00",
        "hiringOrganization": {"name": "주식회사 사각"}
      }'></script>
      <script id="__NEXT_DATA__" type="application/json">{
        "props": {"pageProps": {"position": {
          "approvedAt": "2025-08-04 16:06:04",
          "jobLevels": ["MIDDLE", "JUNIOR"],
          "responsibilities": "<ul><li>AI 서비스 플랫폼 개발</li></ul>",
          "basicQualifications": "<ul><li>백엔드 API 서버 개발 경험</li></ul>",
          "preferredQualifications": "<ul><li>LLM 서비스 개발 경험</li></ul>",
          "benefits": "<ul><li>최신 장비 제공</li></ul>",
          "jobSkillKeywords": ["Django", "FastAPI", "PostgreSQL"]
        }}}
      }</script>
    </main></body></html>
    """

    job = get_adapter("rallit").parse_detail(
        html,
        "https://www.rallit.com/positions/3727/software-engineer-backend",
    )

    assert job.posted_at is not None
    assert job.posted_at.date().isoformat() == "2025-08-04"
    assert job.deadline_at is None
    assert job.experience_text == "미들 (4~8년), 주니어 (1~3년)"
    assert {"Django", "FastAPI", "PostgreSQL"}.issubset(job.tech_stack)
    assert job.main_tasks == ["AI 서비스 플랫폼 개발"]
