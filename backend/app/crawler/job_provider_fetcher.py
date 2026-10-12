import asyncio
import ipaddress
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

import httpx

from app.crawler.domain import CollectedJob
from app.crawler.jobplanet_processor import JobPlanetProcessor
from app.crawler.normalization import normalize_name, normalize_text
from app.crawler.relevance import assess_relevance, extract_tech_stack
from app.crawler.source_dates import korean_source_datetime

MAX_ENDPOINT_URL_LENGTH = 2_048
MAX_QUERY_LENGTH = 8_192
MAX_QUERY_PARAMS = 100
MAX_RESPONSE_BYTES = 5_000_000
JOBPLANET_PAGE_SIZE = 100
MAX_JOBPLANET_PAGE_REQUESTS = 250
ProgressCallback = Callable[[int, int, int], None]
PageProgressCallback = Callable[[int, int, int], None]
SleepCallback = Callable[[float], Awaitable[None]]


class JobPlanetPageClient(Protocol):
    async def get_jobs(self, page: int = 1, per: int = 20) -> list[dict]: ...


class ExternalJobFetchError(httpx.HTTPError):
    """A sanitized provider transport error safe to persist in crawl status."""


class ExternalJobStatusError(httpx.HTTPStatusError):
    """A sanitized non-success response from the configured provider."""


class ExternalJobFetcher:
    """Fetch a JSON job payload and pass it through the JobPlanet processor."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | httpx.Timeout = 30.0,
        processor: JobPlanetProcessor | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.transport = transport
        self.timeout = timeout
        self.processor = processor or JobPlanetProcessor()
        self.headers = {"Accept": "application/json", **dict(headers or {})}

    async def fetch_raw_data(self, endpoint_url: str, params: dict) -> dict:
        """Return one JSON object from an HTTPS provider endpoint.

        HTTP transport failures and non-success status codes are deliberately
        propagated as ``httpx.HTTPError`` subclasses so a synchronization caller
        can distinguish a failed fetch from an empty result set.
        """
        validate_provider_endpoint_url(endpoint_url)
        validate_provider_params(params)
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(endpoint_url, params=params)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExternalJobStatusError(
                f"External job provider returned HTTP {exc.response.status_code}",
                request=exc.request,
                response=exc.response,
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalJobFetchError("External job provider request failed") from exc

        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_RESPONSE_BYTES:
            raise ValueError("External job provider response is too large")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("External job provider response is too large")

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise ValueError("External job provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("External job provider response must be a JSON object")
        return payload

    async def get_processed_jobs(self, endpoint_url: str, params: dict) -> list[dict]:
        """Fetch provider data and normalize it for the existing job pipeline."""
        raw_data = await self.fetch_raw_data(endpoint_url, params)
        return self.processor.process_raw_payload(raw_data)


async def collect_jobplanet_jobs(
    endpoint_url: str,
    params: dict,
    *,
    max_jobs: int,
    on_progress: ProgressCallback | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[CollectedJob]:
    """Collect target-role JobPlanet rows for the existing persistence pipeline."""
    if max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    fetcher = ExternalJobFetcher(transport=transport)
    raw_data = await fetcher.fetch_raw_data(endpoint_url, params)
    _validate_jobplanet_payload(raw_data)
    rows = fetcher.processor.process_raw_payload(raw_data)
    return normalize_jobplanet_rows(
        rows,
        max_jobs=max_jobs,
        on_progress=on_progress,
    )


async def collect_jobplanet_pages(
    client: JobPlanetPageClient,
    *,
    max_jobs: int,
    delay_min_seconds: float,
    page_size: int = JOBPLANET_PAGE_SIZE,
    on_progress: PageProgressCallback | None = None,
    sleep: SleepCallback = asyncio.sleep,
) -> list[CollectedJob]:
    """Follow JobPlanet's infinite-scroll JSON pages until the limit or final page."""
    if isinstance(max_jobs, bool) or not isinstance(max_jobs, int) or max_jobs < 1:
        raise ValueError("max_jobs must be a positive integer")
    if (
        isinstance(delay_min_seconds, bool)
        or not isinstance(delay_min_seconds, (int, float))
        or not math.isfinite(delay_min_seconds)
        or delay_min_seconds < 0
    ):
        raise ValueError("delay_min_seconds must be a non-negative finite number")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 100
    ):
        raise ValueError("page_size must be an integer between 1 and 100")

    jobs: list[CollectedJob] = []
    seen_ids: set[str] = set()
    failed = 0

    for page in range(1, MAX_JOBPLANET_PAGE_REQUESTS + 1):
        rows = await client.get_jobs(page=page, per=page_size)
        if not isinstance(rows, list):
            raise ValueError("JobPlanet page result must be a list")

        new_ids_on_page = 0
        for row in rows:
            try:
                job = _to_collected_job(row)
            except (TypeError, ValueError):
                failed += 1
                continue
            if job.external_job_id in seen_ids:
                continue
            seen_ids.add(job.external_job_id)
            new_ids_on_page += 1
            # The API request is already constrained to JobPlanet's official
            # backend/software occupations. Applying the generic title-only
            # relevance check again would drop valid roles such as DevOps/SRE.
            jobs.append(job)
            if len(jobs) >= max_jobs:
                break

        if on_progress:
            on_progress(page, len(jobs), failed)

        reached_end = len(rows) < page_size or not rows or new_ids_on_page == 0
        if len(jobs) >= max_jobs or reached_end:
            break
        await sleep(float(delay_min_seconds))

    return jobs


