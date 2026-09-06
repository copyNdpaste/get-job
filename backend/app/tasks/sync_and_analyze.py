import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.crawler.domain import CollectedJob
from app.crawler.normalization import normalize_text
from app.crawler.persistence import persist_collected_jobs
from app.db.session import SessionLocal
from app.models import Company, JobPosting, JobSource

MAX_BATCH_ROWS = 5_000
MAX_INPUT_BYTES = 20_000_000
UNKNOWN_LOCATION = "미상"

_STRING_LIMITS = {
    "source_name": 100,
    "external_job_id": 255,
    "company_name": 255,
    "title": 500,
    "url": 2_048,
    "experience_text": 500,
    "location": 500,
    "employment_type": 100,
    "salary_text": 500,
}
_LIST_FIELDS = (
    "main_tasks",
    "requirements",
    "preferred_requirements",
    "benefits",
    "tech_stack",
    "hiring_process",
)


@dataclass(frozen=True, slots=True)
class BulkUpsertResult:
    received: int
    created: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class JobStatistics:
    total_postings: int
    by_company: dict[str, int]
    by_location: dict[str, int]


@dataclass(frozen=True, slots=True)
class SyncAndAnalyzeResult:
    upsert: BulkUpsertResult
    statistics: JobStatistics


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = normalize_text(value)
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > _STRING_LIMITS[field]:
        raise ValueError(f"{field} exceeds {_STRING_LIMITS[field]} characters")
    return normalized


