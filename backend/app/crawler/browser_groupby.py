import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.company_facts import groupby_company_facts
from app.crawler.domain import CollectedJob
from app.crawler.hiring_process import analyze_hiring_process
from app.crawler.normalization import normalize_text
from app.crawler.relevance import assess_relevance, extract_tech_stack, is_likely_target_role
from app.crawler.tracked import prioritize_tracked_urls

ProgressCallback = Callable[[int, int, int], None]

GROUPBY_API_BASE = "https://api.groupby.kr"
GROUPBY_PUBLIC_ORIGIN = "https://groupby.kr"
GROUPBY_DEVELOPER_PARENT_POSITION_ID = 17
LIST_PAGE_SIZE = 10
MAX_LIST_PAGES = 200


async def collect_groupby_browser(
    *,
    max_jobs: int = 50,
    profile_dir: str | Path = "playwright-profile/groupby",
    headless: bool = False,
    delay_min_seconds: float = 2.0,
    user_agent: str = "get-job/0.1 (+local personal job search)",
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
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
        candidates = await _discover_groupby_candidates(
            client,
            delay_min_seconds=delay_min_seconds,
        )
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
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    offset = 0
    total: int | None = None
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
            total = raw_total if isinstance(raw_total, int) and raw_total >= 0 else None
        page_items = [item for item in raw_items if isinstance(item, dict)]
        for item in page_items:
            position_id = item.get("id")
            if isinstance(position_id, int) and position_id > 0 and position_id not in seen:
                seen.add(position_id)
                candidates.append(item)
        if not page_items:
            break
        offset += len(page_items)
        if total is not None and offset >= total:
            break
        if delay_min_seconds > 0:
            await asyncio.sleep(delay_min_seconds)
    else:
        raise RuntimeError("groupby public API pagination exceeded the safety limit")
    return candidates


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
            return data
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError("groupby public API request failed") from last_error


def parse_groupby_api_detail(payload: dict[str, Any]) -> CollectedJob:
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
