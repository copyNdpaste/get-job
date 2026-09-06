import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.crawler.http import CachedHttpClient
from app.models import EcosystemCrawlRun, EcosystemOrganization, EcosystemProgram

PROGRAM_KEYWORDS = (
    "모집",
    "지원",
    "선발",
    "배치",
    "프로그램",
    "교육",
    "데모데이",
    "액셀러레이팅",
    "아카데미",
    "멘토링",
    "공모",
)
ANCHOR_PROGRAM_KEYWORDS = (
    "모집",
    "선발",
    "접수",
    "공고",
    "교육",
    "데모데이",
    "아카데미",
    "멘토링",
    "피칭",
    "행사",
    "세미나",
    "상담회",
    "설명회",
    "네트워킹",
    "챌린지",
)
EXCLUDED_PROGRAM_PHRASES = (
    "출자사업",
    "접수 현황",
    "선정 결과",
    "서류평가 합격자",
    "서류평가 추가 선정기업",
    "자율규제",
    "투자자 모집",
    "vc pool 모집",
    "전문개인투자자 양성",
    "채용 공고",
    "청렴서한문",
    "보고서 발간",
)
CLOSED_KEYWORDS = (
    "모집종료",
    "접수마감",
    "마감",
    "종료",
    "진행 중인 프로그램이 없습니다",
    "closed",
)
DEADLINE_PATTERN = re.compile(r"20\d{2}[.년\-/\s]+\d{1,2}[.월\-/\s]+\d{1,2}(?:일)?")
SHORT_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2}|\d{2})[.년\-/\s]+)?"
    r"(?P<month>\d{1,2})[.월\-/](?:\s)*(?P<day>\d{1,2})(?:일)?"
)
PROGRAM_MONTH_PATTERN = re.compile(r"(?P<year>20\d{2})년\s*(?P<month>\d{1,2})월")
REGISTERED_DATE_PATTERN = re.compile(r"등록일자\s*(20\d{2}-\d{2}-\d{2})")


@dataclass(frozen=True, slots=True)
class ProgramCandidate:
    title: str
    url: str
    summary: str | None
    program_type: str
    deadline_text: str | None
    is_open: bool


def _compact(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())[:500]


def _program_type(value: str) -> str:
    lowered = value.casefold()
    if (
        "데모데이" in lowered
        or "d.day" in lowered
        or re.search(r"(?<![a-z])ir(?![a-z])", lowered)
        or "피칭" in lowered
    ):
        return "demo_day"
    if "배치" in lowered or "액셀러레이팅" in lowered:
        return "batch"
    if "투자" in lowered or "피칭" in lowered:
        return "investment"
    if "교육" in lowered or "아카데미" in lowered or "멘토링" in lowered:
        return "education"
    return "program"


def _is_candidate(value: str) -> bool:
    return 4 <= len(value) <= 500 and any(
        keyword in value.casefold() for keyword in PROGRAM_KEYWORDS
    )


def _is_anchor_candidate(value: str) -> bool:
    lowered = value.casefold()
    return (
        4 <= len(value) <= 500
        and "상시지원" not in lowered
        and not any(phrase in lowered for phrase in EXCLUDED_PROGRAM_PHRASES)
        and (
            any(keyword in lowered for keyword in ANCHOR_PROGRAM_KEYWORDS)
            or re.search(r"(?<![a-z])ir(?![a-z])", lowered)
        )
    )


def _is_open(context: str, deadline_text: str | None) -> bool:
    lowered = context.casefold()
    if deadline_text:
        numbers = [int(value) for value in re.findall(r"\d+", deadline_text)]
        if len(numbers) >= 3:
            try:
                return date(*numbers[:3]) >= datetime.now(UTC).date()
            except ValueError:
                return True
    if any(keyword in lowered for keyword in CLOSED_KEYWORDS):
        return False
    registered = REGISTERED_DATE_PATTERN.search(context)
    if registered:
        registered_on = date.fromisoformat(registered.group(1))
        return (datetime.now(UTC).date() - registered_on).days <= 45
    return True


