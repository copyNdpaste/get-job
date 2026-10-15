"""Persistent AI evaluation queue. Only validated, current inputs replace displayed scores."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, load_only

from app.analysis_budget import AnalysisBudgetExceeded, finish_call, reserve_call
from app.config import Settings
from app.db.session import SessionLocal
from app.local_ai import AIUnavailableError, LocalAIClient
from app.models import (
    AIAnalysisDay,
    CandidateProfile,
    Company,
    CrawlRun,
    JobPosting,
    JobScore,
    PreferenceEvaluation,
)
from app.preference_scoring import (
    PROMPT_PATH,
    VERSION,
    Evaluations,
    apply_evaluation,
    candidate_sources,
    input_hash,
    job_context,
    preferences,
    validate_evaluation,
)

LOGGER = logging.getLogger(__name__)


def eligible(now: datetime):
    year = (now + timedelta(hours=9)).year
    start = datetime(year, 1, 1, tzinfo=UTC) - timedelta(hours=9)
    return (
        JobPosting.is_active.is_(True),
        JobPosting.is_primary_posting.is_(True),
        JobPosting.is_hidden.is_(False),
        or_(JobPosting.deadline_at.is_(None), JobPosting.deadline_at >= now),
        or_(JobPosting.posted_at.is_(None), JobPosting.posted_at >= start),
    )


def enqueue(session: Session, settings: Settings, job_ids: set[int] | None = None) -> int:
    if not settings.ai_preference_scoring:
        return 0
    profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if profile is None:
        return 0
    candidate = candidate_sources(profile.profile_json)
    if not candidate:
        return 0
    prefs = preferences(settings.ai_preferences_path)
    now = datetime.now(UTC)
    query = (
        select(JobPosting, Company)
        .join(Company)
        .where(*eligible(now))
        .options(
            load_only(
                JobPosting.id,
                JobPosting.title,
                JobPosting.experience_text,
                JobPosting.location,
                JobPosting.tech_stack,
                JobPosting.employment_type,
                JobPosting.requirements,
                JobPosting.main_tasks,
                JobPosting.preferred_requirements,
                JobPosting.description_text,
            )
        )
    )
    if job_ids is not None:
        if not job_ids:
            return 0
        query = query.where(JobPosting.id.in_(job_ids))
    inserts = []
    for job, company in session.execute(query):
        fingerprint = input_hash(
            candidate, job_context(job, company), prefs, settings.ai_analysis_fast_model
        )
        inserts.append(
            {
                "job_id": job.id,
                "candidate_id": profile.id,
                "input_hash": fingerprint,
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": now,
            }
        )
    insert = sqlite_insert if session.bind.dialect.name == "sqlite" else pg_insert
    for offset in range(0, len(inserts), 100):
        statement = insert(PreferenceEvaluation).values(inserts[offset : offset + 100])
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["job_id", "candidate_id"],
                set_={
                    "input_hash": statement.excluded.input_hash,
                    "status": "pending",
                    "attempts": 0,
                    "next_attempt_at": now,
                    "error_code": None,
                },
                where=(PreferenceEvaluation.status != "running")
                & or_(
                    PreferenceEvaluation.input_hash != statement.excluded.input_hash,
                    PreferenceEvaluation.status == "skipped",
                ),
            )
        )
    session.commit()
    return len(inserts)


def queue_status(session: Session, settings: Settings) -> dict:
    rows = session.execute(
        select(PreferenceEvaluation.status, func.count())
        .join(JobPosting, JobPosting.id == PreferenceEvaluation.job_id)
        .where(*eligible(datetime.now(UTC)))
        .group_by(PreferenceEvaluation.status)
    ).all()
    counts = dict(rows)
    last = session.scalar(select(func.max(PreferenceEvaluation.completed_at)))
    return {
        "enabled": settings.ai_preference_scoring,
        "after_crawl": settings.ai_analysis_after_crawl,
        "model": settings.ai_analysis_fast_model,
        "version": VERSION,
        "counts": counts,
        "last_completed_at": last,
        "total": sum(counts.values()),
        "batch_size": settings.ai_preference_batch_size,
    }


async def run_batch(settings: Settings, *, session_factory=SessionLocal, client=None) -> dict:
    if (
        not settings.ai_preference_scoring
        or not settings.ai_enabled
        or settings.ai_provider == "disabled"
    ):
        return {"outcome": "disabled", "completed": 0}
    now = datetime.now(UTC)
    with session_factory() as session:
        # Let collection finish before comparing jobs or regenerating recommendations.
        if session.scalar(select(CrawlRun.id).where(CrawlRun.status == "running").limit(1)):
            return {"outcome": "collecting", "completed": 0}
        budget = session.get(AIAnalysisDay, now.date())
        if budget and budget.reserved_tokens >= settings.ai_analysis_daily_budget:
            return {"outcome": "budget_limited", "completed": 0}
        session.execute(
            update(PreferenceEvaluation)
            .where(
                PreferenceEvaluation.status == "running",
                PreferenceEvaluation.started_at
                < now - timedelta(seconds=max(600, settings.ai_timeout_seconds * 2)),
            )
            .values(status="pending", next_attempt_at=now)
        )
        tasks = list(
            session.scalars(
                select(PreferenceEvaluation)
                .join(JobPosting)
                .where(
                    *eligible(now),
                    PreferenceEvaluation.status.in_(["pending", "failed", "budget_limited"]),
                    PreferenceEvaluation.next_attempt_at <= now,
                )
                .order_by(
                    PreferenceEvaluation.attempts,
                    PreferenceEvaluation.next_attempt_at,
                    PreferenceEvaluation.job_id.desc(),
                )
                .limit(settings.ai_preference_batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if not tasks:
            session.commit()
            return {"outcome": "idle", "completed": 0}
        keys = [(task.job_id, task.candidate_id, task.input_hash) for task in tasks]
        for task in tasks:
            task.status = "running"
            task.started_at = now
            task.attempts += 1
        session.commit()
        profile = session.get(CandidateProfile, keys[0][1])
        candidate = candidate_sources(profile.profile_json)
        prefs = preferences(settings.ai_preferences_path)
        contexts = {}
        for job_id, _, _ in keys:
            row = session.execute(
                select(JobPosting, Company).join(Company).where(JobPosting.id == job_id)
            ).one()
            contexts[job_id] = job_context(*row)
        data = {"candidate": candidate, "preferences": prefs, "jobs": list(contexts.values())}
        user_text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if len(user_text.encode()) > 150000:
            error_code = "input_too_large"
            reports = None
        else:
            error_code = "invalid_output"
            reports = None
            ai = client or LocalAIClient(settings)
            for attempt in range(2):
                usage = None
                try:
                    usage = reserve_call(
                        session,
                        settings,
                        model=settings.ai_analysis_fast_model,
                        stage="preference_scoring",
                        amount=(len(user_text.encode()) + len(PROMPT_PATH.read_bytes())) // 3
                        + 4096,
                    )
                    completion = await ai.complete(
                        [
                            {"role": "system", "content": PROMPT_PATH.read_text()},
                            {"role": "user", "content": user_text},
                            *(
                                [
                                    {
                                        "role": "user",
                                        "content": (
                                            "이전 출력이 형식 또는 근거 검증을 통과하지 못했습니다."
                                            " 각 공고의 근거 ID만 인용하세요."
                                            " 미확인은 unknown으로 표시하고 JSON 전체를 출력하세요."
                                        ),
                                    }
                                ]
                                if attempt
                                else []
                            ),
                        ],
                        json_mode=True,
                        model=settings.ai_analysis_fast_model,
                        max_output_tokens=4096,
                    )
                    finish_call(session, usage, status="completed", completion=completion)
                    text = (
                        completion.content.strip()
                        .removeprefix("```json")
                        .removeprefix("```")
                        .removesuffix("```")
                        .strip()
                    )
                    parsed = Evaluations.model_validate_json(text)
                    reports = {report.job_id: report for report in parsed.evaluations}
                    if len(reports) != len(parsed.evaluations) or set(reports) != set(contexts):
                        raise ValueError("wrong_job_ids")
                    for job_id, report in reports.items():
                        validate_evaluation(report, candidate, contexts[job_id])
                    actual_model = completion.model
                    break
                except AnalysisBudgetExceeded:
                    reports, error_code = None, "budget_limited"
                    break
                except AIUnavailableError:
                    if usage:
                        finish_call(session, usage, status="unavailable")
                    reports, error_code = None, "model_unavailable"
                    break
                except (ValueError, ValidationError):
                    reports = None
        completed = 0
        for job_id, candidate_id, fingerprint in keys:
            task = session.get(PreferenceEvaluation, (job_id, candidate_id))
            if task is None or task.input_hash != fingerprint:
                continue
            if reports is None:
                task.status = "budget_limited" if error_code == "budget_limited" else "failed"
                task.error_code = error_code
                task.next_attempt_at = (
                    (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    if error_code == "budget_limited"
                    else now + timedelta(seconds=min(3600, 60 * 2 ** min(task.attempts, 6)))
                )
                continue
            job, company = session.execute(
                select(JobPosting, Company).join(Company).where(JobPosting.id == job_id)
            ).one()
            fresh_context = job_context(job, company)
            fresh_candidate = candidate_sources(
                session.get(CandidateProfile, candidate_id).profile_json
            )
            fresh_hash = input_hash(
                fresh_candidate,
                fresh_context,
                preferences(settings.ai_preferences_path),
                settings.ai_analysis_fast_model,
            )
            if fresh_hash != fingerprint:
                task.input_hash, task.status, task.next_attempt_at = fresh_hash, "pending", now
                continue
            if not session.scalar(
                select(JobPosting.id).where(JobPosting.id == job_id, *eligible(datetime.now(UTC)))
            ):
                task.status = "skipped"
                continue
            score = session.scalar(
                select(JobScore).where(
                    JobScore.job_posting_id == job_id, JobScore.candidate_profile_id == candidate_id
                )
            )
            if score is None:
                score = JobScore(
                    job_posting_id=job_id,
                    candidate_profile_id=candidate_id,
                    grade="C",
                    scoring_version="pending",
                    scored_at=now,
                )
                session.add(score)
            apply_evaluation(
                score,
                reports[job_id],
                model=actual_model,
                fingerprint=fingerprint,
                candidate=candidate,
                context=contexts[job_id],
            )
            task.status, task.model = "completed", actual_model
            task.evaluation = reports[job_id].model_dump()
            task.completed_at, task.error_code = datetime.now(UTC), None
            completed += 1
        session.commit()
        if completed:
            from app.daily_recommendations import generate_daily_recommendations

            generate_daily_recommendations(session, settings)
            session.commit()
        return {"outcome": "completed" if reports else error_code, "completed": completed}


async def worker_loop(settings: Settings):
    while True:
        try:

            def refresh_queue():
                with SessionLocal() as session:
                    enqueue(session, settings)

            await asyncio.to_thread(refresh_queue)
            result = await run_batch(settings)
            wait = (
                max(settings.ai_preference_poll_seconds, 300)
                if result["outcome"] == "budget_limited"
                else settings.ai_preference_poll_seconds
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Exception messages/validation details can contain private model input.
            LOGGER.warning("Preference worker retry: %s", type(exc).__name__)
            wait = settings.ai_preference_poll_seconds
        await asyncio.sleep(wait)
