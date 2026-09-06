from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.resume_recommendation import (
    RESUME_VARIANTS_BY_ID,
    resolve_resume_file,
    resume_catalog,
)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.get("")
def list_resumes(
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[dict[str, Any]]:
    return resume_catalog(settings)


@router.get("/{resume_id}/file", response_class=FileResponse)
def resume_file(
    resume_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    if resume_id not in RESUME_VARIANTS_BY_ID:
        raise HTTPException(status_code=404, detail="resume not found")
    path = resolve_resume_file(resume_id, settings)
    if path is None:
        raise HTTPException(status_code=404, detail="local resume file not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
