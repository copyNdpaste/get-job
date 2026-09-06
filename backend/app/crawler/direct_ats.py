import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.crawler.domain import CollectedJob
from app.crawler.hiring_process import analyze_hiring_process
from app.crawler.normalization import normalize_text
from app.crawler.relevance import assess_relevance, extract_tech_stack, is_likely_target_role
from app.crawler.tracked import prioritize_tracked_urls
from app.direct_ats_catalog import DirectAtsBoard

ProgressCallback = Callable[[int, int, int], None]

ATS_API_HOSTS = {
    "greenhouse": "boards-api.greenhouse.io",
    "lever": "api.lever.co",
    "ashby": "api.ashbyhq.com",
}
KOREA_LOCATION_SIGNALS = (
    "korea",
    "seoul",
    "대한민국",
    "한국",
    "서울",
    "판교",
    "경기도",
    "부산",
    "대전",
    "인천",
)
REMOTE_LOCATION_SIGNALS = ("remote", "원격", "재택")
GLOBAL_REMOTE_SIGNALS = ("worldwide", "global remote", "anywhere", "apac", "asia")


def _api_url(board: DirectAtsBoard) -> str:
    if board.source_name == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{board.board_key}/jobs?content=true"
    if board.source_name == "lever":
        return f"https://api.lever.co/v0/postings/{board.board_key}?mode=json"
    if board.source_name == "ashby":
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{board.board_key}"
            "?includeCompensation=true"
        )
    raise ValueError(f"{board.source_name} does not expose a configured public API")


def validate_ats_api_url(source_name: str, url: str) -> str:
    if source_name not in ATS_API_HOSTS:
        raise ValueError(f"unsupported ATS API source: {source_name}")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != ATS_API_HOSTS[source_name]:
        raise ValueError(f"{source_name} API URL must use its exact public API host")
    if parts.username or parts.password or parts.port not in {None, 443}:
        raise ValueError("ATS API URL must not contain credentials or a custom port")
    patterns = {
        "greenhouse": r"/v1/boards/[A-Za-z0-9_-]+/jobs",
        "lever": r"/v0/postings/[A-Za-z0-9_-]+",
        "ashby": r"/posting-api/job-board/[A-Za-z0-9_-]+",
    }
    if not re.fullmatch(patterns[source_name], parts.path):
        raise ValueError(f"unsupported {source_name} API path")
    return url


def validate_ninehire_api_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != "api.ninehire.com"
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
        or parts.path != "/identity-access/homepage/recruitments"
    ):
        raise ValueError("Ninehire API URL must use the exact public recruitment endpoint")
    if not re.search(r"(?:^|&)companyId=[0-9a-f-]{36}(?:&|$)", parts.query, re.IGNORECASE):
        raise ValueError("Ninehire API URL is missing a valid public company ID")
    return url


def _html_text(value: object) -> str:
    return normalize_text(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))


def _html_items(value: object) -> list[str]:
    if not value:
        return []
    text = BeautifulSoup(str(value), "html.parser").get_text("\n", strip=True)
    return [
        normalized
        for line in text.splitlines()
        if (normalized := normalize_text(line.lstrip("•·- ")))
    ]


def _datetime(value: object, *, milliseconds: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if milliseconds and isinstance(value, int):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OSError):
        return None


def _experience_text(text: str) -> str | None:
    match = re.search(
        r"(?:경력\s*)?(?:신입\s*[-~]\s*)?\d+\s*(?:[-~]\s*\d+)?\s*년(?:\s*(?:이상|이하))?"
        r"|\b\d+\+?\s*(?:years?|yrs?)\b",
        text,
        re.IGNORECASE,
    )
    return normalize_text(match.group()) if match else None


def _is_korea_target(location: str | None, description: str) -> bool:
    location_text = normalize_text(location or "").casefold()
    if any(signal in location_text for signal in KOREA_LOCATION_SIGNALS):
        return True
    if any(signal in location_text for signal in REMOTE_LOCATION_SIGNALS):
        description_text = description.casefold()
        return any(signal in description_text for signal in GLOBAL_REMOTE_SIGNALS) or any(
            signal in description_text for signal in KOREA_LOCATION_SIGNALS
        )
    if location_text:
        return False
    return any(signal in description.casefold() for signal in KOREA_LOCATION_SIGNALS)


