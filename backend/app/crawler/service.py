from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crawler.adapters import POLICIES, get_adapter, validate_source_url
from app.crawler.domain import CollectedJob
from app.crawler.http import CachedHttpClient
from app.crawler.persistence import upsert_collected_job
from app.crawler.relevance import assess_relevance
from app.crawler.tracked import prioritize_tracked_urls
from app.models import CrawlRun, JobPosting, JobSource


@dataclass(slots=True)
class CrawlSummary:
    source: str
    pages_visited: int = 0
    jobs_found: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    jobs_skipped: int = 0
    jobs_failed: int = 0


def deactivate_out_of_scope(session: Session, source_name: str) -> int:
    postings = session.scalars(
        select(JobPosting)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .where(JobSource.name == source_name, JobPosting.is_active.is_(True))
    )
    deactivated = 0
    for posting in postings:
        if not assess_relevance(
            posting.title,
            posting.description_text or "",
            posting.experience_text,
            posting.employment_type,
        ).included:
            posting.is_active = False
            deactivated += 1
    session.flush()
    return deactivated


def deactivate_not_seen_since(session: Session, source_name: str, seen_since: datetime) -> int:
    """Close stale rows only after a complete, successful public catalog scan."""
    postings = session.scalars(
        select(JobPosting)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .where(
            JobSource.name == source_name,
            JobPosting.is_active.is_(True),
            JobPosting.last_seen_at < seen_since,
        )
    )
    deactivated = 0
    for posting in postings:
        posting.is_active = False
        deactivated += 1
    session.flush()
    return deactivated


async def collect_http(
    session: Session,
    settings: Settings,
    source_name: str,
    *,
    urls: list[str] | None = None,
    priority_urls: list[str] | None = None,
    max_jobs: int = 50,
    crawl_run: CrawlRun | None = None,
) -> CrawlSummary:
    policy = POLICIES[source_name]
    if policy.collection_mode == "manual_html":
        raise ValueError(f"{source_name} permits manual HTML import only")
    if policy.collection_mode in {"browser", "browser_url"}:
        raise ValueError(f"{source_name} requires browser-assisted collection")
    if not urls and policy.collection_mode == "url_import":
        raise ValueError(f"{source_name} requires one or more public job URLs")

    source = session.scalar(select(JobSource).where(JobSource.name == source_name))
    if source is None:
        raise ValueError(f"source is not seeded: {source_name}")
    run = crawl_run
    if run is None:
        run = CrawlRun(source_id=source.id, started_at=datetime.now(UTC), status="running")
        session.add(run)
        session.flush()
    summary = CrawlSummary(source=source_name)
    errors: list[str] = []
    adapter = get_adapter(source_name)
    expected_host = urlsplit(policy.base_url).hostname
    if expected_host is None:
        raise ValueError(f"source has an invalid base URL: {source_name}")

    try:
        async with CachedHttpClient(
            cache_dir=settings.crawler_cache_dir,
            user_agent=settings.crawler_user_agent,
            delay_min_seconds=settings.crawler_delay_min_seconds,
            delay_max_seconds=settings.crawler_delay_max_seconds,
        ) as client:
            detail_urls = list(urls or [])
            if not detail_urls:
                for list_url in policy.list_urls:
                    html = await client.get(
                        list_url, force_refresh=True, expected_host=expected_host
                    )
                    summary.pages_visited += 1
                    detail_urls.extend(adapter.listing_urls(html, list_url))
            detail_urls = prioritize_tracked_urls(detail_urls, priority_urls or [])
            detail_urls = [validate_source_url(source_name, url) for url in detail_urls]
            summary.jobs_found = len(detail_urls)
            run.jobs_found = summary.jobs_found
            run.pages_visited = summary.pages_visited
            session.commit()
            matched_jobs = 0
            exhausted_catalog = True
            for index, url in enumerate(detail_urls):
                try:
                    html = await client.get(url, expected_host=expected_host)
                    summary.pages_visited += 1
                    data = adapter.parse_detail(html, url)
                    decision = assess_relevance(
                        data.title,
                        data.description_text,
                        data.experience_text,
                        data.employment_type,
                    )
                    if not decision.included:
                        summary.jobs_skipped += 1
                        continue
                    matched_jobs += 1
                    result = upsert_collected_job(session, source, data)
                    if result.status == "created":
                        summary.jobs_created += 1
                    elif result.status == "updated":
                        summary.jobs_updated += 1
                    if matched_jobs >= max_jobs:
                        exhausted_catalog = index + 1 >= len(detail_urls)
                        break
                except Exception as exc:  # continue the run and retain per-job failure evidence
                    summary.jobs_failed += 1
                    errors.append(f"{url}: {exc}")
                finally:
                    if (index + 1) % 10 == 0:
                        run.pages_visited = summary.pages_visited
                        run.jobs_created = summary.jobs_created
                        run.jobs_updated = summary.jobs_updated
                        run.jobs_failed = summary.jobs_failed
                        session.commit()
        run.status = "partial" if errors else "succeeded"
        if not urls and detail_urls and exhausted_catalog and not errors:
            deactivate_not_seen_since(session, source_name, run.started_at)
    except Exception as exc:
        run.status = "failed"
        errors.append(str(exc))
        raise
    finally:
        finished = datetime.now(UTC)
        run.finished_at = finished
        run.pages_visited = summary.pages_visited
        run.jobs_found = summary.jobs_found
        run.jobs_created = summary.jobs_created
        run.jobs_updated = summary.jobs_updated
        run.jobs_failed = summary.jobs_failed
        run.error_log = "\n".join(errors) or None
        source.last_crawled_at = finished
        session.flush()
    return summary


def import_html(
    session: Session, source_name: str, html: str, url: str
) -> tuple[CollectedJob, str]:
    validate_source_url(source_name, url)
    source = session.scalar(select(JobSource).where(JobSource.name == source_name))
    if source is None:
        raise ValueError(f"source is not seeded: {source_name}")
    data = get_adapter(source_name).parse_detail(html, url)
    decision = assess_relevance(
        data.title,
        data.description_text,
        data.experience_text,
        data.employment_type,
    )
    if not decision.included:
        raise ValueError(f"job is outside target developer roles: {', '.join(decision.reasons)}")
    result = upsert_collected_job(session, source, data)
    return data, result.status
