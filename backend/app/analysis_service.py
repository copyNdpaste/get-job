import json
from datetime import UTC, datetime
from hashlib import sha256

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis_pipeline import PipelineInputError, prepare_sources
from app.budget_analysis import ECONOMY_VERSION, EconomyReport, run_budget_analysis
from app.config import Settings
from app.local_ai import LocalAIClient
from app.models import CandidateProfile, JobAIAnalysis, JobPosting, JobScore


def routing_models(settings: Settings) -> tuple[str, str]:
    fast = settings.ai_analysis_fast_model.strip()
    # Never inherit an expensive interactive Astra selection for automated Codex work.
    if fast == "auto" and settings.ai_provider == "codex":
        fast = "gpt-5.6-luna"
    return fast, settings.ai_analysis_review_model.strip()


class EconomyAnalysisResponse(EconomyReport):
    provider: str
    model: str
    local_only: bool
    cached: bool
    generated_at: datetime


async def analyze_collected_job(
    session: Session,
    settings: Settings,
    job_id: int,
    *,
    refresh: bool = False,
    allow_review: bool = True,
) -> EconomyAnalysisResponse:
    job = session.get(JobPosting, job_id)
    if job is None:
        raise LookupError("job not found")
    profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if profile is None:
        raise LookupError("candidate profile is not configured")
    profile_id = profile.id
    score = session.scalar(
        select(JobScore).where(
            JobScore.job_posting_id == job.id,
            JobScore.candidate_profile_id == profile_id,
        )
    )
    sources = prepare_sources(
        profile.profile_json,
        {
            "requirements": job.requirements,
            "preferred_requirements": job.preferred_requirements,
            "main_tasks": job.main_tasks,
            "experience": job.experience_text,
        },
    )
    scores = {
        "fit": score.total_fit_score if score else None,
        "application_value": score.application_value_score if score else None,
    }
    fast, review = routing_models(settings)
    if fast == "auto" and settings.ai_allow_remote and settings.ai_provider == "openai-compatible":
        raise PipelineInputError("외부 API는 AI_ANALYSIS_FAST_MODEL에 저비용 모델을 지정해 주세요.")
    client = LocalAIClient(settings)
    # Resolve local auto to an actual model BEFORE constructing the cache key.
    # If offline, deterministic paths still work; no stale auto cache is reused.
    if fast == "auto" and settings.ai_enabled and settings.ai_provider != "disabled":
        status = await client.status(model="auto")
        fast = status.active_model or "auto"
    fingerprint = sha256(
        json.dumps(
            {
                "version": ECONOMY_VERSION,
                "sources": sources,
                "scores": scores,
                "scoring_version": score.scoring_version if score else None,
                "provider": settings.ai_provider,
                "endpoint": settings.ai_base_url,
                "fast": fast,
                "review": review,
                "enabled": settings.ai_enabled,
                "output": settings.ai_analysis_max_output_tokens,
                "prompt_bytes": settings.ai_analysis_prompt_bytes,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()

    def response(report, cached, generated_at):
        return EconomyAnalysisResponse(
            **report.model_dump(),
            provider=settings.ai_provider,
            model=" → ".join(report.models_used) or "rules",
            local_only=not settings.ai_allow_remote,
            cached=cached,
            generated_at=generated_at,
        )

    # Content-addressed lookup also reuses identical postings from another source.
    if not refresh:
        cached = session.scalar(
            select(JobAIAnalysis)
            .where(
                JobAIAnalysis.analysis_type == ECONOMY_VERSION,
                JobAIAnalysis.candidate_profile_id == profile_id,
                JobAIAnalysis.input_hash == fingerprint,
            )
            .order_by(JobAIAnalysis.generated_at.desc())
            .limit(1)
        )
        if cached:
            try:
                report = EconomyReport.model_validate(cached.payload_json)
                return response(report, True, cached.generated_at)
            except ValidationError:
                pass
    report = await run_budget_analysis(
        client,
        session,
        settings,
        sources=sources,
        rule_scores=scores,
        fast_model=fast,
        review_model=review,
        allow_review=allow_review,
    )
    generated_at = datetime.now(UTC)
    # Transient failures must be retriable after budgets, connectivity or models change.
    cacheable_review = (
        report.outcome == "needs_review"
        and report.routing_reason == "ambiguous_matches"
        and not review
    )
    if report.outcome in {"validated", "rules_only"} or cacheable_review:
        identity = select(JobAIAnalysis).where(
            JobAIAnalysis.job_posting_id == job_id,
            JobAIAnalysis.candidate_profile_id == profile_id,
            JobAIAnalysis.analysis_type == ECONOMY_VERSION,
            JobAIAnalysis.provider == settings.ai_provider,
            JobAIAnalysis.model == fast,
        )
        row = session.scalar(identity)
        if row is None:
            row = JobAIAnalysis(
                job_posting_id=job_id,
                candidate_profile_id=profile_id,
                analysis_type=ECONOMY_VERSION,
                provider=settings.ai_provider,
                model=fast,
            )
            session.add(row)
        row.input_hash = fingerprint
        row.payload_json = report.model_dump(mode="json")
        row.generated_at = generated_at
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if session.scalar(identity) is None:
                raise
    return response(report, False, generated_at)


async def analyze_batch(
    session: Session,
    settings: Settings,
    *,
    limit: int | None = None,
    job_ids: set[int] | None = None,
) -> dict:
    profile_id = session.scalar(select(CandidateProfile.id).order_by(CandidateProfile.id).limit(1))
    if profile_id is None:
        raise LookupError("candidate profile is not configured")
    cap = min(limit or settings.ai_analysis_batch_size, settings.ai_analysis_batch_size)
    query = (
        select(JobPosting.id)
        .join(JobScore, JobScore.job_posting_id == JobPosting.id)
        .where(
            JobPosting.is_active.is_(True),
            JobPosting.is_hidden.is_(False),
            JobScore.candidate_profile_id == profile_id,
            JobScore.grade != "Excluded",
            JobScore.total_fit_score >= settings.ai_analysis_min_fit,
        )
        .order_by(JobScore.application_value_score.desc(), JobPosting.id)
    )
    if job_ids is not None:
        query = query.where(JobPosting.id.in_(job_ids))
    # Scan a bounded window beyond the first page so cached top jobs don't starve new ones.
    candidates = list(session.scalars(query.limit(min(cap * 20, 1000))))
    results = []
    reviews = 0
    fresh = 0
    calls = 0
    reserved = 0
    for job_id in candidates:
        try:
            result = await analyze_collected_job(
                session,
                settings,
                job_id,
                allow_review=reviews < settings.ai_analysis_batch_reviews,
            )
        except (ValueError, LookupError):
            results.append({"job_id": job_id, "outcome": "invalid_input", "cached": False})
            fresh += 1
        else:
            results.append({"job_id": job_id, "outcome": result.outcome, "cached": result.cached})
            if not result.cached:
                fresh += 1
                reviews += sum(step.name == "review" for step in result.steps)
                calls += result.model_calls
                reserved += result.reserved_tokens
            if result.outcome in {"budget_limited", "unavailable"}:
                break
        if fresh >= cap:
            break
    return {
        "items": results,
        "fresh": fresh,
        "cached": sum(r["cached"] for r in results),
        "model_calls": calls,
        "reviews": reviews,
        "reserved_tokens": reserved,
        "scanned": len(results),
    }