def _sections_from_html(value: object) -> dict[str, list[str]]:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    sections = {"main_tasks": [], "requirements": [], "preferred_requirements": [], "benefits": []}
    aliases = {
        "main_tasks": ("responsibil", "what you'll do", "주요업무", "담당업무", "하는 일"),
        "requirements": ("requirement", "qualification", "what we're looking", "자격요건", "필수"),
        "preferred_requirements": ("preferred", "nice to have", "우대", "더 좋아"),
        "benefits": ("benefit", "what we offer", "복지", "혜택"),
    }
    for heading in soup.select("h1,h2,h3,h4,strong"):
        label = normalize_text(heading.get_text(" ", strip=True)).casefold()
        section_name = next(
            (name for name, values in aliases.items() if any(value in label for value in values)),
            None,
        )
        if section_name is None:
            continue
        items: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3", "h4"}:
                break
            if isinstance(sibling, Tag):
                items.extend(_html_items(sibling))
        for item in items:
            if item not in sections[section_name]:
                sections[section_name].append(item)
    return sections


def _build_job(
    *,
    source_name: str,
    external_id: object,
    company_name: str,
    title: object,
    url: str,
    raw: object,
    description_html: object,
    location: object = None,
    employment_type: object = None,
    posted_at: object = None,
    deadline_at: object = None,
    posted_at_milliseconds: bool = False,
    extra_sections: dict[str, list[str]] | None = None,
) -> CollectedJob:
    normalized_title = normalize_text(str(title or ""))
    description_text = _html_text(description_html)
    if not normalized_title or not company_name or not description_text:
        raise ValueError(f"{source_name} job is missing title/company/description")
    sections = _sections_from_html(description_html)
    for name, items in (extra_sections or {}).items():
        if name in sections:
            sections[name] = list(dict.fromkeys([*sections[name], *items]))
    process_info = analyze_hiring_process(_html_items(description_html))
    tech_stack = extract_tech_stack(f"{normalized_title}\n{description_text}")
    return CollectedJob(
        source_name=source_name,
        external_job_id=str(external_id),
        company_name=company_name,
        title=normalized_title,
        url=url,
        description_raw=(
            raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
        ),
        description_text=description_text,
        main_tasks=sections["main_tasks"],
        requirements=sections["requirements"],
        preferred_requirements=sections["preferred_requirements"],
        benefits=sections["benefits"],
        tech_stack=tech_stack,
        hiring_process=list(process_info.steps),
        has_coding_test=process_info.has_coding_test,
        interview_count=process_info.interview_count,
        experience_text=_experience_text(f"{normalized_title} {description_text}"),
        location=normalize_text(str(location or "")) or None,
        employment_type=normalize_text(str(employment_type or "")) or None,
        posted_at=_datetime(posted_at, milliseconds=posted_at_milliseconds),
        deadline_at=_datetime(deadline_at),
    )


def parse_greenhouse_job(board: DirectAtsBoard, payload: dict[str, Any]) -> CollectedJob:
    job_id = payload.get("id")
    if not isinstance(job_id, int):
        raise ValueError("Greenhouse job is missing its numeric ID")
    location = payload.get("location")
    location_name = location.get("name") if isinstance(location, dict) else None
    url = f"https://job-boards.greenhouse.io/{board.board_key}/jobs/{job_id}"
    return _build_job(
        source_name="greenhouse",
        external_id=job_id,
        company_name=board.company_name,
        title=payload.get("title"),
        url=url,
        raw=payload,
        description_html=payload.get("content"),
        location=location_name,
        posted_at=payload.get("updated_at"),
    )


