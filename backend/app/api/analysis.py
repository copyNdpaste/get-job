import asyncio
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis_pipeline import (
    PIPELINE_VERSION,
    PipelineInputError,
    PipelineReport,
    prepare_sources,
    run_analysis_pipeline,
)
from app.config import Settings, get_settings
from app.db.session import get_db
from app.local_ai import AIUnavailableError, LocalAIClient
from app.models import CandidateProfile, Company, JobAIAnalysis, JobPosting, JobScore

router = APIRouter(prefix="/api/ai", tags=["analysis-pipeline"])
# Bound concurrent multi-call runs within each backend worker.
_slots = asyncio.Semaphore(2)


class AnalysisResponse(PipelineReport):
    provider: str
    model: str
    local_only: bool
    cached: bool
    generated_at: datetime


@router.post("/jobs/{job_id}/analysis", response_model=AnalysisResponse)
async def analyze_job(
    job_id: int,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    model: Annotated[str | None, Query(max_length=120)] = None,
    refresh: bool = False,
) -> AnalysisResponse:
    if not settings.ai_enabled or settings.ai_provider == "disabled":
        raise HTTPException(503, "AI 기능이 비활성화되어 있습니다.")
    row = session.execute(
        select(JobPosting, Company, JobScore)
        .join(Company, Company.id == JobPosting.company_id)
        .outerjoin(JobScore, JobScore.job_posting_id == JobPosting.id)
        .where(JobPosting.id == job_id)
    ).first()
    if row is None:
        raise HTTPException(404, "job not found")
    job, _company, score = row
    profile = (
        session.get(CandidateProfile, score.candidate_profile_id) if score else
        session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    )
    if profile is None:
        raise HTTPException(409, "candidate profile is not configured")
    try:
        sources = prepare_sources(profile.profile_json, {
            "requirements": job.requirements,
            "preferred_requirements": job.preferred_requirements,
            "main_tasks": job.main_tasks,
            "experience": job.experience_text,
        })
    except PipelineInputError as exc:
        raise HTTPException(422, str(exc)) from None
    rule_scores = {
        "fit": score.total_fit_score if score else None,
        "application_value": score.application_value_score if score else None,
    }
    client = LocalAIClient(settings)
    status = await client.status(model=model)
    if not status.available or not status.active_model:
        raise HTTPException(503, status.message)
    active_model = status.active_model
    input_hash = sha256(json.dumps({
        "version": PIPELINE_VERSION,
        "sources": sources,
        "rule_scores": rule_scores,
        "scoring_version": score.scoring_version if score else None,
        "endpoint": settings.ai_base_url,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    identity = select(JobAIAnalysis).where(
        JobAIAnalysis.job_posting_id == job.id,
        JobAIAnalysis.candidate_profile_id == profile.id,
        JobAIAnalysis.analysis_type == PIPELINE_VERSION,
        JobAIAnalysis.provider == settings.ai_provider,
        JobAIAnalysis.model == active_model,
    )

    def response(report, generated_at, cached):
        return AnalysisResponse(
            **report.model_dump(), provider=settings.ai_provider, model=active_model,
            local_only=not settings.ai_allow_remote, cached=cached, generated_at=generated_at,
        )

    cached_row = session.scalar(identity)
    if not refresh and cached_row is not None and cached_row.input_hash == input_hash:
        try:
            report = PipelineReport.model_validate(cached_row.payload_json)
            return response(report, cached_row.generated_at, True)
        except ValidationError:
            pass
    if _slots.locked():
        raise HTTPException(429, "분석이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
    async with _slots:
        try:
            report = await run_analysis_pipeline(
                client, model=active_model, sources=sources, rule_scores=rule_scores,
            )
        except AIUnavailableError as exc:
            raise HTTPException(503, str(exc)) from None

    generated_at = datetime.now(UTC)
    values = {
        "input_hash": input_hash, "payload_json": report.model_dump(mode="json"),
        "generated_at": generated_at,
    }
    if cached_row is None:
        session.add(JobAIAnalysis(
            job_posting_id=job.id, candidate_profile_id=profile.id,
            analysis_type=PIPELINE_VERSION, provider=settings.ai_provider,
            model=active_model, **values,
        ))
    else:
        for key, value in values.items():
            setattr(cached_row, key, value)
    try:
        session.commit()
    except IntegrityError:
        # Concurrent requests can finish the same identity; return this valid result
        # while leaving the other request's committed cache intact.
        session.rollback()
    return response(report, generated_at, False)
