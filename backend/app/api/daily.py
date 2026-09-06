from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.crawler.tracked import SUBMITTED_APPLICATION_STATUSES
from app.daily_recommendations import generate_daily_recommendations
from app.db.session import get_db
from app.models import (
    Application,
    Company,
    DailyRecommendationBatch,
    DailyRecommendationItem,
    JobPosting,
    JobSource,
)
from app.slack import SlackJob, send_daily_recommendations

router = APIRouter(prefix="/api/daily-recommendations", tags=["daily-recommendations"])


class DailyRecommendationDate(BaseModel):
    date: date
    generated_at: datetime
    item_count: int
    slack_status: str


class DailyRecommendationItemResponse(BaseModel):
    job_id: int
    rank: int
    company: str
    title: str
    source: str
    url: str
    tech_stack: list[str]
    experience_text: str | None
    location: str | None
    posted_at: datetime | None
    fit_score: float
    application_value_score: float


class DailyRecommendationResponse(BaseModel):
    date: date | None
    generated_at: datetime | None
    slack_status: str | None
    items: list[DailyRecommendationItemResponse]


class GenerateDailyRequest(BaseModel):
    notify_slack: bool = True


def _batch_items(
    session: Session, batch: DailyRecommendationBatch
) -> list[DailyRecommendationItemResponse]:
    rows = session.execute(
        select(DailyRecommendationItem, JobPosting, Company, JobSource)
        .join(JobPosting, JobPosting.id == DailyRecommendationItem.job_posting_id)
        .join(Company, Company.id == JobPosting.company_id)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(DailyRecommendationItem.batch_id == batch.id)
        .where(
            JobPosting.is_primary_posting.is_(True),
            or_(
                Application.status.is_(None),
                Application.status.notin_(SUBMITTED_APPLICATION_STATUSES),
            ),
        )
        .order_by(DailyRecommendationItem.rank)
    ).all()
    return [
        DailyRecommendationItemResponse(
            job_id=job.id,
            rank=item.rank,
            company=company.name,
            title=job.title,
            source=source.name,
            url=job.url,
            tech_stack=job.tech_stack or [],
            experience_text=job.experience_text,
            location=job.location,
            posted_at=job.posted_at,
            fit_score=item.fit_score,
            application_value_score=item.application_value_score,
        )
        for item, job, company, source in rows
    ]


def _response(
    session: Session, batch: DailyRecommendationBatch | None
) -> DailyRecommendationResponse:
    if batch is None:
        return DailyRecommendationResponse(
            date=None,
            generated_at=None,
            slack_status=None,
            items=[],
        )
    return DailyRecommendationResponse(
        date=batch.recommendation_date,
        generated_at=batch.generated_at,
        slack_status=batch.slack_status,
        items=_batch_items(session, batch),
    )


def _markdown_text(value: str | None) -> str:
    return (value or "미기재").replace("\r", " ").replace("\n", " ").replace("[", "\\[")


@router.get("/dates", response_model=list[DailyRecommendationDate])
def list_daily_recommendation_dates(
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[DailyRecommendationDate]:
    rows = session.execute(
        select(
            DailyRecommendationBatch,
            func.count(DailyRecommendationItem.id),
        )
        .outerjoin(
            DailyRecommendationItem,
            DailyRecommendationItem.batch_id == DailyRecommendationBatch.id,
        )
        .outerjoin(
            JobPosting,
            JobPosting.id == DailyRecommendationItem.job_posting_id,
        )
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(
            or_(JobPosting.id.is_(None), JobPosting.is_primary_posting.is_(True)),
            or_(
                Application.status.is_(None),
                Application.status.notin_(SUBMITTED_APPLICATION_STATUSES),
            ),
        )
        .group_by(DailyRecommendationBatch.id)
        .order_by(DailyRecommendationBatch.recommendation_date.desc())
        .limit(limit)
    ).all()
    return [
        DailyRecommendationDate(
            date=batch.recommendation_date,
            generated_at=batch.generated_at,
            item_count=item_count,
            slack_status=batch.slack_status,
        )
        for batch, item_count in rows
    ]


@router.get("/report")
def download_daily_recommendation_report(
    session: Annotated[Session, Depends(get_db)],
    recommendation_date: Annotated[date, Query(alias="date")],
) -> Response:
    batch = session.scalar(
        select(DailyRecommendationBatch).where(
            DailyRecommendationBatch.recommendation_date == recommendation_date
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="daily recommendation report not found")
    items = _batch_items(session, batch)
    lines = [
        f"# 오늘의 추천 공고 · {recommendation_date.isoformat()}",
        "",
        f"- 생성 시각: {batch.generated_at.isoformat()}",
        f"- 추천 공고: {len(items)}개",
        "- 적합도: 현재 이력서로 필수 업무를 수행할 수 있는 정도",
        "- 지원가치: 적합도와 커리어 방향·성장 기회를 반영한 지원 우선순위",
        "",
    ]
    for item in items:
        technologies = ", ".join(_markdown_text(tech) for tech in item.tech_stack[:8])
        lines.extend(
            [
                f"## {item.rank}. {_markdown_text(item.title)}",
                "",
                f"- 회사: {_markdown_text(item.company)}",
                f"- 사이트: {_markdown_text(item.source)}",
                f"- 경력: {_markdown_text(item.experience_text)}",
                f"- 근무지: {_markdown_text(item.location)}",
                f"- 기술: {technologies or '미기재'}",
                f"- 적합도: {item.fit_score:.1f}점",
                f"- 지원가치: {item.application_value_score:.1f}점",
                f"- 공고: {item.url}",
                "",
            ]
        )
    lines.extend(
        [
            "---",
            "이 리포트에는 공개 공고 정보와 집계 점수만 포함됩니다. ",
            "이력서 원문, 개인정보, 상세 매칭 근거는 포함되지 않습니다.",
        ]
    )
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="get-job-{recommendation_date.isoformat()}.md"'
            )
        },
    )


@router.get("", response_model=DailyRecommendationResponse)
def get_daily_recommendations(
    session: Annotated[Session, Depends(get_db)],
    recommendation_date: Annotated[date | None, Query(alias="date")] = None,
) -> DailyRecommendationResponse:
    query = select(DailyRecommendationBatch)
    if recommendation_date is None:
        query = query.order_by(DailyRecommendationBatch.recommendation_date.desc())
    else:
        query = query.where(DailyRecommendationBatch.recommendation_date == recommendation_date)
    return _response(session, session.scalar(query.limit(1)))


@router.post("/generate", response_model=DailyRecommendationResponse)
async def generate_daily_recommendation_batch(
    payload: GenerateDailyRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DailyRecommendationResponse:
    batch = generate_daily_recommendations(session, settings)
    items = _batch_items(session, batch)
    if not payload.notify_slack:
        batch.slack_status = "not_requested"
    session.commit()

    if payload.notify_slack:
        try:
            slack_status = await send_daily_recommendations(
                settings,
                batch.recommendation_date,
                [
                    SlackJob(
                        rank=item.rank,
                        company=item.company,
                        title=item.title,
                        source=item.source,
                        url=item.url,
                        tech_stack=item.tech_stack,
                        fit_score=item.fit_score,
                        application_value_score=item.application_value_score,
                    )
                    for item in items
                ],
            )
            batch.slack_status = slack_status
            batch.slack_error = None
        except Exception as exc:
            batch.slack_status = "failed"
            batch.slack_error = f"Slack delivery failed ({type(exc).__name__})"
        session.commit()

    session.refresh(batch)
    return _response(session, batch)
