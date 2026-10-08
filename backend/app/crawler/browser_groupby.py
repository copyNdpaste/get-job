import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.company_facts import groupby_company_facts
from app.config import get_settings
from app.crawler.domain import CollectedJob
from app.crawler.hiring_process import analyze_hiring_process
from app.crawler.http import CachedHttpClient, RobotsDeniedError
from app.crawler.normalization import normalize_text
from app.crawler.relevance import assess_relevance, extract_tech_stack, is_likely_target_role
from app.crawler.tracked import prioritize_tracked_urls

ProgressCallback = Callable[[int, int, int], None]
DiscoveryCallback = Callable[[bool, str | None], None]

GROUPBY_API_BASE = "https://api.groupby.kr"
GROUPBY_PUBLIC_ORIGIN = "https://groupby.kr"
GROUPBY_DEVELOPER_PARENT_POSITION_ID = 17
LIST_PAGE_SIZE = 10
MAX_LIST_PAGES = 200
MAX_PUBLIC_POSITIONS = 50
GROUPBY_PUBLIC_CATALOG = f"{GROUPBY_PUBLIC_ORIGIN}/jobs/engineering"


class GroupbyRestrictedResponseError(RuntimeError):
    """The public API supplied display-restricted data instead of real postings."""


def _reject_restricted_position(position: dict[str, Any]) -> None:
    startup = position.get("startup")
    names = [position.get("name")]
    if isinstance(startup, dict):
        names.append(startup.get("name"))
    if any(isinstance(name, str) and "[표시 제한]" in name for name in names):
        raise GroupbyRestrictedResponseError(
            "GroupBy API가 표시 제한 응답을 반환했습니다. 제한된 공고는 저장하지 않습니다."
        )


@dataclass
class GroupbyDiscovery:
    candidates: list[dict[str, Any]]
    complete: bool
    warning: str | None = None


async def collect_groupby_browser(
    *,
    max_jobs: int = 50,
    profile_dir: str | Path = "playwright-profile/groupby",
    headless: bool = False,
    delay_min_seconds: float = 2.0,
    user_agent: str = "get-job/0.1 (+local personal job search)",
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
    on_discovery: DiscoveryCallback | None = None,
) -> list[CollectedJob]:
    """Collect GroupBy's open developer positions through its public page API.

    The legacy name is kept for API/CLI compatibility. An ephemeral HTTP client avoids
    inheriting a stale browser profile filter such as a previously selected Python skill.
    """
    del profile_dir, headless
    headers = {
        "Accept": "application/json",
        "Origin": GROUPBY_PUBLIC_ORIGIN,
        "Referer": f"{GROUPBY_PUBLIC_ORIGIN}/positions",
        "User-Agent": user_agent,
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
    ) as client:
        try:
            discovery = await _discover_groupby_candidates(
                client,
                delay_min_seconds=delay_min_seconds,
            )
        except GroupbyRestrictedResponseError:
            return await collect_groupby_public_pages(
                max_jobs=max_jobs,
                delay_min_seconds=delay_min_seconds,
                user_agent=user_agent,
                priority_urls=priority_urls,
                on_progress=on_progress,
                on_discovery=on_discovery,
            )
        if on_discovery:
            on_discovery(discovery.complete, discovery.warning)
        candidates = discovery.candidates
        prioritized_urls = prioritize_tracked_urls(
            (
                f"{GROUPBY_PUBLIC_ORIGIN}/positions/{candidate.get('id')}"
                for candidate in candidates
                if isinstance(candidate.get("id"), int)
            ),
            priority_urls or [],
        )
        priority_order = {url: index for index, url in enumerate(prioritized_urls)}
        candidates.sort(
            key=lambda candidate: priority_order.get(
                f"{GROUPBY_PUBLIC_ORIGIN}/positions/{candidate.get('id')}",
                len(priority_order),
            )
        )
        found = len(candidates)
        failed = 0
        results: list[CollectedJob] = []
        if on_progress:
            on_progress(0, found, failed)

        for index, candidate in enumerate(candidates):
            title = normalize_text(str(candidate.get("name") or ""))
            if not title or not is_likely_target_role(title):
                if on_progress:
                    on_progress(index + 1, found, failed)
                continue
            position_id = candidate.get("id")
            if not isinstance(position_id, int) or position_id <= 0:
                failed += 1
                if on_progress:
                    on_progress(index + 1, found, failed)
                continue
            try:
                payload = await _get_groupby_data(
                    client,
                    f"{GROUPBY_API_BASE}/startup-positions/{position_id}",
                )
                collected = parse_groupby_api_detail(payload)
                if assess_relevance(
                    collected.title,
                    collected.description_text,
                    collected.experience_text,
                    collected.employment_type,
                ).included:
                    results.append(collected)
            except GroupbyRestrictedResponseError:
                return await collect_groupby_public_pages(
                    max_jobs=max_jobs,
                    delay_min_seconds=delay_min_seconds,
                    user_agent=user_agent,
                    priority_urls=priority_urls,
                    on_progress=on_progress,
                    on_discovery=on_discovery,
                )
            except (httpx.HTTPError, RuntimeError, TypeError, ValueError, KeyError):
                failed += 1
            if on_progress:
                on_progress(index + 1, found, failed)
            if len(results) >= max_jobs:
                break
            if delay_min_seconds > 0:
                await asyncio.sleep(delay_min_seconds)
    return results


