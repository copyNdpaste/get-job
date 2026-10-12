import asyncio
import random
from collections.abc import Callable
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.crawler.adapters import POLICIES, get_adapter, validate_source_url
from app.crawler.domain import CollectedJob
from app.crawler.http import CachedHttpClient, retry_delay
from app.crawler.relevance import assess_relevance, is_likely_target_role
from app.crawler.source_dates import jobposting_dates
from app.crawler.tracked import prioritize_tracked_urls

ProgressCallback = Callable[[int, int, int], None]
WANTED_JOBS_API = "https://www.wanted.co.kr/api/v4/jobs"
WANTED_DETAIL_API = "https://www.wanted.co.kr/api/chaos/jobs/v4"
WANTED_DETAIL_CONCURRENCY = 8
WANTED_LIST_CONCURRENCY = 8


class RequestPacer:
    """Spread starts across concurrent requests made by one source client."""

    def __init__(self, sleep=asyncio.sleep) -> None:
        self.lock = asyncio.Lock()
        self.sleep = sleep
        self.started = False

    async def wait(self) -> None:
        async with self.lock:
            if self.started:
                await self.sleep(random.uniform(0.5, 1.5))
            self.started = True


async def get_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, object] | None = None,
    attempts: int = 5,
    pacer: RequestPacer | None = None,
) -> dict[str, object]:
    for attempt in range(attempts):
        try:
            if pacer is not None:
                await pacer.wait()
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            retryable_status = isinstance(exc, httpx.HTTPStatusError) and (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if isinstance(exc, httpx.HTTPStatusError) and not retryable_status:
                raise
            if attempt + 1 >= attempts:
                raise
            delay = (
                retry_delay(exc.response, attempt)
                if isinstance(exc, httpx.HTTPStatusError)
                else 0.5 * (2**attempt)
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


def filter_wanted_candidates(candidates: list[dict[str, str]], max_jobs: int) -> list[str]:
    """Keep unique development roles before visiting Wanted detail pages."""
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = candidate.get("url", "")
        title = candidate.get("title", "")
        if not url or url in seen or not is_likely_target_role(title):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max_jobs:
            break
    return urls


async def discover_wanted_urls(
    max_jobs: int,
    on_progress: ProgressCallback | None = None,
) -> list[str]:
    """Discover all public active Wanted roles without rendering the infinite list."""
    candidates: list[dict[str, str]] = []
    offset = 0
    page_size = 100
    async with httpx.AsyncClient(
        headers={"User-Agent": get_settings().crawler_user_agent},
        follow_redirects=True,
        timeout=30,
    ) as client:
        pacer = RequestPacer()

        async def fetch_page(page_offset: int) -> dict[str, object]:
            return await get_json_with_retry(
                client,
                WANTED_JOBS_API,
                pacer=pacer,
                params={
                    "country": "kr",
                    "job_sort": "job.latest_order",
                    "years": -1,
                    "locations": "all",
                    "limit": page_size,
                    "offset": page_offset,
                },
            )

        for _ in range(25):
            offsets = [offset + page_size * index for index in range(WANTED_LIST_CONCURRENCY)]
            pages = await asyncio.gather(*(fetch_page(page_offset) for page_offset in offsets))
            reached_end = False
            for payload in pages:
                rows = payload.get("data", [])
                if not isinstance(rows, list) or not rows:
                    reached_end = True
                    break
                for row in rows:
                    if (
                        not isinstance(row, dict)
                        or row.get("status") != "active"
                        or row.get("hidden") is True
                        or not row.get("id")
                    ):
                        continue
                    candidates.append(
                        {
                            "url": f"https://www.wanted.co.kr/wd/{row['id']}",
                            "title": str(row.get("position", row.get("title", ""))),
                        }
                    )
                if not payload.get("links", {}).get("next"):
                    reached_end = True
                    break
            target_urls = filter_wanted_candidates(candidates, max_jobs)
            if on_progress:
                on_progress(0, len(target_urls), 0)
            if len(target_urls) >= max_jobs or reached_end:
                return target_urls
            offset += page_size * WANTED_LIST_CONCURRENCY
            await asyncio.sleep(0.1)
    return filter_wanted_candidates(candidates, max_jobs)


async def collect_wanted_api(
    target_urls: list[str],
    on_progress: ProgressCallback | None = None,
) -> list[CollectedJob]:
    adapter = get_adapter("wanted")
    semaphore = asyncio.Semaphore(WANTED_DETAIL_CONCURRENCY)

    async with httpx.AsyncClient(
        headers={"User-Agent": get_settings().crawler_user_agent},
        follow_redirects=True,
        timeout=30,
    ) as client:
        pacer = RequestPacer()
        settings = get_settings()
        pages = CachedHttpClient(
            cache_dir=".cache/wanted-dates",
            user_agent=settings.crawler_user_agent,
            respect_robots=settings.crawler_respect_robots,
            delay_min_seconds=0,
            delay_max_seconds=0,
            cache_ttl_seconds=7 * 24 * 3600,
            before_request=pacer.wait,
        )

        async def fetch(url: str) -> CollectedJob:
            async with semaphore:
                job_id = url.rstrip("/").rsplit("/", 1)[-1]
                payload = await get_json_with_retry(
                    client, f"{WANTED_DETAIL_API}/{job_id}/details", pacer=pacer
                )
                job = adapter.parse_api_detail(payload, url)
                try:
                    html = await pages.get(url, expected_host="www.wanted.co.kr")
                    posted, _ = jobposting_dates(BeautifulSoup(html, "html.parser"), url)
                    job.posted_at = posted
                    # Keep the current API deadline: JSON-LD expiry can contradict publication.
                except (httpx.HTTPError, RuntimeError, ValueError):
                    # API detail remains usable; lack of a date is not a guessed timestamp.
                    pass
                return job

        tasks = [asyncio.create_task(fetch(url)) for url in target_urls]
        results: list[CollectedJob] = []
        failed = 0
        completed = 0
        try:
            for task in asyncio.as_completed(tasks):
                try:
                    job = await task
                    if assess_relevance(
                        job.title,
                        job.description_text,
                        job.experience_text,
                        job.employment_type,
                    ).included:
                        results.append(job)
                except Exception:
                    failed += 1
                completed += 1
                if on_progress:
                    on_progress(completed, len(target_urls), failed)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pages.client.aclose()
        return results


async def collect_browser_urls(
    source_name: str,
    urls: list[str] | None,
    *,
    profile_dir: str | Path,
    max_jobs: int = 50,
    headless: bool = False,
    delay_min_seconds: float = 2.0,
    priority_urls: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[CollectedJob]:
    if not urls and source_name not in {"wanted", "remember"}:
        raise ValueError(f"{source_name} browser collection requires public job URLs")
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("install crawler extras: pip install -e 'backend[crawler]'") from exc

    adapter = get_adapter(source_name)
    results: list[CollectedJob] = []
    target_urls = list(dict.fromkeys(urls or []))
    if source_name == "wanted" and not target_urls:
        target_urls = await discover_wanted_urls(max_jobs, on_progress)
    if source_name == "wanted":
        target_urls = prioritize_tracked_urls(target_urls, priority_urls or [])
        return await collect_wanted_api(target_urls[:max_jobs], on_progress)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        if source_name == "remember" and not target_urls:
            listing_url = POLICIES[source_name].list_urls[0]
            try:
                await page.goto(listing_url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_function(
                    r"""() => Array.from(document.querySelectorAll('a[href]')).some(
                        a => /\/job\/postings?\/\d+/.test(a.getAttribute('href') || '')
                    )""",
                    timeout=30_000,
                )
                target_urls = get_adapter(source_name).listing_urls(await page.content(), page.url)
                target_urls = [validate_source_url(source_name, url) for url in target_urls]
            except Exception:
                await context.close()
                await browser.close()
                raise

        target_urls = prioritize_tracked_urls(target_urls, priority_urls or [])

        failed = 0
        if on_progress:
            on_progress(0, len(target_urls), failed)

        for index, url in enumerate(target_urls):
            try:
                validate_source_url(source_name, url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_function(
                    """() => {
                      const heading = document.querySelector('main h1');
                      const main = document.querySelector('main');
                      return Boolean(
                        heading?.textContent?.trim()
                        && main?.innerText?.trim().length > 200
                      );
                    }""",
                    timeout=30_000,
                )
                html = await page.content()
                detail_url = validate_source_url(source_name, page.url)
                data = adapter.parse_detail(html, detail_url)
                if assess_relevance(
                    data.title,
                    data.description_text,
                    data.experience_text,
                    data.employment_type,
                ).included:
                    results.append(data)
            except Exception:
                failed += 1
            finally:
                if on_progress:
                    on_progress(index + 1, len(target_urls), failed)
            if len(results) >= max_jobs:
                break
            if index + 1 < len(target_urls):
                await asyncio.sleep(delay_min_seconds)
        await context.close()
        await browser.close()
    return results
