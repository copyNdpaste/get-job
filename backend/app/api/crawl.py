import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_service import analyze_batch
from app.config import Settings, get_settings
from app.crawler.adapters import validate_source_url
from app.crawler.approved_api import collect_saramin_api
from app.crawler.browser_groupby import collect_groupby_browser
from app.crawler.browser_urls import collect_browser_urls
from app.crawler.direct_ats import collect_public_ats, collect_rendered_ats
from app.crawler.job_provider_fetcher import collect_jobplanet_pages
from app.crawler.jobplanet_fetcher import JobPlanetApiClient
from app.crawler.persistence import persist_collected_jobs
from app.crawler.service import (
    collect_http,
    deactivate_not_seen_since,
    deactivate_out_of_scope,
    import_html,
)
from app.crawler.tracked import tracked_posting_urls
from app.db.session import SessionLocal, get_db
from app.deduplication import refresh_duplicate_groups
from app.direct_ats_catalog import PUBLIC_API_ATS, PUBLIC_BOARD_ATS, load_direct_ats_boards
from app.models import Company, CrawlRun, JobPosting, JobSource
from app.scoring import score_jobs

router = APIRouter(prefix="/api/crawl", tags=["crawl"])

AUTOMATIC_SOURCES = (
    "demoday",
    "groupby",
    "wanted",
    "remember",
    "jumpit",
    "rallit",
    "jobplanet",
    "saramin",
    "greenhouse",
    "lever",
    "ashby",
    "greeting",
    "ninehire",
)
_running_tasks: dict[int, asyncio.Task[None]] = {}
_batch_tasks: set[asyncio.Task[None]] = set()
_collection_slots: asyncio.Semaphore | None = None
_collection_slots_loop: asyncio.AbstractEventLoop | None = None
_collection_slots_limit: int | None = None


class CrawlRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=5000)
    max_jobs: int = Field(default=500, ge=1, le=5000)
    headless: bool = False

    @field_validator("urls")
    @classmethod
    def validate_url_lengths(cls, values: list[str]) -> list[str]:
        if any(len(value) > 2048 for value in values):
            raise ValueError("each URL must be at most 2048 characters")
        return values


class RocketPunchImportRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)
    html: str = Field(min_length=20, max_length=2_000_000)


class CrawlRunResponse(BaseModel):
    id: int
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages_visited: int
    jobs_found: int
    jobs_created: int
    jobs_updated: int
    jobs_failed: int
    error: str | None


class CrawlResultItem(BaseModel):
    id: int
    title: str
    company: str
    url: str
    status: str


def _run_response(run: CrawlRun, source_name: str) -> CrawlRunResponse:
    return CrawlRunResponse(
        id=run.id,
        source=source_name,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        pages_visited=run.pages_visited,
        jobs_found=run.jobs_found,
        jobs_created=run.jobs_created,
        jobs_updated=run.jobs_updated,
        jobs_failed=run.jobs_failed,
        error=run.error_log,
    )


def _create_run(session: Session, source_name: str) -> tuple[CrawlRun, JobSource]:
    source = session.scalar(select(JobSource).where(JobSource.name == source_name))
    if source is None or not source.enabled:
        raise ValueError(f"source is not available: {source_name}")
    active = session.scalar(
        select(CrawlRun.id).where(
            CrawlRun.source_id == source.id,
            CrawlRun.status == "running",
        )
    )
    if active is not None:
        raise ValueError(f"{source_name} collection is already running")
    run = CrawlRun(source_id=source.id, started_at=datetime.now(UTC), status="running")
    session.add(run)
    session.flush()
    return run, source