async def _discover_groupby_candidates(
    client: httpx.AsyncClient,
    *,
    delay_min_seconds: float,
) -> GroupbyDiscovery:
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    offset = 0
    total: int | None = None
    invalid_items = False

    def finish() -> GroupbyDiscovery:
        if invalid_items or (total is not None and len(seen) < total):
            return GroupbyDiscovery(
                candidates,
                False,
                "GroupBy 목록에 누락되거나 잘못된 항목이 있어 부분 수집했습니다.",
            )
        return GroupbyDiscovery(candidates, True)

    for _ in range(MAX_LIST_PAGES):
        data = await _get_groupby_data(
            client,
            f"{GROUPBY_API_BASE}/startup-positions",
            params={
                "parentPositionTypes": GROUPBY_DEVELOPER_PARENT_POSITION_ID,
                "offset": offset,
                "limit": LIST_PAGE_SIZE,
            },
        )
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise RuntimeError("groupby public API returned no position list")
        if total is None:
            raw_total = data.get("total")
            total = raw_total if type(raw_total) is int and raw_total >= 0 else None
        if not raw_items:
            return finish()
        previous_count = len(seen)
        for item in raw_items:
            if not isinstance(item, dict):
                invalid_items = True
                continue
            position_id = item.get("id")
            if type(position_id) is not int or position_id <= 0:
                invalid_items = True
                continue
            if position_id not in seen:
                seen.add(position_id)
                candidates.append(item)
        if len(seen) == previous_count:
            return GroupbyDiscovery(
                candidates,
                False,
                "GroupBy 목록에서 새로운 공고를 찾지 못해 반복 조회를 중단하고 부분 수집했습니다.",
            )
        # Offset refers to API rows, including malformed and duplicate entries.
        offset += len(raw_items)
        if total is not None and offset >= total:
            return finish()
        if total is None and len(raw_items) < LIST_PAGE_SIZE:
            return finish()
        if delay_min_seconds > 0 and _ + 1 < MAX_LIST_PAGES:
            await asyncio.sleep(delay_min_seconds)
    return GroupbyDiscovery(
        candidates,
        False,
        f"GroupBy 목록 조회 안전 한도({MAX_LIST_PAGES}페이지)에 도달해 부분 수집했습니다.",
    )


async def _get_groupby_data(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, object] | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != 200:
                raise ValueError("unexpected GroupBy API envelope")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("missing GroupBy API data")
            _reject_restricted_position(data)
            for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
                if isinstance(item, dict):
                    _reject_restricted_position(item)
            return data
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError("groupby public API request failed") from last_error


def _public_page_props(html: str) -> dict[str, Any]:
    node = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if node is None:
        raise ValueError("GroupBy 공개 페이지의 구조화 데이터를 찾지 못했습니다.")
    payload = json.loads(node.get_text())
    outer_props = payload.get("props") if isinstance(payload, dict) else None
    props = outer_props.get("pageProps") if isinstance(outer_props, dict) else None
    if not isinstance(props, dict):
        raise ValueError("GroupBy 공개 페이지의 데이터 구조가 변경되었습니다.")
    return props


def parse_groupby_public_detail(html: str, position_id: int) -> CollectedJob:
    payload = _public_page_props(html).get("fallbackDataRaw")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if (
        not isinstance(payload, dict)
        or type(payload.get("id")) is not int
        or payload["id"] != position_id
    ):
        raise ValueError("GroupBy 공개 상세 페이지의 공고 ID가 일치하지 않습니다.")
    return parse_groupby_api_detail(payload)


