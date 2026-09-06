from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.crawler.normalization import canonicalize_url
from app.models import Application, JobPosting

SUBMITTED_APPLICATION_STATUSES = frozenset(
    {
        "applied",
        "document_passed",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    }
)


def tracked_posting_urls(session: Session, source_id: int) -> list[str]:
    """Return locally tracked public posting URLs without exposing application details."""
    rows = session.execute(
        select(JobPosting.url, Application.status, JobPosting.is_favorite)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(
            JobPosting.source_id == source_id,
            or_(
                JobPosting.is_favorite.is_(True),
                Application.status.in_(SUBMITTED_APPLICATION_STATUSES),
            ),
        )
        .order_by(JobPosting.last_seen_at.asc(), JobPosting.id.asc())
    ).all()
    applied = [url for url, status, _favorite in rows if status in SUBMITTED_APPLICATION_STATUSES]
    favorites = [
        url
        for url, status, favorite in rows
        if favorite and status not in SUBMITTED_APPLICATION_STATUSES
    ]
    return list(dict.fromkeys([*applied, *favorites]))


def prioritize_tracked_urls(urls: Iterable[str], tracked_urls: Iterable[str]) -> list[str]:
    """Move tracked URLs to the front while retaining the source catalog's exact scope."""
    unique_urls = list(dict.fromkeys(urls))
    tracked_keys = {canonicalize_url(url) for url in tracked_urls}
    return sorted(
        unique_urls,
        key=lambda url: 0 if canonicalize_url(url) in tracked_keys else 1,
    )
