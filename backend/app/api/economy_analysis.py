from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis_pipeline import PipelineInputError
from app.analysis_service import (
    EconomyAnalysisResponse,
    analyze_batch,
    analyze_collected_job,
    routing_models,
)
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models import AIAnalysisDay, AIAnalysisUsage

router = APIRouter(prefix="/api/ai/analysis", tags=["economy-analysis"])


class BatchRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


@router.get("/usage")
def usage(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    today = datetime.now(UTC).date()
    day = session.get(AIAnalysisDay, today)
    totals = session.execute(
        select(
            func.sum(AIAnalysisUsage.input_tokens),
            func.sum(AIAnalysisUsage.output_tokens),
            func.count(AIAnalysisUsage.id),
            func.count(AIAnalysisUsage.input_tokens),
            func.count(AIAnalysisUsage.output_tokens),
        ).where(AIAnalysisUsage.created_at >= datetime.combine(today, time.min, tzinfo=UTC))
    ).one()
    fast, review = routing_models(settings)
    return {
        "day": today,
        "timezone": "UTC",
        "daily_budget": settings.ai_analysis_daily_budget,
        "reserved_tokens": day.reserved_tokens if day else 0,
        "calls": day.calls if day else 0,
        "reviews": day.reviews if day else 0,
        "input_tokens": totals[0],
        "output_tokens": totals[1],
        "usage_complete": totals[2] == totals[3] == totals[4],
        "fast_model": fast,
        "review_model": review or None,
        "batch_size": settings.ai_analysis_batch_size,
        "after_crawl": settings.ai_analysis_after_crawl,
        "output_limit": settings.ai_analysis_max_output_tokens,
        "output_limit_enforced": settings.ai_provider != "codex",
    }


@router.post("/jobs/{job_id}", response_model=EconomyAnalysisResponse)
async def analyze(
    job_id: int,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    refresh: bool = False,
):
    try:
        return await analyze_collected_job(session, settings, job_id, refresh=refresh)
    except LookupError as exc:
        raise HTTPException(404 if str(exc) == "job not found" else 409, str(exc)) from None
    except PipelineInputError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/batch")
async def batch(
    payload: BatchRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        return await analyze_batch(session, settings, limit=payload.limit)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from None
