from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.company_enrichment import enrich_company_facts
from app.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.post("/enrich")
async def enrich_companies(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return await enrich_company_facts(session, settings)