async def _run_collection(
    run_id: int,
    source_name: str,
    payload: CrawlRequest,
    settings: Settings,
) -> None:
    with SessionLocal() as session:
        run = session.get(CrawlRun, run_id)
        if run is None:
            return
        try:
            priority_urls = tracked_posting_urls(session, run.source_id)
            if source_name == "groupby":
                progress = {"visited": 0, "found": 0, "failed": 0}
                discovery_complete = False

                def update_groupby_discovery(complete: bool, warning: str | None) -> None:
                    nonlocal discovery_complete
                    discovery_complete = complete
                    run.error_log = warning

                def update_groupby_progress(visited: int, found: int, failed: int) -> None:
                    progress.update(visited=visited, found=found, failed=failed)
                    run.pages_visited = visited
                    run.jobs_found = found
                    run.jobs_failed = failed
                    session.commit()

                jobs = await collect_groupby_browser(
                    max_jobs=payload.max_jobs,
                    headless=payload.headless,
                    delay_min_seconds=settings.crawler_delay_min_seconds,
                    user_agent=settings.crawler_user_agent,
                    priority_urls=priority_urls,
                    on_progress=update_groupby_progress,
                    on_discovery=update_groupby_discovery,
                )
                counts = persist_collected_jobs(session, source_name, jobs)
                run.jobs_created = counts["created"]
                run.jobs_updated = counts["updated"]
                run.status = "partial" if run.jobs_failed or not discovery_complete else "succeeded"
                if (
                    discovery_complete
                    and progress["found"] > 0
                    and progress["visited"] >= progress["found"]
                    and progress["failed"] == 0
                ):
                    deactivate_not_seen_since(session, source_name, run.started_at)
            elif source_name in {"wanted", "remember"}:
                progress = {"visited": 0, "found": 0, "failed": 0}

                def update_browser_progress(visited: int, found: int, failed: int) -> None:
                    progress.update(visited=visited, found=found, failed=failed)
                    run.pages_visited = visited
                    run.jobs_found = found
                    run.jobs_failed = failed
                    session.commit()

                jobs = await collect_browser_urls(
                    source_name,
                    payload.urls or None,
                    profile_dir=f"playwright-profile/{source_name}",
                    max_jobs=payload.max_jobs,
                    headless=payload.headless,
                    delay_min_seconds=settings.crawler_delay_min_seconds,
                    priority_urls=priority_urls,
                    on_progress=update_browser_progress,
                )
                counts = persist_collected_jobs(session, source_name, jobs)
                run.jobs_created = counts["created"]
                run.jobs_updated = counts["updated"]
                run.status = "partial" if run.jobs_failed else "succeeded"
                if (
                    0 < progress["found"] < payload.max_jobs
                    and progress["visited"] >= progress["found"]
                    and progress["failed"] == 0
                ):
                    deactivate_not_seen_since(session, source_name, run.started_at)
            elif source_name == "saramin":
                progress = {"visited": 0, "found": 0, "failed": 0}

                def update_saramin_progress(visited: int, found: int, failed: int) -> None:
                    progress.update(visited=visited, found=found, failed=failed)
                    run.pages_visited = visited
                    run.jobs_found = found
                    run.jobs_failed = failed
                    session.commit()

                if settings.saramin_api_key is None:
                    raise ValueError("SARAMIN_API_KEY가 설정되지 않았습니다")
                jobs = await collect_saramin_api(
                    settings.saramin_api_key.get_secret_value(),
                    max_jobs=payload.max_jobs,
                    delay_min_seconds=settings.crawler_delay_min_seconds,
                    user_agent=settings.crawler_user_agent,
                    on_progress=update_saramin_progress,
                )
                counts = persist_collected_jobs(session, source_name, jobs)
                run.jobs_created = counts["created"]
                run.jobs_updated = counts["updated"]
                run.status = "partial" if run.jobs_failed else "succeeded"
                if progress["found"] > 0 and progress["failed"] == 0:
                    deactivate_not_seen_since(session, source_name, run.started_at)
            elif source_name == "jobplanet":
                progress = {"visited": 0, "found": 0, "failed": 0}

                def update_jobplanet_progress(pages: int, found: int, failed: int) -> None:
                    progress.update(visited=pages, found=found, failed=failed)
                    run.pages_visited = pages
                    run.jobs_found = found
                    run.jobs_failed = failed
                    session.commit()

                jobs = await collect_jobplanet_pages(
                    JobPlanetApiClient(),
                    max_jobs=payload.max_jobs,
                    delay_min_seconds=settings.crawler_delay_min_seconds,
                    on_progress=update_jobplanet_progress,
                )
                counts = persist_collected_jobs(session, source_name, jobs)
                run.pages_visited = progress["visited"]
                run.jobs_found = progress["found"]
                run.jobs_created = counts["created"]
                run.jobs_updated = counts["updated"]
                run.status = "partial" if run.jobs_failed else "succeeded"
            elif source_name in PUBLIC_API_ATS | PUBLIC_BOARD_ATS:
                progress = {"visited": 0, "found": 0, "failed": 0}

                def update_ats_progress(visited: int, found: int, failed: int) -> None:
                    progress.update(visited=visited, found=found, failed=failed)
                    run.pages_visited = visited
                    run.jobs_found = found
                    run.jobs_failed = failed
                    session.commit()

                boards = load_direct_ats_boards(settings.direct_ats_board_path)
                if source_name in PUBLIC_API_ATS:
                    jobs = await collect_public_ats(
                        source_name,
                        boards,
                        max_jobs=payload.max_jobs,
                        delay_min_seconds=settings.crawler_delay_min_seconds,
                        user_agent=settings.crawler_user_agent,
                        priority_urls=priority_urls,
                        on_progress=update_ats_progress,
                    )
                else:
                    jobs = await collect_rendered_ats(
                        source_name,
                        boards,
                        max_jobs=payload.max_jobs,
                        headless=payload.headless,
                        delay_min_seconds=settings.crawler_delay_min_seconds,
                        user_agent=settings.crawler_user_agent,
                        priority_urls=priority_urls,
                        on_progress=update_ats_progress,
                    )
                counts = persist_collected_jobs(session, source_name, jobs)
                run.jobs_created = counts["created"]
                run.jobs_updated = counts["updated"]
                run.status = "partial" if run.jobs_failed else "succeeded"
                if (
                    progress["found"] > 0
                    and progress["visited"] >= progress["found"]
                    and progress["failed"] == 0
                ):
                    deactivate_not_seen_since(session, source_name, run.started_at)
            else:
                await collect_http(
                    session,
                    settings,
                    source_name,
                    urls=payload.urls or None,
                    max_jobs=payload.max_jobs,
                    crawl_run=run,
                    priority_urls=priority_urls,
                )
            deactivate_out_of_scope(session, source_name)
            score_candidates = select(JobPosting.id).where(
                JobPosting.source_id == run.source_id,
                (
                    JobPosting.last_seen_at
                    if source_name == "jobplanet"
                    else JobPosting.first_seen_at
                )
                >= run.started_at,
            )
            score_job_ids = set(session.scalars(score_candidates))
            score_jobs(
                session,
                job_ids=score_job_ids,
                skip_existing=source_name != "jobplanet",
            )
            if source_name == "jobplanet":
                refresh_duplicate_groups(session)
            run.finished_at = datetime.now(UTC)
            source = session.get(JobSource, run.source_id)
            if source is not None:
                source.last_crawled_at = run.finished_at
            session.commit()
            if settings.ai_analysis_after_crawl and score_job_ids:
                try:
                    await analyze_batch(session, settings, job_ids=score_job_ids)
                except Exception:
                    # AI enrichment is optional; committed crawl data remains usable.
                    session.rollback()
        except Exception as exc:
            session.rollback()
            failed_run = session.get(CrawlRun, run_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.finished_at = datetime.now(UTC)
                failed_run.error_log = str(exc)[:4000]
                session.commit()


def _get_collection_slots(limit: int) -> asyncio.Semaphore:
    global _collection_slots, _collection_slots_limit, _collection_slots_loop

    loop = asyncio.get_running_loop()
    if (
        _collection_slots is None
        or _collection_slots_loop is not loop
        or _collection_slots_limit != limit
    ):
        _collection_slots = asyncio.Semaphore(limit)
        _collection_slots_loop = loop
        _collection_slots_limit = limit
    return _collection_slots


async def _run_collection_limited(
    run_id: int,
    source_name: str,
    payload: CrawlRequest,
    settings: Settings,
) -> None:
    async with _get_collection_slots(settings.crawler_max_concurrency):
        await _run_collection(run_id, source_name, payload, settings)


def schedule_collection(
    run_id: int, source_name: str, payload: CrawlRequest, settings: Settings
) -> asyncio.Task[None]:
    task = asyncio.create_task(_run_collection_limited(run_id, source_name, payload, settings))
    _running_tasks[run_id] = task
    task.add_done_callback(lambda _task: _running_tasks.pop(run_id, None))
    return task


async def _finalize_collection_batch(tasks: list[asyncio.Task[None]]) -> None:
    await asyncio.gather(*tasks, return_exceptions=True)
    with SessionLocal.begin() as session:
        refresh_duplicate_groups(session)


def schedule_batch_finalization(tasks: list[asyncio.Task[None]]) -> None:
    batch_task = asyncio.create_task(_finalize_collection_batch(tasks))
    _batch_tasks.add(batch_task)
    batch_task.add_done_callback(_batch_tasks.discard)


def _recover_orphaned_runs(session: Session) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=30)
    orphaned = session.scalars(
        select(CrawlRun).where(
            CrawlRun.status == "running",
            CrawlRun.started_at < cutoff,
        )
    )
    changed = False
    for run in orphaned:
        if run.id in _running_tasks:
            continue
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error_log = "백엔드 재시작으로 중단됨 — 다시 수집해 주세요."
        changed = True
    if changed:
        session.commit()


