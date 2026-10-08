"""Summarize observed discovery times without inferring publication from polling."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def build_timing_report(
    jobs: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    *,
    timezone: str = "Asia/Seoul",
) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    grouped_jobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in jobs:
        grouped_jobs[row["source"]].append(row)
    for row in runs:
        grouped_runs[row["source"]].append(row)
    sources = []
    for source in sorted(grouped_jobs.keys() | grouped_runs.keys()):
        discoveries = Counter()
        observed_days: set[str] = set()
        lag_seconds = []
        measured = 0
        persisted_estimates = 0
        samples = []
        source_runs = sorted(grouped_runs[source], key=lambda row: row["started_at"])
        for row in grouped_jobs[source]:
            persisted = aware(row["first_seen_at"])
            timing = (row.get("snapshot") or {}).get("collection_timing", {})
            observed = persisted
            precision = "db_first_saved_at_only"
            try:
                parsed = aware(datetime.fromisoformat(timing["observed_at"]))
                if parsed <= persisted:
                    observed = parsed
                    precision = "detail_parsed_at"
            except (KeyError, ValueError, TypeError):
                pass
            if precision == "detail_parsed_at":
                measured += 1
                lag_seconds.append((persisted - observed).total_seconds())
            else:
                persisted_estimates += 1
            local = observed.astimezone(zone)
            discoveries[f"{local.hour:02d}:00"] += 1
            observed_days.add(local.date().isoformat())
            # This is a sampling reference, never proof that the job was absent then.
            previous = [
                run
                for run in source_runs
                if run["status"] == "succeeded"
                and run["finished_at"] is not None
                and aware(run["finished_at"]) < observed
            ]
            previous_finish = aware(previous[-1]["finished_at"]) if previous else None
            samples.append(
                {
                    "job_id": row["id"],
                    "url": row["url"],
                    "observed_at": local.isoformat(),
                    "first_saved_at": persisted.astimezone(zone).isoformat(),
                    "precision": precision,
                    "source_posted_at": (
                        aware(row["posted_at"]).astimezone(zone).isoformat()
                        if row.get("posted_at")
                        else None
                    ),
                    "previous_successful_scan_finished_at": (
                        previous_finish.astimezone(zone).isoformat() if previous_finish else None
                    ),
                    "hours_since_previous_successful_scan": (
                        round((observed - previous_finish).total_seconds() / 3600, 2)
                        if previous_finish
                        else None
                    ),
                    "initial_or_uncovered": previous_finish is None,
                }
            )
        completed = [run for run in source_runs if run["finished_at"] is not None]
        durations = [
            (aware(run["finished_at"]) - aware(run["started_at"])).total_seconds()
            for run in completed
        ]
        sources.append(
            {
                "source": source,
                "new_source_postings": len(grouped_jobs[source]),
                "detail_parse_timestamps": measured,
                "legacy_save_time_estimates": persisted_estimates,
                "discovery_days": len(observed_days),
                "discoveries_by_observed_hour": dict(sorted(discoveries.items())),
                "scans_by_requested_hour": dict(
                    sorted(
                        Counter(
                            f"{aware(run['started_at']).astimezone(zone).hour:02d}:00"
                            for run in source_runs
                        ).items()
                    )
                ),
                "scan_status_counts": dict(Counter(run["status"] for run in source_runs)),
                "median_queue_and_collection_seconds": median(durations) if durations else None,
                "median_parse_to_save_seconds": median(lag_seconds) if lag_seconds else None,
                "initial_or_uncovered_postings": sum(
                    row["initial_or_uncovered"] for row in samples
                ),
                "schedule_adjustment": {
                    "ready": False,
                    "recommended_times": None,
                    "reason": "fixed_polling_does_not_identify_public_availability_time",
                    "next_step": (
                        "Review at least 14 days of successful scans, excluding initial imports; "
                        "verify source publication timestamp precision or use permitted finer "
                        "availability observations before moving collection slots."
                    ),
                },
                "recent_observations": sorted(
                    samples, key=lambda item: item["observed_at"], reverse=True
                )[:100],
            }
        )
    return {
        "timezone": timezone,
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": sources,
        "limitations": [
            "Discovery is detail parsing time, not platform publication or indexing time.",
            "Historical jobs without timing metadata use DB first-save time as an estimate.",
            "Fixed polling biases hourly discovery counts towards collection times.",
            "A successful scan may be capped; the previous scan is not proof of absence.",
            "Counts are per-source postings; cross-site duplicates are counted separately.",
            "Source posted_at precision and public visibility must be verified before use.",
        ],
    }


def timing_report_from_db(session, *, days: int = 30, timezone: str = "Asia/Seoul"):
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.models import CrawlRun, JobPosting, JobPostingSnapshot, JobSource

    start = datetime.now(UTC) - timedelta(days=days)
    first_snapshots = (
        select(
            JobPostingSnapshot.job_posting_id.label("job_id"),
            func.min(JobPostingSnapshot.id).label("snapshot_id"),
        )
        .group_by(JobPostingSnapshot.job_posting_id)
        .subquery()
    )
    rows = session.execute(
        select(JobPosting, JobSource.name, JobPostingSnapshot.structured_content)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .outerjoin(first_snapshots, first_snapshots.c.job_id == JobPosting.id)
        .outerjoin(JobPostingSnapshot, JobPostingSnapshot.id == first_snapshots.c.snapshot_id)
        .where(JobPosting.first_seen_at >= start)
    ).all()
    run_rows = session.execute(
        select(CrawlRun, JobSource.name)
        .join(JobSource, JobSource.id == CrawlRun.source_id)
        .where(CrawlRun.started_at >= start - timedelta(days=7))
    ).all()
    report = build_timing_report(
        [
            {
                "id": job.id,
                "source": name,
                "url": job.url,
                "first_seen_at": job.first_seen_at,
                "posted_at": job.posted_at,
                "snapshot": snapshot,
            }
            for job, name, snapshot in rows
        ],
        [
            {
                "source": name,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
            }
            for run, name in run_rows
        ],
        timezone=timezone,
    )
    report["window_days"] = days
    return report
