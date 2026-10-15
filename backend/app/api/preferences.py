from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.preference_worker import enqueue, queue_status, run_batch

router = APIRouter(prefix="/api/ai/preferences", tags=["preference-scoring"])


@router.get("/status")
def status(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return queue_status(session, settings)


@router.post("/enqueue")
def schedule(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    if not settings.ai_preference_scoring:
        raise HTTPException(409, "AI 선호 조건 평가가 비활성화되어 있습니다.")
    return {"eligible": enqueue(session, settings), **queue_status(session, settings)}


@router.post("/batch")
async def batch(settings: Annotated[Settings, Depends(get_settings)]):
    return await run_batch(settings)
