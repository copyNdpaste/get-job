import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.crawler.adapters import POLICIES, get_adapter
from app.crawler.browser_groupby import _discover_groupby_candidates
from app.crawler.hiring_process import analyze_hiring_process
from app.crawler.persistence import upsert_collected_job
from app.crawler.relevance import assess_relevance, is_likely_target_role
from app.db.base import Base
from app.models import JobPosting, JobPostingSnapshot, JobSource

scenarios("features/job_collection.feature")

FIXTURE_DIR = Path(__file__).parent / "fixtures"
URLS = {
    "groupby": "https://groupby.kr/positions",
    "wanted": "https://www.wanted.co.kr/wd/287697",
    "jumpit": "https://jumpit.saramin.co.kr/position/52642030",
    "rocketpunch": "https://www.rocketpunch.com/jobs/153918",
    "rallit": "https://www.rallit.com/positions/4279/server-developer",
}


@pytest.fixture
def context() -> dict[str, object]:
    return {}


@given(parsers.parse('"{source}"의 공개 채용 상세 HTML이 있다'))
def detail_html(context: dict[str, object], source: str) -> None:
    context["source"] = source
    context["html"] = (FIXTURE_DIR / f"{source}_detail.html").read_text(encoding="utf-8")


@when("사이트 adapter로 공고를 파싱한다")
def parse_detail(context: dict[str, object]) -> None:
    source = str(context["source"])
    job = get_adapter(source).parse_detail(str(context["html"]), URLS[source])
    context["job"] = job
    context["decision"] = assess_relevance(job.title, job.description_text)


@then("공고는 개발 직무로 포함된다")
def included(context: dict[str, object]) -> None:
    assert context["decision"].included  # type: ignore[union-attr]


@then(parsers.parse('제목은 "{title}"이다'))
def title_is(context: dict[str, object], title: str) -> None:
    assert context["job"].title == title  # type: ignore[union-attr]


@then(parsers.parse('기술 스택에 "{tech}"가 있다'))
def tech_is_present(context: dict[str, object], tech: str) -> None:
    assert tech in context["job"].tech_stack  # type: ignore[union-attr]


@given(parsers.parse('제목이 "{title}"이고 본문에 "{description}"가 있다'))
def job_text(context: dict[str, object], title: str, description: str) -> None:
    context.update(title=title, description=description)


@given(
    parsers.parse(
        '제목이 "{title}"이고 본문에 "{description}"가 있으며 경력 조건이 "{experience}"이다'
    )
)
def job_text_with_experience(
    context: dict[str, object], title: str, description: str, experience: str
) -> None:
    context.update(title=title, description=description, experience=experience)


@when("개발 공고 관련성을 판정한다")
def decide(context: dict[str, object]) -> None:
    context["decision"] = assess_relevance(
        str(context["title"]),
        str(context["description"]),
        str(context["experience"]) if "experience" in context else None,
    )


@then("공고는 수집 대상에서 제외된다")
def excluded(context: dict[str, object]) -> None:
    assert not context["decision"].included  # type: ignore[union-attr]


def test_python_development_title_remains_in_collection_scope() -> None:
    decision = assess_relevance(
        "Python 개발",
        "Django와 FastAPI로 백엔드 API를 개발하고 PostgreSQL, AWS를 운영합니다.",
        "경력 4년 이상",
    )

    assert decision.included is True


@given(parsers.parse('원티드 목록 공고 제목이 "{title}"이다'))
def wanted_listing_title(context: dict[str, object], title: str) -> None:
    context["title"] = title


@when("상세 페이지 방문 전 직군을 판정한다")
def decide_wanted_listing_visit(context: dict[str, object]) -> None:
    context["visit"] = is_likely_target_role(str(context["title"]))


@then(parsers.parse('상세 페이지 방문 여부는 "{visit}"이다'))
def wanted_listing_visit_is(context: dict[str, object], visit: str) -> None:
    assert context["visit"] is (visit == "yes")