@router.get("/runs", response_model=list[CrawlRunResponse])
def list_runs(
    session: Annotated[Session, Depends(get_db)], limit: int = 50
) -> list[CrawlRunResponse]:
    _recover_orphaned_runs(session)
    rows = session.execute(
        select(CrawlRun, JobSource.name)
        .join(JobSource, JobSource.id == CrawlRun.source_id)
        .order_by(CrawlRun.started_at.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return [_run_response(run, source_name) for run, source_name in rows]


@router.get("/runs/{run_id}/results", response_model=list[CrawlResultItem])
def crawl_run_results(
    run_id: int, session: Annotated[Session, Depends(get_db)]
) -> list[CrawlResultItem]:
    run = session.get(CrawlRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="crawl run not found")
    finished_at = run.finished_at or datetime.now(UTC)
    rows = session.execute(
        select(JobPosting, Company)
        .join(Company, Company.id == JobPosting.company_id)
        .where(
            JobPosting.source_id == run.source_id,
            JobPosting.last_seen_at >= run.started_at,
            JobPosting.last_seen_at <= finished_at,
            JobPosting.is_active.is_(True),
        )
        .order_by(JobPosting.first_seen_at.desc(), JobPosting.id.desc())
        .limit(1000)
    ).all()
    return [
        CrawlResultItem(
            id=job.id,
            title=job.title,
            company=company.name,
            url=job.url,
            status=(
                "created"
                if job.first_seen_at >= run.started_at
                else "updated"
                if job.last_changed_at >= run.started_at
                else "seen"
            ),
        )
        for job, company in rows
    ]


@router.post("/all", response_model=list[CrawlRunResponse], status_code=status.HTTP_202_ACCEPTED)
async def crawl_all(
    payload: CrawlRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[CrawlRunResponse]:
    if payload.urls:
        raise HTTPException(status_code=400, detail="/all does not accept source-specific URLs")
    created: list[tuple[CrawlRun, str]] = []
    try:
        configured_sources = tuple(
            source_name
            for source_name in AUTOMATIC_SOURCES
            if (source_name != "saramin" or settings.saramin_api_key is not None)
        )
        for source_name in configured_sources:
            run, source = _create_run(session, source_name)
            created.append((run, source.name))
        session.commit()
        tasks = [
            schedule_collection(run.id, source_name, payload, settings)
            for run, source_name in created
        ]
        schedule_batch_finalization(tasks)
        return [_run_response(run, source_name) for run, source_name in created]
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/rocketpunch/import")
def import_rocketpunch(
    payload: RocketPunchImportRequest,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        data, save_status = import_html(session, "rocketpunch", payload.html, payload.url)
        job_id = session.scalar(
            select(JobPosting.id)
            .join(JobSource, JobSource.id == JobPosting.source_id)
            .where(
                JobSource.name == "rocketpunch",
                JobPosting.external_job_id == data.external_job_id,
            )
        )
        analyzed = score_jobs(
            session,
            job_ids={job_id} if save_status == "created" and job_id is not None else set(),
            skip_existing=True,
        )
        session.commit()
        return {
            "source": "rocketpunch",
            "title": data.title,
            "status": save_status,
            "analyzed": analyzed,
        }
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{source_name}", response_model=CrawlRunResponse, status_code=status.HTTP_202_ACCEPTED
)
async def crawl_source(
    source_name: str,
    payload: CrawlRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> CrawlRunResponse:
    if source_name == "rocketpunch":
        raise HTTPException(
            status_code=400,
            detail="rocketpunch only supports saved HTML import (GUI or import-html CLI)",
        )
    if source_name not in AUTOMATIC_SOURCES:
        raise HTTPException(status_code=400, detail=f"unsupported automatic source: {source_name}")
    if source_name == "saramin" and settings.saramin_api_key is None:
        raise HTTPException(
            status_code=409,
            detail="사람인 공식 API 승인 후 로컬 .env에 SARAMIN_API_KEY를 설정해 주세요.",
        )
    try:
        if source_name in {"saramin", "jobplanet"} and payload.urls:
            raise ValueError(f"{source_name} API 수집은 임의 URL을 받지 않습니다")
        for url in payload.urls:
            validate_source_url(source_name, url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        run, source = _create_run(session, source_name)
        session.commit()
        schedule_collection(run.id, source_name, payload, settings)
        response.headers["Location"] = f"/api/crawl/runs?run_id={run.id}"
        return _run_response(run, source.name)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
