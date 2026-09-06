import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import SessionLocal, get_db
from app.ecosystem_monitor import collect_organization_programs
from app.models import EcosystemCrawlRun, EcosystemOrganization, EcosystemProgram

router = APIRouter(prefix="/api/ecosystem", tags=["ecosystem"])
_running_tasks: dict[int, asyncio.Task[None]] = {}


class OrganizationItem(BaseModel):
    slug: str
    name: str
    organization_type: str
    summary: str
    website_url: str
    program_url: str | None
    monitored: bool
    last_crawled_at: datetime | None
    fit_score: int
    fit_reason: str
    focus_tags: list[str]
    source_url: str | None
    operating_scale: str | None


class ProgramItem(BaseModel):
    id: int
    organization_slug: str
    organization_name: str
    organization_type: str
    title: str
    url: str
    program_type: str
    summary: str | None
    deadline_text: str | None
    is_open: bool
    first_seen_at: datetime
    last_seen_at: datetime


class ProgramListResponse(BaseModel):
    items: list[ProgramItem]
    total: int
    new_last_7_days: int


class ProgramCrawlRunItem(BaseModel):
    id: int
    organization_slug: str
    organization_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages_visited: int
    programs_found: int
    programs_created: int
    programs_updated: int
    error: str | None


def _organization_item(organization: EcosystemOrganization) -> OrganizationItem:
    return OrganizationItem(
        slug=organization.slug,
        name=organization.name,
        organization_type=organization.organization_type,
        summary=organization.summary,
        website_url=organization.website_url,
        program_url=organization.program_url,
        monitored=organization.enabled and organization.program_url is not None,
        last_crawled_at=organization.last_crawled_at,
        fit_score=organization.fit_score,
        fit_reason=organization.fit_reason,
        focus_tags=organization.focus_tags or [],
        source_url=organization.source_url,
        operating_scale=organization.operating_scale,
    )


def _program_item(row: tuple[EcosystemProgram, EcosystemOrganization]) -> ProgramItem:
    program, organization = row
    return ProgramItem(
        id=program.id,
        organization_slug=organization.slug,
        organization_name=organization.name,
        organization_type=organization.organization_type,
        title=program.title,
        url=program.url,
        program_type=program.program_type,
        summary=program.summary,
        deadline_text=program.deadline_text,
        is_open=program.is_open,
        first_seen_at=program.first_seen_at,
        last_seen_at=program.last_seen_at,
    )


def _run_item(row: tuple[EcosystemCrawlRun, EcosystemOrganization]) -> ProgramCrawlRunItem:
    run, organization = row
    return ProgramCrawlRunItem(
        id=run.id,
        organization_slug=organization.slug,
        organization_name=organization.name,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        pages_visited=run.pages_visited,
        programs_found=run.programs_found,
        programs_created=run.programs_created,
        programs_updated=run.programs_updated,
        error=run.error_log,
    )


async def _run_collection(run_id: int, settings: Settings) -> None:
    with SessionLocal() as session:
        run = session.get(EcosystemCrawlRun, run_id)
        if run is None:
            return
        try:
            await collect_organization_programs(session, settings, run.organization_id, run.id)
        except Exception:
            # The collector persists a safe, bounded failure message in the run record.
            return


def _schedule(run_id: int, settings: Settings) -> None:
    task = asyncio.create_task(_run_collection(run_id, settings))
    _running_tasks[run_id] = task
    task.add_done_callback(lambda _task: _running_tasks.pop(run_id, None))


@router.get("/organizations", response_model=list[OrganizationItem])
def list_organizations(session: Annotated[Session, Depends(get_db)]) -> list[OrganizationItem]:
    organizations = session.scalars(
        select(EcosystemOrganization).order_by(
            EcosystemOrganization.fit_score.desc(), EcosystemOrganization.name
        )
    )
    return [_organization_item(item) for item in organizations]


@router.get("/programs", response_model=ProgramListResponse)
def list_programs(
    session: Annotated[Session, Depends(get_db)], open_only: bool = True, limit: int = 100
) -> ProgramListResponse:
    query = select(EcosystemProgram, EcosystemOrganization).join(EcosystemOrganization)
    if open_only:
        query = query.where(
            EcosystemProgram.is_open.is_(True), EcosystemProgram.is_active.is_(True)
        )
    query = query.order_by(EcosystemProgram.first_seen_at.desc(), EcosystemProgram.id.asc())
    rows = session.execute(query.limit(min(max(limit, 1), 200))).all()
    cutoff = datetime.now(UTC) - timedelta(days=7)
    new_count = (
        session.scalar(
            select(func.count(EcosystemProgram.id)).where(
                EcosystemProgram.is_active.is_(True),
                EcosystemProgram.is_open.is_(True),
                EcosystemProgram.first_seen_at >= cutoff,
            )
        )
        or 0
    )
    return ProgramListResponse(
        items=[_program_item(row) for row in rows], total=len(rows), new_last_7_days=new_count
    )


@router.get("/runs", response_model=list[ProgramCrawlRunItem])
def list_runs(
    session: Annotated[Session, Depends(get_db)], limit: int = 30
) -> list[ProgramCrawlRunItem]:
    rows = session.execute(
        select(EcosystemCrawlRun, EcosystemOrganization)
        .join(EcosystemOrganization)
        .order_by(EcosystemCrawlRun.started_at.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return [_run_item(row) for row in rows]


@router.post(
    "/crawl", response_model=list[ProgramCrawlRunItem], status_code=status.HTTP_202_ACCEPTED
)
async def crawl_programs(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ProgramCrawlRunItem]:
    organizations = session.scalars(
        select(EcosystemOrganization).where(
            EcosystemOrganization.enabled.is_(True), EcosystemOrganization.program_url.is_not(None)
        )
    ).all()
    created: list[tuple[EcosystemCrawlRun, EcosystemOrganization]] = []
    for organization in organizations:
        active = session.scalar(
            select(EcosystemCrawlRun.id).where(
                EcosystemCrawlRun.organization_id == organization.id,
                EcosystemCrawlRun.status == "running",
            )
        )
        if active is not None:
            continue
        run = EcosystemCrawlRun(
            organization_id=organization.id, status="running", started_at=datetime.now(UTC)
        )
        session.add(run)
        session.flush()
        created.append((run, organization))
    session.commit()
    for run, _organization in created:
        _schedule(run.id, settings)
    return [_run_item(row) for row in created]


@router.post(
    "/crawl/{organization_slug}",
    response_model=ProgramCrawlRunItem,
    status_code=status.HTTP_202_ACCEPTED,
)
async def crawl_organization(
    organization_slug: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProgramCrawlRunItem:
    organization = session.scalar(
        select(EcosystemOrganization).where(EcosystemOrganization.slug == organization_slug)
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="organization not found")
    if not organization.enabled or not organization.program_url:
        raise HTTPException(
            status_code=400, detail="organization has no public program page to monitor"
        )
    active = session.scalar(
        select(EcosystemCrawlRun.id).where(
            EcosystemCrawlRun.organization_id == organization.id,
            EcosystemCrawlRun.status == "running",
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="program collection is already running")
    run = EcosystemCrawlRun(
        organization_id=organization.id, status="running", started_at=datetime.now(UTC)
    )
    session.add(run)
    session.commit()
    _schedule(run.id, settings)
    return _run_item((run, organization))