@given("원티드 화면 기술 스택이 포함된 공개 상세 API 응답이 있다")
def wanted_api_with_skill_tags(context: dict[str, object]) -> None:
    context["wanted_api_payload"] = {
        "error_code": None,
        "message": "ok",
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
                    "main_tasks": "• Spring Boot 기반 REST API 설계 및 개발",
                    "requirements": "• AWS, Docker 환경의 서버 운영 경험",
                    "preferred_points": "• 복잡한 쿼리 최적화 경험",
                    "benefits": "• 교육비 지원",
                    "hire_rounds": "서류 → 코딩테스트 → 1차 면접 → 처우 협의",
                },
                "skill_tags": [
                    {"tag_type_id": 1464, "text": "MySQL"},
                    {"tag_type_id": 1470, "text": "Redis"},
                    {"tag_type_id": 1540, "text": "Java"},
                    {"tag_type_id": 1698, "text": "AWS"},
                    {"tag_type_id": 3451, "text": "JPA"},
                    {"tag_type_id": 10169, "text": "Spring Boot"},
                ],
            }
        },
    }


@when("원티드 API adapter로 공고를 파싱한다")
def parse_wanted_api(context: dict[str, object]) -> None:
    context["job"] = get_adapter("wanted").parse_api_detail(
        context["wanted_api_payload"],  # type: ignore[arg-type]
        "https://www.wanted.co.kr/wd/363967",
    )


@then("코딩테스트가 있는 공고로 구분된다")
def wanted_has_coding_test(context: dict[str, object]) -> None:
    assert context["job"].has_coding_test is True  # type: ignore[union-attr]


@then("면접 횟수는 1회로 구분된다")
def wanted_has_one_interview(context: dict[str, object]) -> None:
    assert context["job"].interview_count == 1  # type: ignore[union-attr]


@given(parsers.parse('"{source}" 수집 정책이 있다'))
def policy(context: dict[str, object], source: str) -> None:
    context["policy"] = POLICIES[source]


@then(parsers.parse('수집 방식은 "{mode}"이다'))
def collection_mode(context: dict[str, object], mode: str) -> None:
    assert context["policy"].collection_mode == mode  # type: ignore[union-attr]


@given("그룹바이 공개 목록 API에 개발 공고 3개가 두 페이지에 있다")
def groupby_api_pages(context: dict[str, object]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params.get("offset", "0"))
        items = (
            [
                {"id": 101, "name": "Backend Engineer"},
                {"id": 102, "name": "AI Engineer"},
            ]
            if offset == 0
            else [{"id": 103, "name": "Server Engineer"}]
        )
        return httpx.Response(
            200,
            request=request,
            json={"status": 200, "data": {"total": 3, "items": items}},
        )

    context["groupby_transport"] = httpx.MockTransport(handler)
    context["groupby_requests"] = requests


@when("그룹바이 공개 API에서 개발 후보를 탐색한다")
def discover_groupby_api_candidates(context: dict[str, object]) -> None:
    async def discover() -> list[dict[str, object]]:
        async with httpx.AsyncClient(
            transport=context["groupby_transport"],  # type: ignore[arg-type]
            headers={
                "Origin": "https://groupby.kr",
                "Referer": "https://groupby.kr/positions",
            },
        ) as client:
            return await _discover_groupby_candidates(client, delay_min_seconds=0)

    context["groupby_candidates"] = asyncio.run(discover())


@then(parsers.parse("그룹바이 개발 후보는 {count:d}개이다"))
def groupby_candidate_count(context: dict[str, object], count: int) -> None:
    assert len(context["groupby_candidates"]) == count  # type: ignore[arg-type]


@then("모든 그룹바이 목록 요청은 개발 직군 필터를 사용한다")
def groupby_requests_use_developer_filter(context: dict[str, object]) -> None:
    requests = context["groupby_requests"]
    assert requests  # type: ignore[truthy-function]
    assert all(
        request.url.host == "api.groupby.kr"
        and request.url.params.get("parentPositionTypes") == "17"
        for request in requests  # type: ignore[union-attr]
    )


