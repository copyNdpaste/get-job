from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crawler.tracked import SUBMITTED_APPLICATION_STATUSES
from app.models import (
    Application,
    Company,
    DailyRecommendationBatch,
    DailyRecommendationItem,
    JobPosting,
    JobScore,
)


def local_today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.daily_digest_timezone)).date()


def generate_daily_recommendations(
    session: Session,
    settings: Settings,
    recommendation_date: date | None = None,
) -> DailyRecommendationBatch:
    target_date = recommendation_date or local_today(settings)
    batch = session.scalar(
        select(DailyRecommendationBatch).where(
            DailyRecommendationBatch.recommendation_date == target_date
        )
    )
    if batch is None:
        batch = DailyRecommendationBatch(
            recommendation_date=target_date,
            generated_at=datetime.now(UTC),
            slack_status="pending",
        )
        session.add(batch)
        session.flush()
    else:
        session.execute(
            delete(DailyRecommendationItem).where(DailyRecommendationItem.batch_id == batch.id)
        )
        batch.generated_at = datetime.now(UTC)
        batch.slack_status = "pending"
        batch.slack_error = None

    excluded_job_ids: set[int] = set()
    if settings.daily_recommendation_cooldown_days:
        cutoff = target_date - timedelta(days=settings.daily_recommendation_cooldown_days)
        excluded_job_ids.update(
            session.scalars(
                select(DailyRecommendationItem.job_posting_id)
                .join(
                    DailyRecommendationBatch,
                    DailyRecommendationBatch.id == DailyRecommendationItem.batch_id,
                )
                .where(
                    DailyRecommendationBatch.recommendation_date >= cutoff,
                    DailyRecommendationBatch.recommendation_date < target_date,
                )
            )
        )

    # Company evidence affects ordering only; unknown size is not a tiny company.
    organization_priority = (
        case(
            (
                and_(
                    Company.employee_count >= 30,
                    func.lower(Company.investment_stage).in_(
                        ["series a", "series b", "series c", "series d", "series e", "series f"]
                    ),
                ),
                0,
            ),
            (Company.employee_count >= 30, 1),
            (Company.employee_count.is_(None), 2),
            (Company.employee_count >= 20, 3),
            else_=4,
        )
        if settings.daily_recommendation_prefer_established and not settings.ai_preference_scoring
        else (JobScore.application_value_score.desc())
    )

    year_start = datetime(target_date.year, 1, 1, tzinfo=ZoneInfo(settings.daily_digest_timezone))
    rows = session.execute(
        select(
            JobPosting.id,
            JobScore.total_fit_score,
            JobScore.application_value_score,
            JobScore.application_probability_score,
            JobScore.evidence_json,
        )
        .join(JobScore, JobScore.job_posting_id == JobPosting.id)
        .join(Company, Company.id == JobPosting.company_id)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(
            JobPosting.is_primary_posting.is_(True),
            JobPosting.is_active.is_(True),
            or_(JobPosting.posted_at.is_(None), JobPosting.posted_at >= year_start),
            or_(JobPosting.deadline_at.is_(None), JobPosting.deadline_at >= datetime.now(UTC)),
            JobPosting.is_hidden.is_(False),
            or_(
                Application.status.is_(None),
                Application.status.notin_(SUBMITTED_APPLICATION_STATUSES),
            ),
            JobScore.grade != "Excluded",
            *(
                [JobScore.scoring_version == "ai_preference_v1"]
                if settings.ai_preference_scoring
                else []
            ),
            JobScore.total_fit_score >= settings.daily_recommendation_min_fit,
            JobScore.application_value_score >= settings.daily_recommendation_min_value,
        )
        .order_by(
            organization_priority,
            JobScore.application_value_score.desc(),
            JobScore.total_fit_score.desc(),
            JobScore.application_probability_score.desc(),
            JobPosting.posted_at.desc().nullslast(),
            JobPosting.first_seen_at.desc(),
            JobPosting.id.desc(),
        )
    ).all()

    seen_job_ids: set[int] = set()
    rank = 1
    for job_id, fit_score, value_score, _probability_score, evidence in rows:
        if job_id in excluded_job_ids or job_id in seen_job_ids:
            continue
        hard_gaps = (evidence or {}).get("hard_requirement_gaps", [])
        if any(gap.get("severity") == "high" for gap in hard_gaps):
            continue
        strict_tech_gaps = (evidence or {}).get("rank_factors", {}).get("strict_required_gaps", [])
        if strict_tech_gaps:
            continue
        if (evidence or {}).get("career_fit", {}).get("java_spring_required") is True:
            continue
        seen_job_ids.add(job_id)
        session.add(
            DailyRecommendationItem(
                batch_id=batch.id,
                job_posting_id=job_id,
                rank=rank,
                fit_score=float(fit_score),
                application_value_score=float(value_score),
            )
        )
        rank += 1
        if rank > settings.daily_recommendation_limit:
            break

    session.flush()
    session.expire(batch, ["items"])
    return batch