def _optional_text(record: Mapping[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    normalized = normalize_text(value)
    if not normalized:
        return None
    if len(normalized) > _STRING_LIMITS[field]:
        raise ValueError(f"{field} exceeds {_STRING_LIMITS[field]} characters")
    return normalized


def _string_list(record: Mapping[str, object], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    if len(value) > 1_000:
        raise ValueError(f"{field} has too many items")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} must be a list of strings")
        text = normalize_text(item)
        if len(text) > 10_000:
            raise ValueError(f"{field} contains an oversized item")
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _optional_bool(record: Mapping[str, object], field: str) -> bool | None:
    value = record.get(field)
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean or null")


def _optional_non_negative_int(record: Mapping[str, object], field: str) -> int | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer or null")
    return value


def _optional_datetime(record: Mapping[str, object], field: str) -> datetime | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime or null") from exc
    else:
        raise ValueError(f"{field} must be an ISO-8601 datetime or null")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _description_raw(record: Mapping[str, object]) -> str:
    value = record.get("description_raw")
    if value is None:
        return json.dumps(dict(record), ensure_ascii=False, sort_keys=True, default=str)
    if not isinstance(value, str):
        raise ValueError("description_raw must be a string or null")
    if len(value) > 2_000_000:
        raise ValueError("description_raw exceeds 2000000 characters")
    return value


def record_to_collected_job(
    record: Mapping[str, object],
    *,
    default_source_name: str | None = None,
) -> CollectedJob:
    """Validate one normalized pipeline record and convert it to the domain model."""
    normalized_record = dict(record)
    if "source_name" not in normalized_record and default_source_name is not None:
        normalized_record["source_name"] = default_source_name
    if "external_job_id" not in normalized_record and "job_id" in normalized_record:
        normalized_record["external_job_id"] = normalized_record["job_id"]
    if "url" not in normalized_record and "job_url" in normalized_record:
        normalized_record["url"] = normalized_record["job_url"]

    source_name = _required_text(normalized_record, "source_name")
    external_job_id = _required_text(normalized_record, "external_job_id")
    company_name = _required_text(normalized_record, "company_name")
    title = _required_text(normalized_record, "title")
    url = _required_text(normalized_record, "url")
    description_text = normalized_record.get("description_text")
    if description_text is None:
        normalized_description = title
    elif isinstance(description_text, str):
        normalized_description = normalize_text(description_text) or title
    else:
        raise ValueError("description_text must be a string or null")
    if len(normalized_description) > 2_000_000:
        raise ValueError("description_text exceeds 2000000 characters")

    list_values = {field: _string_list(normalized_record, field) for field in _LIST_FIELDS}
    return CollectedJob(
        source_name=source_name,
        external_job_id=external_job_id,
        company_name=company_name,
        title=title,
        url=url,
        description_raw=_description_raw(normalized_record),
        description_text=normalized_description,
        main_tasks=list_values["main_tasks"],
        requirements=list_values["requirements"],
        preferred_requirements=list_values["preferred_requirements"],
        benefits=list_values["benefits"],
        tech_stack=list_values["tech_stack"],
        hiring_process=list_values["hiring_process"],
        has_coding_test=_optional_bool(normalized_record, "has_coding_test"),
        interview_count=_optional_non_negative_int(normalized_record, "interview_count"),
        experience_text=_optional_text(normalized_record, "experience_text"),
        location=_optional_text(normalized_record, "location"),
        employment_type=_optional_text(normalized_record, "employment_type"),
        salary_text=_optional_text(normalized_record, "salary_text"),
        posted_at=_optional_datetime(normalized_record, "posted_at"),
        deadline_at=_optional_datetime(normalized_record, "deadline_at"),
    )


def _validate_batch(
    records: Sequence[Mapping[str, object]],
    *,
    default_source_name: str | None,
) -> list[CollectedJob]:
    if len(records) > MAX_BATCH_ROWS:
        raise ValueError(f"a batch may contain at most {MAX_BATCH_ROWS} jobs")
    jobs: list[CollectedJob] = []
    identities: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"jobs[{index}] must be an object")
        try:
            job = record_to_collected_job(
                record,
                default_source_name=default_source_name,
            )
        except ValueError as exc:
            raise ValueError(f"jobs[{index}]: {exc}") from exc
        identity = (job.source_name, job.external_job_id)
        if identity in identities:
            raise ValueError(
                f"jobs[{index}] duplicates source_name/external_job_id: "
                f"{job.source_name}/{job.external_job_id}"
            )
        identities.add(identity)
        jobs.append(job)
    return jobs


def _validate_source_urls(session: Session, jobs: Sequence[CollectedJob]) -> None:
    source_names = {job.source_name for job in jobs}
    sources = {
        source.name: source
        for source in session.scalars(
            select(JobSource).where(
                JobSource.name.in_(source_names),
                JobSource.enabled.is_(True),
            )
        )
    }
    missing = sorted(source_names - sources.keys())
    if missing:
        raise ValueError(
            "enabled job source is not seeded: "
            f"{', '.join(missing)}; run python -m app.seed first"
        )

    for job in jobs:
        job_url = urlsplit(job.url)
        source_url = urlsplit(sources[job.source_name].base_url)
        if (
            job_url.scheme != "https"
            or not job_url.hostname
            or job_url.hostname != source_url.hostname
            or job_url.username
            or job_url.password
            or job_url.port not in {None, 443}
        ):
            raise ValueError(
                f"job URL for {job.source_name} must use the configured HTTPS host "
                f"{source_url.hostname}"
            )


def bulk_upsert_jobs(
    session: Session,
    records: Sequence[Mapping[str, object]],
    *,
    default_source_name: str | None = None,
) -> BulkUpsertResult:
    """Upsert a validated batch using the repository's company/job/snapshot invariants."""
    jobs = _validate_batch(records, default_source_name=default_source_name)
    if not jobs:
        return BulkUpsertResult(received=0, created=0, updated=0, unchanged=0)

    _validate_source_urls(session, jobs)
    grouped: dict[str, list[CollectedJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.source_name].append(job)

    totals = {"created": 0, "updated": 0, "unchanged": 0}
    for source_name in sorted(grouped):
        counts = persist_collected_jobs(session, source_name, grouped[source_name])
        for key in totals:
            totals[key] += counts[key]
    session.flush()
    return BulkUpsertResult(received=len(jobs), **totals)


def analyze_job_statistics(
    session: Session,
    *,
    active_only: bool = True,
) -> JobStatistics:
    """Aggregate posting counts from the database without loading posting bodies."""
    filters = [JobPosting.is_active.is_(True)] if active_only else []
    total = session.scalar(select(func.count(JobPosting.id)).where(*filters)) or 0

    company_rows = session.execute(
        select(Company.name, func.count(JobPosting.id))
        .join(JobPosting, JobPosting.company_id == Company.id)
        .where(*filters)
        .group_by(Company.name)
        .order_by(func.count(JobPosting.id).desc(), Company.name.asc())
    ).all()

    location = func.coalesce(func.nullif(func.trim(JobPosting.location), ""), UNKNOWN_LOCATION)
    location_rows = session.execute(
        select(location, func.count(JobPosting.id))
        .where(*filters)
        .group_by(location)
        .order_by(func.count(JobPosting.id).desc(), location.asc())
    ).all()

    return JobStatistics(
        total_postings=int(total),
        by_company={str(name): int(count) for name, count in company_rows},
        by_location={str(name): int(count) for name, count in location_rows},
    )


def sync_and_analyze(
    records: Sequence[Mapping[str, object]],
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    active_only: bool = True,
    default_source_name: str | None = None,
) -> SyncAndAnalyzeResult:
    """Atomically upsert local pipeline data, then calculate database statistics."""
    with session_factory.begin() as session:
        upsert = bulk_upsert_jobs(
            session,
            records,
            default_source_name=default_source_name,
        )
        statistics = analyze_job_statistics(session, active_only=active_only)
        return SyncAndAnalyzeResult(upsert=upsert, statistics=statistics)


def load_job_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"input file does not exist: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"input file exceeds {MAX_INPUT_BYTES} bytes")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"input file must contain valid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, list):
        raise ValueError("input JSON root must be an array of job objects")
    if len(payload) > MAX_BATCH_ROWS:
        raise ValueError(f"a batch may contain at most {MAX_BATCH_ROWS} jobs")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("input JSON root must be an array of job objects")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-and-analyze",
        description="로컬 JSON 채용 데이터를 DB에 upsert하고 기업별·지역별 통계를 집계합니다.",
    )
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 JSON 배열 파일")
    parser.add_argument(
        "--source",
        help="레코드에 source_name이 없을 때 사용할 seeded source 이름",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="통계에 비활성 공고도 포함합니다.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = load_job_records(args.input)
    result = sync_and_analyze(
        records,
        active_only=not args.include_inactive,
        default_source_name=args.source,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