def _deadline_from_context(context: str) -> str | None:
    for match in DEADLINE_PATTERN.finditer(context):
        before = context[max(0, match.start() - 24) : match.start()].casefold()
        after = context[match.end() : match.end() + 24].casefold()
        if "등록일자" in before[-10:]:
            continue
        deadline_markers = ("마감", "접수", "신청", "~", "까지")
        if any(marker in before or marker in after for marker in deadline_markers):
            return match.group(0)
    for match in SHORT_DATE_PATTERN.finditer(context):
        before = context[max(0, match.start() - 24) : match.start()].casefold()
        if "등록일자" in before[-10:]:
            continue
        year_text = match.group("year")
        year = int(year_text) if year_text else datetime.now(UTC).year
        if year < 100:
            year += 2000
        try:
            parsed = date(year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            continue
        return parsed.isoformat()
    if "상담회" in context:
        program_month = PROGRAM_MONTH_PATTERN.search(context)
        if program_month:
            year = int(program_month.group("year"))
            month = int(program_month.group("month"))
            return date(year, month, monthrange(year, month)[1]).isoformat()
    return None


def _same_public_host(url: str, expected_host: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == expected_host
        and not parts.username
        and not parts.password
        and parts.port in {None, 443}
    )


def _source_path_allowed(url: str, expected_host: str) -> bool:
    if expected_host != "www.vcs.go.kr":
        return True
    return bool(re.fullmatch(r"/web/portal/bbs/(?:notice|martnotice)/[^/]+", urlsplit(url).path))


def _anchor_context(anchor: object, title: str) -> str:
    """Keep the listing card plus its preceding heading for safe type detection."""
    if not hasattr(anchor, "find_parent") or not hasattr(anchor, "find_previous"):
        return title
    container = anchor.find_parent(["article", "li", "section", "div"])
    container_text = container.get_text(" ", strip=True) if container else title
    heading = anchor.find_previous(["h1", "h2", "h3", "h4"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    return _compact(f"{heading_text} {container_text}", 1200)


def extract_program_candidates(html: str, page_url: str) -> list[ProgramCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    expected_host = urlsplit(page_url).hostname
    if not expected_host:
        return []
    candidates: list[ProgramCandidate] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.select("a[href]"):
        title = _compact(anchor.get_text(" ", strip=True), 500)
        if not _is_anchor_candidate(title):
            continue
        url = urljoin(page_url, str(anchor.get("href") or ""))
        if not _same_public_host(url, expected_host) or not _source_path_allowed(
            url, expected_host
        ):
            continue
        context = _anchor_context(anchor, title)
        key = (_normalized(title), url)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deadline_text = _deadline_from_context(title) or _deadline_from_context(context)
        candidates.append(
            ProgramCandidate(
                title=title,
                url=url,
                summary=context if context != title else None,
                program_type=_program_type(f"{title} {context}"),
                deadline_text=deadline_text,
                is_open=_is_open(context, deadline_text),
            )
        )
    if candidates:
        return candidates[:100]
    title = (
        _compact((soup.title or soup.find("h1")).get_text(" ", strip=True), 500)
        if (soup.title or soup.find("h1"))
        else ""
    )
    page_text = _compact(soup.get_text(" ", strip=True), 4000)
    if not _is_candidate(f"{title} {page_text}"):
        return []
    deadline_text = _deadline_from_context(page_text)
    return [
        ProgramCandidate(
            title=title or "공개 프로그램 안내",
            url=page_url,
            summary=page_text[:1200] or None,
            program_type=_program_type(f"{title} {page_text}"),
            deadline_text=deadline_text,
            is_open=_is_open(page_text, deadline_text),
        )
    ]


async def collect_organization_programs(
    session: Session, settings: Settings, organization_id: int, run_id: int | None = None
) -> EcosystemCrawlRun:
    organization = session.get(EcosystemOrganization, organization_id)
    if organization is None or not organization.enabled or not organization.program_url:
        raise ValueError("organization is not available for public program collection")
    if run_id is None:
        active = session.scalar(
            select(EcosystemCrawlRun.id).where(
                EcosystemCrawlRun.organization_id == organization.id,
                EcosystemCrawlRun.status == "running",
            )
        )
        if active is not None:
            raise ValueError(f"{organization.name} program collection is already running")
        run = EcosystemCrawlRun(
            organization_id=organization.id, status="running", started_at=datetime.now(UTC)
        )
        session.add(run)
        session.commit()
    else:
        run = session.get(EcosystemCrawlRun, run_id)
        if run is None or run.organization_id != organization.id:
            raise ValueError("program collection run is not available")
    try:
        expected_host = urlsplit(organization.program_url).hostname
        if not expected_host:
            raise ValueError("program URL must include a host")
        async with CachedHttpClient(
            cache_dir=settings.crawler_cache_dir,
            user_agent=settings.crawler_user_agent,
            delay_min_seconds=settings.crawler_delay_min_seconds,
            delay_max_seconds=settings.crawler_delay_max_seconds,
        ) as client:
            html = await client.get(
                organization.program_url, force_refresh=True, expected_host=expected_host
            )
        run.pages_visited = 1
        candidates = extract_program_candidates(html, organization.program_url)
        run.programs_found = len(candidates)
        now = datetime.now(UTC)
        session.execute(
            update(EcosystemProgram)
            .where(EcosystemProgram.organization_id == organization.id)
            .values(is_active=False)
        )
        for candidate in candidates:
            normalized_title = _normalized(candidate.title)
            existing = session.scalar(
                select(EcosystemProgram).where(
                    EcosystemProgram.organization_id == organization.id,
                    EcosystemProgram.normalized_title == normalized_title,
                )
            )
            if existing is None:
                session.add(
                    EcosystemProgram(
                        organization_id=organization.id,
                        title=candidate.title,
                        normalized_title=normalized_title,
                        url=candidate.url,
                        program_type=candidate.program_type,
                        summary=candidate.summary,
                        deadline_text=candidate.deadline_text,
                        is_open=candidate.is_open,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
                run.programs_created += 1
            else:
                existing.title = candidate.title
                existing.url = candidate.url
                existing.program_type = candidate.program_type
                existing.summary = candidate.summary
                existing.deadline_text = candidate.deadline_text
                existing.is_open = candidate.is_open
                existing.is_active = True
                existing.last_seen_at = now
                run.programs_updated += 1
        organization.last_crawled_at = now
        run.status = "succeeded"
    except Exception as exc:
        session.rollback()
        run = session.get(EcosystemCrawlRun, run.id)
        if run is not None:
            run.status = "failed"
            run.error_log = str(exc)[:4000]
    finally:
        run = session.get(EcosystemCrawlRun, run.id)
        if run is not None:
            run.finished_at = datetime.now(UTC)
            session.commit()
    return run
