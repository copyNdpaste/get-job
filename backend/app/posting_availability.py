"""Conservative, fresh checks of public recruitment status. No age-based closure."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, update

from app.config import get_settings
from app.crawler.adapters import POLICIES, validate_source_url
from app.crawler.browser_urls import RequestPacer, discover_wanted_urls, get_json_with_retry
from app.crawler.http import CachedHttpClient
from app.crawler.jobplanet_fetcher import JobPlanetApiClient
from app.db.session import SessionLocal
from app.models import JobPosting, JobSource

CLOSED_TEXT = (
    "채용이 마감되었습니다",
    "채용이 종료되었습니다",
    "마감된 공고입니다",
    "종료된 공고입니다",
    "모집이 마감되었습니다",
)


def html_status(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    if any(
        word in text.casefold() for word in ("captcha", "access denied", "checking your browser")
    ):
        return "unknown", "access_challenge"
    # A phrase in a job's requirements is not a closure banner.
    for tag in soup.find_all(["h1", "h2", "h3", "button", "strong", "p", "div", "span"]):
        if any(
            parent.has_attr("hidden")
            or parent.get("aria-hidden") == "true"
            or "display:none" in str(parent.get("style", "")).replace(" ", "").lower()
            for parent in [tag, *tag.parents]
            if hasattr(parent, "has_attr")
        ):
            continue
        label = " ".join(tag.stripped_strings).strip(".! ")
        if any(label == phrase for phrase in CLOSED_TEXT):
            return "closed", "explicit_closed_notice"
    return "unknown", "no_authoritative_status"


def wanted_status(payload: dict, expected_id: str) -> tuple[str, str]:
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else None
    if not isinstance(job, dict) or str(job.get("id")) != expected_id:
        return "unknown", "unexpected_job_payload"
    status = job.get("status")
    if status == "active":
        return "open", "wanted_status_active"
    if status in {"closed", "inactive", "expired"}:
        return "closed", f"wanted_status_{status}"
    return "unknown", "unrecognized_source_status"


def http_failure(code: int) -> tuple[str, str, bool]:
    # Only Gone is definitive. A 404 may be a routing change or access restriction.
    return (
        "closed" if code == 410 else "unknown",
        f"http_{code}",
        code in {401, 403, 429} or code >= 500,
    )


async def audit(*, limit: int = 50000, resume: bool = False) -> dict:
    settings = get_settings()
    now = datetime.now(UTC)
    year = (now + timedelta(hours=9)).year
    start = datetime(year, 1, 1, tzinfo=UTC) - timedelta(hours=9)
    # Presence in a freshly fetched recruitment catalogue is positive evidence.
    # Absence is never interpreted as closure: scope, pagination and categories can change.
    catalogues: dict[str, set[str]] = {}
    try:
        urls = await asyncio.wait_for(discover_wanted_urls(5000), timeout=90)
        catalogues["wanted"] = {url.rstrip("/").rsplit("/", 1)[-1] for url in urls}
        print(
            json.dumps({"catalogue": "wanted", "open_ids": len(catalogues["wanted"])}), flush=True
        )
    except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
        pass
    try:
        client = JobPlanetApiClient()
        ids: set[str] = set()
        for page in range(1, 151):
            rows = await client.get_jobs(page=page, per=100)
            new_ids = {str(row["job_id"]) for row in rows} - ids
            ids.update(new_ids)
            if not rows or not new_ids:
                break
            await asyncio.sleep(max(0.5, settings.crawler_delay_min_seconds))
        catalogues["jobplanet"] = ids
        print(json.dumps({"catalogue": "jobplanet", "open_ids": len(ids)}), flush=True)
    except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
        pass
    counts: Counter = Counter()
    newly_closed = 0
    by_source: dict[str, Counter] = {}
    with SessionLocal() as session:
        rows = session.execute(
            select(
                JobPosting.id,
                JobSource.name,
                JobPosting.external_job_id,
                JobPosting.url,
                JobPosting.posted_at,
                JobPosting.deadline_at,
                JobPosting.is_active,
                JobPosting.availability_check,
            )
            .join(JobSource)
            .order_by(JobPosting.is_active.desc(), JobPosting.id.desc())
            .limit(limit)
        ).all()
    async with (
        CachedHttpClient(
            cache_dir=".cache/availability",
            user_agent=settings.crawler_user_agent,
            respect_robots=settings.crawler_respect_robots,
            delay_min_seconds=max(0.5, settings.crawler_delay_min_seconds),
            delay_max_seconds=max(1.5, settings.crawler_delay_max_seconds),
        ) as pages,
        httpx.AsyncClient(
            headers={"User-Agent": settings.crawler_user_agent}, follow_redirects=False, timeout=20
        ) as api,
    ):
        pacer = RequestPacer()
        unavailable_sources: set[str] = set()
        for index, row in enumerate(rows):
            status, reason = "unknown", "not_rechecked"
            prior = row.availability_check or {}
            if resume and prior.get("checked_at", "")[:10] == now.date().isoformat():
                status = prior.get("status", "unknown")
                counts[status] += 1
                by_source.setdefault(row.name, Counter())[status] += 1
                continue
            if row.deadline_at and row.deadline_at < now:
                status, reason = "closed", "verified_deadline_expired"
            elif row.posted_at and row.posted_at < start:
                status, reason = "old", "published_before_current_year"
            elif not row.is_active:
                status, reason = "unknown", "previously_inactive_not_reopened"
            elif row.external_job_id in catalogues.get(row.name, set()):
                status, reason = "open", "present_in_fresh_public_catalogue"
            elif row.name not in POLICIES or POLICIES[row.name].collection_mode == "manual_html":
                reason = "manual_source"
            elif row.name in unavailable_sources:
                reason = "source_unavailable_this_run"
            else:
                try:
                    validate_source_url(row.name, row.url)
                    if row.name == "wanted" and row.external_job_id.isdigit():
                        payload = await asyncio.wait_for(
                            get_json_with_retry(
                                api,
                                f"https://www.wanted.co.kr/api/chaos/jobs/v4/{row.external_job_id}/details",
                                attempts=2,
                                pacer=pacer,
                            ),
                            timeout=40,
                        )
                        status, reason = wanted_status(payload, row.external_job_id)
                    else:
                        html = await asyncio.wait_for(
                            pages.get(
                                row.url,
                                force_refresh=True,
                                expected_host=urlsplit(POLICIES[row.name].base_url).hostname,
                            ),
                            timeout=40,
                        )
                        status, reason = html_status(html)
                except httpx.HTTPStatusError as exc:
                    status, reason, pause_source = http_failure(exc.response.status_code)
                    if pause_source:
                        unavailable_sources.add(row.name)
                except (httpx.HTTPError, RuntimeError, TimeoutError):
                    status, reason = "unknown", "request_or_policy_failure"
                    unavailable_sources.add(row.name)
                except ValueError:
                    status, reason = "unknown", "invalid_public_url"
            values = {
                "availability_check": {
                    "status": status,
                    "reason": reason,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
            }
            if status == "closed":
                newly_closed += bool(row.is_active)
                values["is_active"] = False
            with SessionLocal.begin() as session:
                session.execute(update(JobPosting).where(JobPosting.id == row.id).values(**values))
            counts[status] += 1
            by_source.setdefault(row.name, Counter())[status] += 1
            if (index + 1) % 50 == 0:
                print(
                    json.dumps({"checked": index + 1, "total": len(rows), "counts": counts}),
                    flush=True,
                )
    return {
        "checked_at": now.isoformat(),
        "current_year": year,
        "checked": len(rows),
        "counts": dict(counts),
        "newly_closed_this_run": newly_closed,
        "sources": {source: dict(values) for source, values in by_source.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse today's completed checks after an interrupted run",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 50000:
        parser.error("--limit must be between 1 and 50000")
    result = asyncio.run(audit(limit=args.limit, resume=args.resume))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