def parse_lever_job(board: DirectAtsBoard, payload: dict[str, Any]) -> CollectedJob:
    job_id = normalize_text(str(payload.get("id") or ""))
    if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", job_id):
        raise ValueError("Lever job is missing its public ID")
    categories = payload.get("categories")
    categories = categories if isinstance(categories, dict) else {}
    lists = payload.get("lists") if isinstance(payload.get("lists"), list) else []
    description_parts = [str(payload.get("description") or "")]
    extra_sections = {"main_tasks": [], "requirements": [], "preferred_requirements": []}
    for item in lists:
        if not isinstance(item, dict):
            continue
        heading = normalize_text(str(item.get("text") or "")).casefold()
        content = item.get("content") or ""
        description_parts.append(f"<h2>{heading}</h2>{content}")
        target = (
            "main_tasks"
            if any(word in heading for word in ("responsibil", "what you'll do", "업무"))
            else "preferred_requirements"
            if any(word in heading for word in ("preferred", "nice to", "우대"))
            else "requirements"
            if any(word in heading for word in ("requirement", "qualification", "자격"))
            else None
        )
        if target:
            extra_sections[target].extend(_html_items(content))
    return _build_job(
        source_name="lever",
        external_id=job_id,
        company_name=board.company_name,
        title=payload.get("text"),
        url=f"https://jobs.lever.co/{board.board_key}/{job_id}",
        raw=payload,
        description_html="\n".join(description_parts),
        location=categories.get("location"),
        employment_type=categories.get("commitment"),
        posted_at=payload.get("createdAt"),
        posted_at_milliseconds=True,
        extra_sections=extra_sections,
    )


def parse_ashby_job(board: DirectAtsBoard, payload: dict[str, Any]) -> CollectedJob:
    job_url = normalize_text(str(payload.get("jobUrl") or ""))
    parts = urlsplit(job_url)
    path_match = re.fullmatch(
        rf"/{re.escape(board.board_key)}/([A-Za-z0-9-]+)", parts.path.rstrip("/")
    )
    if parts.scheme != "https" or parts.hostname != "jobs.ashbyhq.com" or not path_match:
        raise ValueError("Ashby job URL is outside the configured public board")
    return _build_job(
        source_name="ashby",
        external_id=path_match.group(1),
        company_name=board.company_name,
        title=payload.get("title"),
        url=f"https://jobs.ashbyhq.com{parts.path.rstrip('/')}",
        raw=payload,
        description_html=payload.get("descriptionHtml") or payload.get("descriptionPlain"),
        location=payload.get("location"),
        employment_type=payload.get("employmentType"),
        posted_at=payload.get("publishedAt"),
    )


PARSERS = {
    "greenhouse": parse_greenhouse_job,
    "lever": parse_lever_job,
    "ashby": parse_ashby_job,
}


def _payload_rows(source_name: str, payload: object) -> list[dict[str, Any]]:
    if source_name == "greenhouse" and isinstance(payload, dict):
        rows = payload.get("jobs")
    elif source_name == "ashby" and isinstance(payload, dict):
        rows = payload.get("jobs")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError(f"{source_name} public API returned no job list")
    return [row for row in rows if isinstance(row, dict)]


def _public_candidate_url(source_name: str, board: DirectAtsBoard, payload: dict[str, Any]) -> str:
    if source_name == "greenhouse":
        return f"https://job-boards.greenhouse.io/{board.board_key}/jobs/{payload.get('id')}"
    if source_name == "lever":
        return f"https://jobs.lever.co/{board.board_key}/{payload.get('id')}"
    return normalize_text(str(payload.get("jobUrl") or "")).rstrip("/")