@given(parsers.parse('비어 있는 수집 DB와 "{source_name}" 수집원이 있다'))
def empty_database(context: dict[str, object], source_name: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    source = JobSource(
        name=source_name,
        base_url=POLICIES[source_name].base_url,
        crawler_type=POLICIES[source_name].collection_mode,
    )
    session.add(source)
    session.commit()
    context.update(session=session, db_source=source)


@when("같은 상세 HTML을 두 번 저장한다")
def save_same_detail_twice(context: dict[str, object]) -> None:
    session = context["session"]
    source = context["db_source"]
    html = (FIXTURE_DIR / "jumpit_detail.html").read_text(encoding="utf-8")
    job = get_adapter("jumpit").parse_detail(html, URLS["jumpit"])
    upsert_collected_job(session, source, job)  # type: ignore[arg-type]
    session.commit()  # type: ignore[union-attr]
    upsert_collected_job(session, source, job)  # type: ignore[arg-type]
    session.commit()  # type: ignore[union-attr]


@then("공고는 1개이고 스냅샷도 1개이다")
def one_posting_one_snapshot(context: dict[str, object]) -> None:
    session = context["session"]
    assert session.scalar(select(func.count(JobPosting.id))) == 1  # type: ignore[union-attr]
    assert session.scalar(select(func.count(JobPostingSnapshot.id))) == 1  # type: ignore[union-attr]


@when("주요업무가 변경된 HTML을 저장한다")
def save_changed_detail(context: dict[str, object]) -> None:
    session = context["session"]
    source = context["db_source"]
    html = (FIXTURE_DIR / "jumpit_detail.html").read_text(encoding="utf-8")
    changed = html.replace("PostgreSQL 서비스를 개발합니다", "Kafka 서비스를 개발합니다")
    job = get_adapter("jumpit").parse_detail(changed, URLS["jumpit"])
    upsert_collected_job(session, source, job)  # type: ignore[arg-type]
    session.commit()  # type: ignore[union-attr]


@then("공고는 1개이고 스냅샷은 2개이다")
def one_posting_two_snapshots(context: dict[str, object]) -> None:
    session = context["session"]
    assert session.scalar(select(func.count(JobPosting.id))) == 1  # type: ignore[union-attr]
    assert session.scalar(select(func.count(JobPostingSnapshot.id))) == 2  # type: ignore[union-attr]


@given(parsers.parse('채용 절차가 "{process}"로 명시되어 있다'))
def hiring_process_text(context: dict[str, object], process: str) -> None:
    context["hiring_process_text"] = [] if process == "미기재" else [process]


@when("채용 절차를 분석한다")
def analyze_process(context: dict[str, object]) -> None:
    context["hiring_process_info"] = analyze_hiring_process(
        context["hiring_process_text"]  # type: ignore[arg-type]
    )


@then(parsers.parse('코딩테스트 여부는 "{expected}"이다'))
def coding_test_is(context: dict[str, object], expected: str) -> None:
    labels = {True: "있음", False: "없음", None: "미확인"}
    assert labels[context["hiring_process_info"].has_coding_test] == expected  # type: ignore[union-attr]


@then(parsers.parse('면접 횟수는 "{expected}"이다'))
def interview_count_is(context: dict[str, object], expected: str) -> None:
    count = context["hiring_process_info"].interview_count  # type: ignore[union-attr]
    assert ("미확인" if count is None else str(count)) == expected


def test_jumpit_sitemap_urls_are_discovered() -> None:
    xml = """<urlset><url><loc>https://jumpit.saramin.co.kr/position/12345</loc></url></urlset>"""

    assert get_adapter("jumpit").listing_urls(
        xml, "https://jumpit.saramin.co.kr/sitemap/jobs.xml"
    ) == ["https://jumpit.saramin.co.kr/position/12345"]


def test_rallit_server_sitemap_discovers_only_position_urls() -> None:
    xml = """<urlset>
      <url><loc>https://www.rallit.com/hub/resumes/10</loc></url>
      <url><loc>https://www.rallit.com/positions/4279/server-developer</loc></url>
      <url><loc>https://www.rallit.com/companies/7/example</loc></url>
    </urlset>"""

    assert get_adapter("rallit").listing_urls(xml, "https://www.rallit.com/server-sitemap.xml") == [
        "https://www.rallit.com/positions/4279/server-developer"
    ]


def test_groupby_generic_url_is_upgraded_to_the_real_position_url() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(
            name="groupby",
            base_url=POLICIES["groupby"].base_url,
            crawler_type=POLICIES["groupby"].collection_mode,
        )
        session.add(source)
        session.flush()
        html = (FIXTURE_DIR / "groupby_detail.html").read_text(encoding="utf-8")
        generic = get_adapter("groupby").parse_detail(html, URLS["groupby"])
        upsert_collected_job(session, source, generic)
        session.commit()

        detailed = replace(
            generic,
            external_job_id="11459",
            url="https://groupby.kr/positions/11459",
        )
        result = upsert_collected_job(session, source, detailed)
        session.commit()

        posting = session.scalar(select(JobPosting))
        assert result.status == "updated"
        assert session.scalar(select(func.count(JobPosting.id))) == 1
        assert posting is not None
        assert posting.external_job_id == "11459"
        assert posting.url == "https://groupby.kr/positions/11459"