def normalize_jobplanet_rows(
    rows: Sequence[dict],
    *,
    max_jobs: int,
    on_progress: ProgressCallback | None = None,
) -> list[CollectedJob]:
    """Convert standard JobPlanet dictionaries into persistence domain rows."""
    if max_jobs < 1:
        raise ValueError("max_jobs must be positive")
    jobs: list[CollectedJob] = []
    seen_ids: set[str] = set()
    visited = 0
    failed = 0
    for row in rows:
        visited += 1
        try:
            job = _to_collected_job(row)
        except (TypeError, ValueError):
            failed += 1
            continue
        if job.external_job_id in seen_ids:
            continue
        seen_ids.add(job.external_job_id)
        if assess_relevance(job.title, job.description_text).included:
            jobs.append(job)
        if len(jobs) >= max_jobs:
            break

    if on_progress:
        on_progress(visited, visited, failed)
    return jobs


def validate_provider_endpoint_url(endpoint_url: str) -> None:
    if len(endpoint_url) > MAX_ENDPOINT_URL_LENGTH:
        raise ValueError("External job provider endpoint URL is too long")
    try:
        parts = urlsplit(endpoint_url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("External job provider endpoint URL is invalid") from exc

    hostname = (parts.hostname or "").rstrip(".").lower()
    if (
        parts.scheme != "https"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or bool(parts.query)
        or bool(parts.fragment)
    ):
        raise ValueError("External job provider endpoint must be a safe HTTPS URL")

    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("External job provider endpoint must not target an internal host")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("External job provider endpoint must not target a private address")


def validate_provider_params(params: dict) -> None:
    if len(params) > MAX_QUERY_PARAMS:
        raise ValueError("External job provider request has too many parameters")
    try:
        query = str(httpx.QueryParams(params))
    except (TypeError, ValueError) as exc:
        raise ValueError("External job provider request parameters are invalid") from exc
    if len(query.encode()) > MAX_QUERY_LENGTH:
        raise ValueError("External job provider request parameters are too large")


def _to_collected_job(row: dict) -> CollectedJob:
    if not isinstance(row, dict):
        raise TypeError("JobPlanet row must be an object")
    external_id = normalize_text(str(row.get("job_id") or ""))
    title = normalize_text(str(row.get("title") or ""))
    company_name = normalize_text(str(row.get("company_name") or ""))
    location = normalize_text(str(row.get("location") or ""))
    url = normalize_text(str(row.get("job_url") or ""))
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", external_id)
        or not title
        or len(title) > 500
        or not company_name
        or len(company_name) > 255
        or not normalize_name(company_name)
        or len(location) > 500
        or len(url) > 2_048
    ):
        raise ValueError("JobPlanet row is missing an id, title, or company")
    _validate_job_url(url, external_id)

    description_text = normalize_text(str(row.get("description_text") or ""))
    if not description_text:
        description_text = normalize_text(" ".join(part for part in (title, location) if part))
    requirements = _row_text_list(row.get("requirements"))
    main_tasks = _row_text_list(row.get("main_tasks"))
    preferred_requirements = _row_text_list(row.get("preferred_requirements"))
    benefits = _row_text_list(row.get("benefits"))
    source_stack = _row_text_list(row.get("tech_stack"), max_items=100)
    tech_stack = _unique_text_values(
        [
            *extract_tech_stack(
                "\n".join(
                    [
                        title,
                        description_text,
                        *main_tasks,
                        *requirements,
                        *preferred_requirements,
                    ]
                )
            ),
            *source_stack,
        ]
    )
    experience_text = normalize_text(str(row.get("experience_text") or "")) or None
    employment_type = normalize_text(str(row.get("employment_type") or "")) or None
    return CollectedJob(
        source_name="jobplanet",
        posted_at=korean_source_datetime(row.get("posted_at")),
        deadline_at=korean_source_datetime(row.get("deadline_at"), end_of_day=True),
        external_job_id=external_id,
        company_name=company_name,
        title=title,
        url=url,
        description_raw=json.dumps(row, ensure_ascii=False, sort_keys=True),
        description_text=description_text,
        main_tasks=main_tasks,
        requirements=requirements,
        preferred_requirements=preferred_requirements,
        benefits=benefits,
        tech_stack=tech_stack,
        experience_text=experience_text[:500] if experience_text else None,
        location=location or None,
        employment_type=employment_type[:100] if employment_type else None,
    )


def _row_text_list(value: object, *, max_items: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_text_values(value[:max_items])


def _unique_text_values(values: Sequence[object]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(str(value or ""))
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _validate_job_url(url: str, external_id: str) -> None:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.jobplanet.co.kr"
        or parts.username is not None
        or parts.password is not None
        or parts.port not in {None, 443}
        or parts.path != "/job/search"
        or query != [("posting_ids[]", external_id)]
        or parts.fragment
    ):
        raise ValueError("JobPlanet row contains an unsupported public job URL")


def _validate_jobplanet_payload(payload: dict) -> None:
    data = payload.get("data")
    if not isinstance(data, dict) or not any(
        isinstance(data.get(key), list) for key in ("recruits", "postings")
    ):
        raise ValueError("External job provider response has an invalid JobPlanet envelope")
