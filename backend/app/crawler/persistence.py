from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.company_facts import merge_company_facts
from app.crawler.domain import CollectedJob, UpsertResult
from app.crawler.normalization import canonicalize_url, content_hash, normalize_name, normalize_text
from app.models import Company, JobPosting, JobPostingSnapshot, JobSource


def persist_collected_jobs(
    session: Session, source_name: str, jobs: list[CollectedJob]
) -> dict[str, int]:
    source = session.scalar(select(JobSource).where(JobSource.name == source_name))
    if source is None:
        raise ValueError(f"source is not seeded: {source_name}")
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for job in jobs:
        result = upsert_collected_job(session, source, job)
        counts[result.status] += 1
    return counts


def upsert_collected_job(session: Session, source: JobSource, data: CollectedJob) -> UpsertResult:
    now = datetime.now(UTC)
    company_normalized = normalize_name(data.company_name)
    company = session.scalar(
        select(Company).where(Company.normalized_name == company_normalized).limit(1)
    )
    if company is None:
        company = Company(
            name=data.company_name,
            normalized_name=company_normalized,
            source_urls=[data.url],
        )
        session.add(company)
        session.flush()
    elif data.url not in company.source_urls:
        company.source_urls = [*company.source_urls, data.url]
    merge_company_facts(company, data.company_facts)

    structured = data.structured_content()
    canonical_url = canonicalize_url(data.url)
    normalized_title = normalize_text(data.title).casefold()
    digest_content = {
        key: value
        for key, value in structured.items()
        if key not in {"source_name", "external_job_id", "url"}
    }
    digest_content["canonical_url"] = canonical_url
    digest = content_hash(digest_content)
    is_open_by_deadline = data.deadline_at is None or data.deadline_at >= now
    posting = session.scalar(
        select(JobPosting).where(
            JobPosting.source_id == source.id,
            JobPosting.external_job_id == data.external_job_id,
        )
    )
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(
                JobPosting.source_id == source.id,
                JobPosting.canonical_url == canonical_url,
            )
        )
    if posting is None:
        posting = session.scalar(
            select(JobPosting).where(
                JobPosting.source_id == source.id,
                JobPosting.company_id == company.id,
                JobPosting.normalized_title == normalized_title,
            )
        )
        if posting is not None and data.source_name == "groupby":
            posting.external_job_id = data.external_job_id
    status = "unchanged"
    if posting is None:
        posting = JobPosting(
            source_id=source.id,
            external_job_id=data.external_job_id,
            company_id=company.id,
            title=data.title,
            normalized_title=normalized_title,
            url=data.url,
            canonical_url=canonical_url,
            description_raw=data.description_raw,
            description_text=data.description_text,
            main_tasks=data.main_tasks,
            requirements=data.requirements,
            preferred_requirements=data.preferred_requirements,
            benefits=data.benefits,
            tech_stack=data.tech_stack,
            hiring_process=data.hiring_process,
            has_coding_test=data.has_coding_test,
            interview_count=data.interview_count,
            experience_text=data.experience_text,
            location=data.location,
            employment_type=data.employment_type,
            posted_at=data.posted_at,
            deadline_at=data.deadline_at,
            first_seen_at=now,
            last_seen_at=now,
            last_changed_at=now,
            content_hash=digest,
            crawl_status="success",
            is_active=is_open_by_deadline,
        )
        session.add(posting)
        session.flush()
        status = "created"
    else:
        posting.last_seen_at = now
        posting.is_active = is_open_by_deadline
        if posting.content_hash != digest:
            posting.company_id = company.id
            posting.title = data.title
            posting.normalized_title = normalized_title
            posting.url = data.url
            posting.canonical_url = canonical_url
            posting.description_raw = data.description_raw
            posting.description_text = data.description_text
            posting.main_tasks = data.main_tasks
            posting.requirements = data.requirements
            posting.preferred_requirements = data.preferred_requirements
            posting.benefits = data.benefits
            posting.tech_stack = data.tech_stack
            posting.hiring_process = data.hiring_process
            posting.has_coding_test = data.has_coding_test
            posting.interview_count = data.interview_count
            posting.experience_text = data.experience_text
            posting.location = data.location
            posting.employment_type = data.employment_type
            posting.posted_at = data.posted_at or posting.posted_at
            posting.deadline_at = data.deadline_at
            posting.content_hash = digest
            posting.last_changed_at = now
            status = "updated"

    snapshot_exists = session.scalar(
        select(JobPostingSnapshot.id).where(
            JobPostingSnapshot.job_posting_id == posting.id,
            JobPostingSnapshot.content_hash == digest,
        )
    )
    if snapshot_exists is None:
        session.add(
            JobPostingSnapshot(
                job_posting_id=posting.id,
                content_hash=digest,
                raw_content=data.description_raw,
                structured_content={
                    **structured,
                    "collection_timing": {
                        "observed_at": data.observed_at.isoformat(),
                        "persisted_at": now.isoformat(),
                        "meaning": "detail_parsed_at_not_publication_time",
                    },
                },
                crawled_at=now,
            )
        )
    session.flush()
    return UpsertResult(status=status, job_posting_id=posting.id)