async def collect_public_ats(
    source_name: str,
    boards: tuple[DirectAtsBoard, ...],
    *,
    max_jobs: int,
    delay_min_seconds: float,
    user_agent: str,
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[CollectedJob]:
    selected = [board for board in boards if board.source_name == source_name]
    candidates: list[tuple[DirectAtsBoard, dict[str, Any]]] = []
    failed = 0
    headers = {"Accept": "application/json", "User-Agent": user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=False) as client:
        for board in selected:
            try:
                url = validate_ats_api_url(source_name, _api_url(board))
                response = await client.get(url)
                response.raise_for_status()
                candidates.extend(
                    (board, row) for row in _payload_rows(source_name, response.json())
                )
            except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
                failed += 1
            if delay_min_seconds > 0:
                await asyncio.sleep(delay_min_seconds)

    priority_order = {
        url: index
        for index, url in enumerate(
            prioritize_tracked_urls(
                (
                    _public_candidate_url(source_name, board, payload)
                    for board, payload in candidates
                ),
                priority_urls or [],
            )
        )
    }
    candidates.sort(
        key=lambda candidate: priority_order.get(
            _public_candidate_url(source_name, candidate[0], candidate[1]),
            len(priority_order),
        )
    )
    if on_progress:
        on_progress(0, len(candidates), failed)
    results: list[CollectedJob] = []
    for index, (board, payload) in enumerate(candidates):
        try:
            title = normalize_text(str(payload.get("title") or payload.get("text") or ""))
            if not is_likely_target_role(title):
                continue
            job = PARSERS[source_name](board, payload)
            if not _is_korea_target(job.location, job.description_text):
                continue
            if assess_relevance(
                job.title,
                job.description_text,
                job.experience_text,
                job.employment_type,
            ).included:
                results.append(job)
                if len(results) >= max_jobs:
                    break
        except (KeyError, TypeError, ValueError):
            failed += 1
        finally:
            if on_progress:
                on_progress(index + 1, len(candidates), failed)
    return results


def parse_rendered_board_job(
    source_name: str,
    board: DirectAtsBoard,
    *,
    title: str,
    url: str,
    html: str,
    metadata: dict[str, Any] | None = None,
) -> CollectedJob:
    parts = urlsplit(url)
    board_host = urlsplit(board.board_url).hostname
    if parts.scheme != "https" or parts.hostname != board_host:
        raise ValueError("rendered ATS detail URL left the configured company board")
    path_patterns = {
        "greeting": r"/(?:ko|en)/o/(\d+)",
        "ninehire": r"/job_posting/([A-Za-z0-9]+)",
    }
    match = re.fullmatch(path_patterns[source_name], parts.path.rstrip("/"))
    if match is None:
        raise ValueError(f"unsupported {source_name} public job detail path")

    soup = BeautifulSoup(html, "html.parser")
    for unwanted in soup.select("script,style,svg,noscript"):
        unwanted.decompose()
    body = soup.select_one("main") or soup.body or soup
    description_html = str(body)
    meta = metadata or {}
    experience = normalize_text(str(meta.get("experience_text") or "")) or None
    location = normalize_text(str(meta.get("location") or "")) or None
    employment_type = normalize_text(str(meta.get("employment_type") or "")) or None
    job = _build_job(
        source_name=source_name,
        external_id=match.group(1),
        company_name=board.company_name,
        title=title,
        url=url,
        raw=html,
        description_html=description_html,
        location=location,
        employment_type=employment_type,
        posted_at=meta.get("posted_at"),
        deadline_at=meta.get("deadline_at"),
    )
    if experience:
        job.experience_text = experience
    return job


async def collect_rendered_ats(
    source_name: str,
    boards: tuple[DirectAtsBoard, ...],
    *,
    max_jobs: int,
    headless: bool,
    delay_min_seconds: float,
    user_agent: str,
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[CollectedJob]:
    if source_name not in {"greeting", "ninehire"}:
        raise ValueError(f"unsupported rendered ATS source: {source_name}")
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("install crawler extras: pip install -e 'backend[crawler]'") from exc

    selected = [board for board in boards if board.source_name == source_name]
    candidates: list[tuple[DirectAtsBoard, str, str, dict[str, Any]]] = []
    failed = 0
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=user_agent)
        page = await context.new_page()
        for board in selected:
            try:
                if source_name == "greeting":
                    await page.goto(board.board_url, wait_until="domcontentloaded", timeout=45_000)
                    await page.wait_for_timeout(1_500)
                    anchors = await page.locator('a[href*="/o/"]').evaluate_all(
                        "els => els.map(e => ({url: e.href, title: (e.innerText || '').trim()}))"
                    )
                    for item in anchors:
                        if not isinstance(item, dict):
                            continue
                        url = normalize_text(str(item.get("url") or ""))
                        title = normalize_text(str(item.get("title") or "").split("\n", 1)[0])
                        if title and is_likely_target_role(title):
                            candidates.append((board, title, url, {}))
                else:
                    board_page = await context.new_page()
                    async with board_page.expect_response(
                        lambda response: (
                            response.url.startswith(
                                "https://api.ninehire.com/identity-access/homepage/recruitments?"
                            )
                            and response.request.method == "GET"
                        ),
                        timeout=45_000,
                    ) as response_info:
                        await board_page.goto(
                            board.board_url, wait_until="domcontentloaded", timeout=45_000
                        )
                    response = await response_info.value
                    api_url = validate_ninehire_api_url(response.url)
                    api_response = await context.request.get(api_url, max_redirects=0)
                    if not api_response.ok:
                        raise ValueError(
                            f"Ninehire public recruitment API returned {api_response.status}"
                        )
                    payload = await api_response.json()
                    await board_page.close()
                    rows = payload.get("results") if isinstance(payload, dict) else None
                    if not isinstance(rows, list):
                        raise ValueError("Ninehire public board returned no recruitment list")
                    for row in rows:
                        if not isinstance(row, dict) or row.get("status") != "in_progress":
                            continue
                        title = normalize_text(
                            str(row.get("externalTitle") or row.get("title") or "")
                        )
                        address_key = normalize_text(str(row.get("addressKey") or ""))
                        if not title or not address_key or not is_likely_target_role(title):
                            continue
                        career = row.get("career") if isinstance(row.get("career"), dict) else {}
                        career_range = (
                            career.get("range") if isinstance(career.get("range"), dict) else {}
                        )
                        minimum = career_range.get("over")
                        maximum = career_range.get("below")
                        experience = None
                        if career.get("type") == "newcomer":
                            experience = "신입"
                        elif isinstance(minimum, int):
                            experience = (
                                f"경력 {minimum}~{maximum}년"
                                if isinstance(maximum, int) and maximum > 0
                                else f"경력 {minimum}년 이상"
                            )
                        locations = row.get("jobLocations")
                        location = " ".join(
                            normalize_text(
                                str(item.get("addressName") or item.get("placeName") or "")
                            )
                            for item in locations or []
                            if isinstance(item, dict)
                        )
                        employments = row.get("employmentType")
                        candidates.append(
                            (
                                board,
                                title,
                                f"https://{urlsplit(board.board_url).hostname}/job_posting/{address_key}",
                                {
                                    "experience_text": experience,
                                    "location": location,
                                    "employment_type": (
                                        ", ".join(str(item) for item in employments)
                                        if isinstance(employments, list)
                                        else employments
                                    ),
                                    "posted_at": row.get("createdAt"),
                                    "deadline_at": row.get("deadlineValue"),
                                },
                            )
                        )
            except (PlaywrightTimeoutError, TypeError, ValueError):
                failed += 1

        deduplicated: dict[str, tuple[DirectAtsBoard, str, str, dict[str, Any]]] = {}
        for candidate in candidates:
            deduplicated[candidate[2]] = candidate
        candidates = list(deduplicated.values())
        ordered_urls = prioritize_tracked_urls(
            (candidate[2] for candidate in candidates), priority_urls or []
        )
        priority_order = {url: index for index, url in enumerate(ordered_urls)}
        candidates.sort(key=lambda candidate: priority_order[candidate[2]])
        if on_progress:
            on_progress(0, len(candidates), failed)

        results: list[CollectedJob] = []
        for index, (board, title, url, metadata) in enumerate(candidates):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_timeout(750)
                if page.url.rstrip("/") != url.rstrip("/"):
                    raise ValueError("rendered ATS detail redirected outside the expected URL")
                html = await page.content()
                job = parse_rendered_board_job(
                    source_name,
                    board,
                    title=title,
                    url=url,
                    html=html,
                    metadata=metadata,
                )
                if assess_relevance(
                    job.title,
                    job.description_text,
                    job.experience_text,
                    job.employment_type,
                ).included:
                    results.append(job)
                    if len(results) >= max_jobs:
                        break
            except (PlaywrightTimeoutError, TypeError, ValueError):
                failed += 1
            finally:
                if on_progress:
                    on_progress(index + 1, len(candidates), failed)
            if delay_min_seconds > 0:
                await asyncio.sleep(delay_min_seconds)
        await context.close()
        await browser.close()
    return results