async def collect_groupby_public_pages(
    *,
    max_jobs: int,
    delay_min_seconds: float,
    user_agent: str,
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
    on_discovery: DiscoveryCallback | None = None,
) -> list[CollectedJob]:
    """Read only openly published HTML, never the restricted API or login pages.

    The category's initial HTML is a subset of the catalog. Never use this path
    to infer that missing postings closed, even when every visible item was read.
    """
    if on_discovery:
        on_discovery(
            False,
            "GroupBy API 표시 제한으로 공개 개발자 페이지에 노출된 공고만 부분 수집했습니다. "
            "전체 목록을 확인하지 못해 기존 공고의 마감 상태는 유지합니다.",
        )
    async with CachedHttpClient(
        cache_dir=".cache/groupby-public",
        respect_robots=get_settings().crawler_respect_robots,
        user_agent=user_agent,
        delay_min_seconds=delay_min_seconds,
        delay_max_seconds=max(delay_min_seconds, get_settings().crawler_delay_max_seconds),
    ) as client:
        html = await client.get(
            GROUPBY_PUBLIC_CATALOG, expected_host="groupby.kr", force_refresh=True
        )
        positions = _public_page_props(html).get("positions")
        if not isinstance(positions, list):
            raise ValueError("GroupBy 공개 개발자 페이지에 공고 목록이 없습니다.")
        candidates: dict[str, dict[str, Any]] = {}
        for position in positions[:MAX_PUBLIC_POSITIONS]:
            if not isinstance(position, dict):
                continue
            _reject_restricted_position(position)
            position_id = position.get("id")
            if type(position_id) is int and position_id > 0:
                candidates[f"{GROUPBY_PUBLIC_ORIGIN}/positions/{position_id}"] = position
        urls = prioritize_tracked_urls(candidates, priority_urls or [])
        found = len(urls)
        failed = 0
        results: list[CollectedJob] = []
        if on_progress:
            on_progress(0, found, failed)
        for index, url in enumerate(urls):
            candidate = candidates[url]
            if is_likely_target_role(str(candidate.get("name") or "")):
                try:
                    html = await client.get(url, expected_host="groupby.kr", force_refresh=True)
                    job = parse_groupby_public_detail(html, candidate["id"])
                    if assess_relevance(
                        job.title, job.description_text, job.experience_text, job.employment_type
                    ).included:
                        results.append(job)
                except (GroupbyRestrictedResponseError, RobotsDeniedError):
                    raise
                except (httpx.HTTPError, RuntimeError, TypeError, ValueError, KeyError):
                    failed += 1
            if on_progress:
                on_progress(index + 1, found, failed)
            if len(results) >= max_jobs:
                break
    return results


def parse_groupby_api_detail(payload: dict[str, Any]) -> CollectedJob:
    _reject_restricted_position(payload)
    position_id = payload.get("id")
    startup = payload.get("startup")
    if not isinstance(position_id, int) or position_id <= 0 or not isinstance(startup, dict):
        raise ValueError("groupby detail is missing position/startup")
    title = normalize_text(str(payload.get("name") or ""))
    company = normalize_text(str(startup.get("name") or ""))
    if not title or not company:
        raise ValueError("groupby detail is missing title/company")

    main_tasks = _html_items(payload.get("task"))
    requirements = _html_items(payload.get("qualification"))
    preferred = _html_items(payload.get("preferred"))
    benefits = _string_items(startup.get("keywords"))
    api_tech_stack = _string_items(payload.get("techStacks"))
    process_info = analyze_hiring_process(_html_items(payload.get("hiringProcess")))
    description_parts = [
        title,
        company,
        *main_tasks,
        *requirements,
        *preferred,
        *process_info.steps,
        *api_tech_stack,
    ]
    description_text = normalize_text("\n".join(description_parts))
    detected_stack = extract_tech_stack(description_text)
    tech_stack = list(dict.fromkeys([*api_tech_stack, *detected_stack]))

    location_parts = []
    location = payload.get("location")
    if isinstance(location, dict) and location.get("name"):
        location_parts.append(str(location["name"]))
    if payload.get("address"):
        location_parts.append(str(payload["address"]))
    if not location_parts and startup.get("location"):
        location_parts.append(str(startup["location"]))
    location_text = normalize_text(" ".join(dict.fromkeys(location_parts))) or None
    url = f"{GROUPBY_PUBLIC_ORIGIN}/positions/{position_id}"
    return CollectedJob(
        source_name="groupby",
        external_job_id=str(position_id),
        company_name=company,
        title=title,
        url=url,
        description_raw=json.dumps(payload, ensure_ascii=False, default=str),
        description_text=description_text,
        main_tasks=main_tasks,
        requirements=requirements,
        preferred_requirements=preferred,
        benefits=benefits,
        tech_stack=tech_stack,
        hiring_process=list(process_info.steps),
        has_coding_test=process_info.has_coding_test,
        interview_count=process_info.interview_count,
        experience_text=_experience_text(payload),
        location=location_text,
        posted_at=_datetime(payload.get("publishedAt")),
        deadline_at=_datetime(payload.get("dueDate")),
        company_facts=groupby_company_facts(startup),
    )


def _html_items(value: object) -> list[str]:
    if not value:
        return []
    text = BeautifulSoup(str(value), "html.parser").get_text("\n", strip=True)
    return [line.strip().lstrip("•·- ") for line in text.splitlines() if line.strip()]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        raw = item.get("name") if isinstance(item, dict) else item
        normalized = normalize_text(str(raw or ""))
        if normalized and normalized not in items:
            items.append(normalized)
    return items


def _experience_text(payload: dict[str, Any]) -> str | None:
    career_type = normalize_text(str(payload.get("careerType") or ""))
    if career_type in {"신입", "인턴", "무관"}:
        return career_type
    experience = payload.get("experienceRange")
    if not isinstance(experience, dict):
        return career_type or None
    minimum = experience.get("min")
    maximum = experience.get("max")
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        return career_type or None
    if minimum == 0 and maximum >= 10:
        return "경력 전체"
    if maximum >= 10:
        return f"경력 {minimum}년 이상"
    if minimum == 0:
        return f"경력 {maximum}년 이하"
    if minimum == maximum:
        return f"경력 {minimum}년"
    return f"경력 {minimum}~{maximum}년"


def _datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
