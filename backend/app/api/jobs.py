import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, load_only

from app.config import Settings, get_settings
from app.crawler.tracked import SUBMITTED_APPLICATION_STATUSES
from app.db.session import get_db
from app.deduplication import refresh_duplicate_groups
from app.experience import parse_experience as _parse_experience
from app.models import Application, CandidateProfile, Company, JobPosting, JobScore, JobSource
from app.resume_recommendation import enrich_resume_recommendation

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

EXPERIENCE_FILTERS = {"intern", "entry", "career", "no_experience"}
CODING_TEST_FILTERS = {"yes", "no", "unknown"}
INTERVIEW_COUNT_FILTERS = {"one", "two_plus", "none", "unknown"}
EXCLUDED_APPLICATION_STATUSES = frozenset({"rejected", "withdrawn"})


def _tech_matches(label: str, selected: str) -> bool:
    """Match a technology name on label boundaries, never Java inside JavaScript."""
    label_normalized = label.strip().casefold()
    selected_normalized = selected.strip().casefold()
    if not label_normalized or not selected_normalized:
        return False
    if label_normalized == selected_normalized:
        return True
    return bool(
        re.search(
            rf"(?<![\w+#.]){re.escape(selected_normalized)}(?![\w+#.])",
            label_normalized,
        )
    )


def _matches_post_filters(
    row: Any,
    technologies: list[str],
    excluded_technologies: list[str],
    experience_filters: set[str],
    min_years: int | None,
    max_years: int | None,
) -> bool:
    job = row[0]
    stack = [str(item) for item in (job.tech_stack or [])]
    if technologies and not any(
        _tech_matches(item, selected) for item in stack for selected in technologies
    ):
        return False
    if excluded_technologies and any(
        _tech_matches(item, excluded) for item in stack for excluded in excluded_technologies
    ):
        return False

    has_experience_filter = (
        bool(experience_filters) or min_years is not None or max_years is not None
    )
    if not has_experience_filter:
        return True

    experience_signals = " ".join(
        str(value) for value in (job.title, job.experience_text, job.employment_type) if value
    )
    info = _parse_experience(experience_signals)
    if experience_filters and not experience_filters.intersection(info.categories):
        return False
    if min_years is None and max_years is None:
        return True
    if "no_experience" in info.categories:
        return True
    if not info.has_year_range or info.minimum_years is None:
        return False

    requested_minimum = min_years if min_years is not None else 0
    requested_maximum = max_years if max_years is not None else float("inf")
    posting_maximum = info.maximum_years if info.maximum_years is not None else float("inf")
    return info.minimum_years <= requested_maximum and posting_maximum >= requested_minimum


class CompanySummary(BaseModel):
    employee_count: int | None
    developer_count: int | None
    employee_count_source: str | None
    employee_count_as_of: datetime | None
    latest_revenue: int | None
    latest_revenue_year: int | None
    profitability_status: str
    investment_stage: str | None
    recent_investment_amount: int | None
    recent_investment_count: int
    disclosed_investment_count: int
    facts_updated_at: datetime | None


class CompanyProfile(CompanySummary):
    financial_history: list[dict[str, Any]]
    funding_history: list[dict[str, Any]]
    source_urls: list[str]


class DuplicatePostingLink(BaseModel):
    id: int
    source: str
    url: str
    is_active: bool


class JobListItem(BaseModel):
    id: int
    source: str
    company: str
    company_summary: CompanySummary
    title: str
    url: str
    tech_stack: list[str]
    hiring_process: list[str]
    has_coding_test: bool | None
    interview_count: int | None
    experience_text: str | None
    location: str | None
    posted_at: datetime | None
    deadline_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
    is_hidden: bool
    is_favorite: bool
    total_fit_score: float | None
    application_value_score: float | None
    application_probability_score: float | None
    grade: str | None
    recommendation_grade: str | None
    node_typescript_transition: str | None
    go_transition: str | None
    backend_work_share: int | None
    java_spring_required: bool | None
    java_spring_status: str | None
    recommended_resume_type: str | None
    recommended_resume_id: str | None
    recommended_resume_label: str | None
    recommended_resume_score: float | None
    application_status: str
    duplicate_count: int = 1
    duplicate_postings: list[DuplicatePostingLink] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobListItem]
    total: int
    limit: int
    offset: int


class JobDetail(JobListItem):
    company_profile: CompanyProfile
    description_text: str | None
    main_tasks: list[str]
    requirements: list[str]
    preferred_requirements: list[str]
    benefits: list[str]
    employment_type: str | None
    matching_reasons: list[dict[str, Any]]
    missing_skills: list[dict[str, Any]]
    risk_notes: list[str]
    score_breakdown: list[dict[str, Any]]
    score_formula: str | None
    scoring_version: str | None
    recommended_resume_version: str | None
    resume_recommendation: dict[str, Any] | None
    candidate_summary: str | None
    candidate_years_experience: int | None
    score_summary: str | None
    score_confidence: str | None
    score_caps: list[str]
    score_definitions: dict[str, str]
    recommendation_reasons: list[str]


class JobStats(BaseModel):
    total: int
    active: int
    new_last_7_days: int
    favorite: int
    applied: int
    hidden: int
    source_counts: dict[str, int]
    tech_counts: dict[str, int]


def _recent_funding(company: Company) -> list[dict[str, Any]]:
    today = datetime.now(UTC).date()
    try:
        cutoff = today.replace(year=today.year - 3)
    except ValueError:
        cutoff = date(today.year - 3, 2, 28)
    return [
        item
        for item in (company.funding_history or [])
        if item.get("date") and str(item.get("date"))[:10] >= cutoff.isoformat()
    ]


def _company_summary(company: Company) -> CompanySummary:
    financials = sorted(
        company.financial_history or [],
        key=lambda item: int(item.get("year") or 0),
        reverse=True,
    )
    latest = financials[0] if financials else {}
    recent_funding = _recent_funding(company)
    known_amounts = [
        int(item["amount"]) for item in recent_funding if isinstance(item.get("amount"), int)
    ]
    return CompanySummary(
        employee_count=company.employee_count,
        developer_count=company.developer_count,
        employee_count_source=company.employee_count_source,
        employee_count_as_of=company.employee_count_as_of,
        latest_revenue=(int(latest["revenue"]) if isinstance(latest.get("revenue"), int) else None),
        latest_revenue_year=(int(latest["year"]) if isinstance(latest.get("year"), int) else None),
        profitability_status=company.profitability_status or "undisclosed",
        investment_stage=company.investment_stage,
        recent_investment_amount=sum(known_amounts) if known_amounts else None,
        recent_investment_count=len(recent_funding),
        disclosed_investment_count=len(known_amounts),
        facts_updated_at=company.facts_updated_at,
    )


def _company_profile(company: Company) -> CompanyProfile:
    summary = _company_summary(company)
    financials = sorted(
        company.financial_history or [],
        key=lambda item: int(item.get("year") or 0),
        reverse=True,
    )[:3]
    return CompanyProfile(
        **summary.model_dump(),
        financial_history=financials,
        funding_history=_recent_funding(company),
        source_urls=company.facts_source_urls or [],
    )


def _list_item(
    row: Any, duplicate_postings: list[DuplicatePostingLink] | None = None
) -> JobListItem:
    job, company, source, score, application = row
    resume_recommendation = (
        (score.evidence_json or {}).get("resume_recommendation") if score else None
    )
    career_fit = (score.evidence_json or {}).get("career_fit", {}) if score else {}
    return JobListItem(
        id=job.id,
        source=source.name,
        company=company.name,
        company_summary=_company_summary(company),
        title=job.title,
        url=job.url,
        tech_stack=job.tech_stack or [],
        hiring_process=job.hiring_process or [],
        has_coding_test=job.has_coding_test,
        interview_count=job.interview_count,
        experience_text=job.experience_text,
        location=job.location,
        posted_at=job.posted_at,
        deadline_at=job.deadline_at,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        is_active=job.is_active,
        is_hidden=job.is_hidden,
        is_favorite=job.is_favorite,
        total_fit_score=score.total_fit_score if score else None,
        application_value_score=score.application_value_score if score else None,
        application_probability_score=score.application_probability_score if score else None,
        grade=score.grade if score else None,
        recommendation_grade=career_fit.get("recommendation_grade"),
        node_typescript_transition=career_fit.get("node_typescript_transition"),
        go_transition=career_fit.get("go_transition"),
        backend_work_share=career_fit.get("backend_work_share"),
        java_spring_required=career_fit.get("java_spring_required"),
        java_spring_status=career_fit.get("java_spring_status"),
        recommended_resume_type=career_fit.get("resume_type"),
        recommended_resume_id=(
            resume_recommendation.get("recommended_id") if resume_recommendation else None
        ),
        recommended_resume_label=(
            resume_recommendation.get("recommended_label") if resume_recommendation else None
        ),
        recommended_resume_score=(
            resume_recommendation.get("recommended_score") if resume_recommendation else None
        ),
        application_status=application.status if application else "not_reviewed",
        duplicate_count=max(1, len(duplicate_postings or [])),
        duplicate_postings=duplicate_postings or [],
    )


def _duplicate_links(session: Session, rows: list[Any]) -> dict[object, list[DuplicatePostingLink]]:
    group_ids = {row[0].duplicate_group_id for row in rows if row[0].duplicate_group_id}
    if not group_ids:
        return {}
    links: dict[object, list[DuplicatePostingLink]] = {}
    postings = session.execute(
        select(
            JobPosting.id,
            JobPosting.url,
            JobPosting.is_active,
            JobPosting.duplicate_group_id,
            JobSource.name.label("source_name"),
        )
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .where(JobPosting.duplicate_group_id.in_(group_ids))
        .order_by(JobPosting.is_primary_posting.desc(), JobSource.name.asc())
    ).all()
    for posting in postings:
        links.setdefault(posting.duplicate_group_id, []).append(
            DuplicatePostingLink(
                id=posting.id,
                source=posting.source_name,
                url=posting.url,
                is_active=posting.is_active,
            )
        )
    return links


def _base_query():
    return (
        select(JobPosting, Company, JobSource, JobScore, Application)
        .join(Company, Company.id == JobPosting.company_id)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .outerjoin(JobScore, JobScore.job_posting_id == JobPosting.id)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    session: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    source: str | None = None,
    exclude_source: Annotated[list[str] | None, Query()] = None,
    tech: Annotated[list[str] | None, Query()] = None,
    exclude_tech: Annotated[list[str] | None, Query()] = None,
    experience: Annotated[list[str] | None, Query()] = None,
    min_years: Annotated[int | None, Query(ge=0, le=50)] = None,
    max_years: Annotated[int | None, Query(ge=0, le=50)] = None,
    coding_test: Annotated[list[str] | None, Query()] = None,
    interview_count: Annotated[list[str] | None, Query()] = None,
    min_fit_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_value_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    active_only: bool = True,
    include_hidden: bool = False,
    favorite_only: bool = False,
    applied_only: bool = False,
    hidden_only: bool = False,
    collected_within_days: Annotated[int | None, Query(ge=1, le=90)] = None,
    posted_within_days: Annotated[int | None, Query(ge=1, le=365)] = None,
    include_unknown_posted: bool = False,
    sort: Literal["latest", "collected", "fit", "value", "company"] = "latest",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    excluded_sources = list(
        dict.fromkeys(item.strip() for item in (exclude_source or []) if item.strip())
    )
    if len(excluded_sources) > 20 or any(len(item) > 50 for item in excluded_sources):
        raise HTTPException(status_code=400, detail="제외 출처는 20개, 항목당 50자까지 가능합니다.")
    technologies = [item.strip() for item in (tech or []) if item.strip()]
    if len(technologies) > 20 or any(len(item) > 50 for item in technologies):
        raise HTTPException(
            status_code=400, detail="포함 기술은 20개, 항목당 50자까지 선택할 수 있습니다."
        )
    excluded_technologies = [item.strip() for item in (exclude_tech or []) if item.strip()]
    if len(excluded_technologies) > 20 or any(len(item) > 50 for item in excluded_technologies):
        raise HTTPException(
            status_code=400, detail="제외 기술은 20개, 항목당 50자까지 선택할 수 있습니다."
        )
    experience_filters = {item.strip() for item in (experience or []) if item.strip()}
    invalid_experience = experience_filters - EXPERIENCE_FILTERS
    if invalid_experience:
        raise HTTPException(status_code=400, detail="지원하지 않는 경력 유형입니다.")
    coding_test_filters = {item.strip() for item in (coding_test or []) if item.strip()}
    if coding_test_filters - CODING_TEST_FILTERS:
        raise HTTPException(status_code=400, detail="지원하지 않는 코딩테스트 조건입니다.")
    interview_count_filters = {item.strip() for item in (interview_count or []) if item.strip()}
    if interview_count_filters - INTERVIEW_COUNT_FILTERS:
        raise HTTPException(status_code=400, detail="지원하지 않는 면접 횟수 조건입니다.")
    if min_years is not None and max_years is not None and min_years > max_years:
        raise HTTPException(status_code=400, detail="최소 연차는 최대 연차보다 클 수 없습니다.")

    # List views never need full descriptions, requirements, or scoring rationale.
    query = _base_query().options(
        load_only(
            JobPosting.id,
            JobPosting.title,
            JobPosting.url,
            JobPosting.tech_stack,
            JobPosting.hiring_process,
            JobPosting.has_coding_test,
            JobPosting.interview_count,
            JobPosting.experience_text,
            JobPosting.location,
            JobPosting.posted_at,
            JobPosting.deadline_at,
            JobPosting.first_seen_at,
            JobPosting.last_seen_at,
            JobPosting.is_active,
            JobPosting.is_hidden,
            JobPosting.is_favorite,
            JobPosting.duplicate_group_id,
        ),
        load_only(
            JobScore.total_fit_score,
            JobScore.application_value_score,
            JobScore.application_probability_score,
            JobScore.grade,
            JobScore.evidence_json,
        ),
    )
    count_query = (
        select(func.count(func.distinct(JobPosting.id)))
        .join(Company, Company.id == JobPosting.company_id)
        .join(JobSource, JobSource.id == JobPosting.source_id)
        .outerjoin(JobScore, JobScore.job_posting_id == JobPosting.id)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
    )
    conditions = []
    conditions.append(JobPosting.is_primary_posting.is_(True))
    if active_only:
        conditions.extend(
            [
                JobPosting.is_active.is_(True),
                or_(
                    JobPosting.deadline_at.is_(None),
                    JobPosting.deadline_at >= datetime.now(UTC),
                ),
            ]
        )
    if hidden_only:
        conditions.append(JobPosting.is_hidden.is_(True))
    elif not include_hidden:
        conditions.append(JobPosting.is_hidden.is_(False))
    if favorite_only:
        conditions.append(JobPosting.is_favorite.is_(True))
    if applied_only:
        conditions.append(Application.status.in_(SUBMITTED_APPLICATION_STATUSES))
    elif not hidden_only:
        conditions.append(
            or_(
                Application.status.is_(None),
                Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
            )
        )
    if collected_within_days is not None:
        conditions.append(
            JobPosting.first_seen_at >= datetime.now(UTC) - timedelta(days=collected_within_days)
        )
    if posted_within_days is not None:
        posted_condition = (
            JobPosting.posted_at >= datetime.now(UTC) - timedelta(days=posted_within_days)
        )
        if include_unknown_posted:
            posted_condition = or_(posted_condition, JobPosting.posted_at.is_(None))
        conditions.append(posted_condition)
    if source:
        conditions.append(JobSource.name == source)
    if excluded_sources:
        conditions.append(JobSource.name.notin_(excluded_sources))
    if q:
        token = f"%{q.strip()}%"
        conditions.append(or_(JobPosting.title.ilike(token), Company.name.ilike(token)))
    coding_test_conditions = []
    if "yes" in coding_test_filters:
        coding_test_conditions.append(JobPosting.has_coding_test.is_(True))
    if "no" in coding_test_filters:
        coding_test_conditions.append(JobPosting.has_coding_test.is_(False))
    if "unknown" in coding_test_filters:
        coding_test_conditions.append(JobPosting.has_coding_test.is_(None))
    if coding_test_conditions:
        conditions.append(or_(*coding_test_conditions))
    interview_count_conditions = []
    if "one" in interview_count_filters:
        interview_count_conditions.append(JobPosting.interview_count == 1)
    if "two_plus" in interview_count_filters:
        interview_count_conditions.append(JobPosting.interview_count >= 2)
    if "none" in interview_count_filters:
        interview_count_conditions.append(JobPosting.interview_count == 0)
    if "unknown" in interview_count_filters:
        interview_count_conditions.append(JobPosting.interview_count.is_(None))
    if interview_count_conditions:
        conditions.append(or_(*interview_count_conditions))
    if min_fit_score is not None:
        conditions.append(JobScore.total_fit_score >= min_fit_score)
    if min_value_score is not None:
        conditions.append(JobScore.application_value_score >= min_value_score)
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)

    orders = {
        "latest": (
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
            JobScore.total_fit_score.desc().nullslast(),
            JobScore.application_value_score.desc().nullslast(),
        ),
        "collected": (
            JobPosting.first_seen_at.desc(),
            JobScore.total_fit_score.desc().nullslast(),
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
        ),
        "fit": (
            JobScore.total_fit_score.desc().nullslast(),
            JobScore.application_probability_score.desc().nullslast(),
            JobScore.application_value_score.desc().nullslast(),
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
        ),
        "value": (
            JobScore.application_value_score.desc().nullslast(),
            JobScore.total_fit_score.desc().nullslast(),
            JobScore.application_probability_score.desc().nullslast(),
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
        ),
        "company": (
            Company.normalized_name.asc(),
            JobScore.total_fit_score.desc().nullslast(),
        ),
    }[sort]
    ordered_query = query.order_by(*orders, JobPosting.id.desc())
    needs_post_filter = bool(
        technologies
        or excluded_technologies
        or experience_filters
        or min_years is not None
        or max_years is not None
    )
    if needs_post_filter:
        # Preserve boundary-aware technology and experience parsing semantics while
        # scanning only small filter columns, not every score JSON and job body.
        candidates = ordered_query.with_only_columns(
            JobPosting.id,
            JobPosting.title,
            JobPosting.tech_stack,
            JobPosting.experience_text,
            JobPosting.employment_type,
        )
        matching_ids = [
            candidate.id
            for candidate in session.execute(candidates)
            if _matches_post_filters(
                (candidate,),
                technologies,
                excluded_technologies,
                experience_filters,
                min_years,
                max_years,
            )
        ]
        total = len(matching_ids)
        page_ids = matching_ids[offset : offset + limit]
        rows = (
            session.execute(ordered_query.where(JobPosting.id.in_(page_ids)).limit(limit)).all()
            if page_ids
            else []
        )
    else:
        rows = session.execute(ordered_query.limit(limit).offset(offset)).all()
        total = session.scalar(count_query) or 0
    duplicate_links = _duplicate_links(session, list(rows))
    return JobListResponse(
        items=[_list_item(row, duplicate_links.get(row[0].duplicate_group_id)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=JobStats)
def job_stats(session: Annotated[Session, Depends(get_db)]) -> JobStats:
    total = (
        session.scalar(
            select(func.count(JobPosting.id))
            .outerjoin(Application, Application.job_posting_id == JobPosting.id)
            .where(
                JobPosting.is_primary_posting.is_(True),
                JobPosting.is_hidden.is_(False),
                or_(
                    Application.status.is_(None),
                    Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
                ),
            )
        )
        or 0
    )
    active = (
        session.scalar(
            select(func.count(JobPosting.id))
            .outerjoin(Application, Application.job_posting_id == JobPosting.id)
            .where(
                JobPosting.is_primary_posting.is_(True),
                JobPosting.is_active.is_(True),
                or_(
                    JobPosting.deadline_at.is_(None),
                    JobPosting.deadline_at >= datetime.now(UTC),
                ),
                JobPosting.is_hidden.is_(False),
                or_(
                    Application.status.is_(None),
                    Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
                ),
            )
        )
        or 0
    )
    hidden = (
        session.scalar(
            select(func.count(JobPosting.id)).where(
                JobPosting.is_primary_posting.is_(True), JobPosting.is_hidden.is_(True)
            )
        )
        or 0
    )
    favorite = (
        session.scalar(
            select(func.count(JobPosting.id))
            .outerjoin(Application, Application.job_posting_id == JobPosting.id)
            .where(
                JobPosting.is_primary_posting.is_(True),
                JobPosting.is_active.is_(True),
                JobPosting.is_hidden.is_(False),
                JobPosting.is_favorite.is_(True),
                or_(
                    Application.status.is_(None),
                    Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
                ),
            )
        )
        or 0
    )
    applied = (
        session.scalar(
            select(func.count(Application.id)).where(
                Application.status.in_(SUBMITTED_APPLICATION_STATUSES),
                Application.job_posting_id.in_(
                    select(JobPosting.id).where(JobPosting.is_primary_posting.is_(True))
                ),
            )
        )
        or 0
    )
    since = datetime.now(UTC) - timedelta(days=7)
    new_count = (
        session.scalar(
            select(func.count(JobPosting.id))
            .outerjoin(Application, Application.job_posting_id == JobPosting.id)
            .where(
                JobPosting.is_primary_posting.is_(True),
                JobPosting.first_seen_at >= since,
                JobPosting.is_active.is_(True),
                or_(
                    JobPosting.deadline_at.is_(None),
                    JobPosting.deadline_at >= datetime.now(UTC),
                ),
                JobPosting.is_hidden.is_(False),
                or_(
                    Application.status.is_(None),
                    Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
                ),
            )
        )
        or 0
    )
    source_rows = session.execute(
        select(JobSource.name, func.count(JobPosting.id))
        .outerjoin(
            JobPosting,
            and_(
                JobPosting.source_id == JobSource.id,
                JobPosting.is_primary_posting.is_(True),
                JobPosting.is_hidden.is_(False),
            ),
        )
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(
            or_(
                Application.status.is_(None),
                Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
            )
        )
        .group_by(JobSource.name)
    ).all()
    tech_counts: dict[str, int] = {}
    for stack in session.scalars(
        select(JobPosting.tech_stack)
        .outerjoin(Application, Application.job_posting_id == JobPosting.id)
        .where(
            JobPosting.is_primary_posting.is_(True),
            JobPosting.is_hidden.is_(False),
            or_(
                Application.status.is_(None),
                Application.status.notin_(EXCLUDED_APPLICATION_STATUSES),
            ),
        )
    ):
        for item in stack or []:
            tech_counts[item] = tech_counts.get(item, 0) + 1
    top_tech = dict(sorted(tech_counts.items(), key=lambda pair: pair[1], reverse=True)[:100])
    return JobStats(
        total=total,
        active=active,
        new_last_7_days=new_count,
        favorite=favorite,
        applied=applied,
        hidden=hidden,
        source_counts={name: count for name, count in source_rows},
        tech_counts=top_tech,
    )


@router.post("/deduplicate")
def deduplicate_jobs(session: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    summary = refresh_duplicate_groups(session)
    session.commit()
    return {"groups": summary.groups, "grouped_postings": summary.grouped_postings}


class JobVisibilityRequest(BaseModel):
    job_ids: list[int]
    hidden: bool


@router.patch("/visibility")
def set_job_visibility(
    payload: JobVisibilityRequest, session: Annotated[Session, Depends(get_db)]
) -> dict[str, int | bool]:
    job_ids = list(dict.fromkeys(payload.job_ids))
    if not job_ids:
        raise HTTPException(status_code=400, detail="at least one job id is required")
    result = session.execute(
        update(JobPosting).where(JobPosting.id.in_(job_ids)).values(is_hidden=payload.hidden)
    )
    session.commit()
    return {"updated": result.rowcount or 0, "hidden": payload.hidden}


class JobFavoriteRequest(BaseModel):
    is_favorite: bool


@router.patch("/{job_id}/favorite")
def set_job_favorite(
    job_id: int,
    payload: JobFavoriteRequest,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, int | bool]:
    job = session.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    job.is_favorite = payload.is_favorite
    session.commit()
    return {"job_id": job_id, "is_favorite": job.is_favorite}


class JobApplicationRequest(BaseModel):
    status: Literal[
        "not_reviewed",
        "interested",
        "resume_preparing",
        "applied",
        "document_passed",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    ]


@router.patch("/{job_id}/application")
def set_job_application_status(
    job_id: int,
    payload: JobApplicationRequest,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, int | str | None]:
    job = session.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    application = session.scalar(select(Application).where(Application.job_posting_id == job_id))
    if application is None:
        application = Application(job_posting_id=job_id, status=payload.status)
        session.add(application)
    else:
        application.status = payload.status
    if payload.status in SUBMITTED_APPLICATION_STATUSES and application.applied_at is None:
        application.applied_at = datetime.now(UTC)
    session.commit()
    return {
        "job_id": job_id,
        "status": application.status,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
    }


@router.get("/{job_id}", response_model=JobDetail)
def job_detail(
    job_id: int,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobDetail:
    row = session.execute(_base_query().where(JobPosting.id == job_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    links = _duplicate_links(session, [row])
    item = _list_item(row, links.get(row[0].duplicate_group_id))
    job, company, _source, score, _application = row
    profile = session.get(CandidateProfile, score.candidate_profile_id) if score else None
    profile_data = profile.profile_json if profile else {}
    evidence = score.evidence_json if score else {}
    resume_recommendation = enrich_resume_recommendation(
        evidence.get("resume_recommendation"), settings
    )
    return JobDetail(
        **item.model_dump(),
        company_profile=_company_profile(company),
        description_text=job.description_text,
        main_tasks=job.main_tasks or [],
        requirements=job.requirements or [],
        preferred_requirements=job.preferred_requirements or [],
        benefits=job.benefits or [],
        employment_type=job.employment_type,
        matching_reasons=score.matching_reasons if score else [],
        missing_skills=score.missing_skills if score else [],
        risk_notes=score.risk_notes if score else [],
        score_breakdown=evidence.get("score_breakdown", []),
        score_formula=evidence.get("formula"),
        scoring_version=score.scoring_version if score else None,
        recommended_resume_version=score.recommended_resume_version if score else None,
        resume_recommendation=resume_recommendation,
        candidate_summary=profile_data.get("summary"),
        candidate_years_experience=profile_data.get("years_experience"),
        score_summary=evidence.get("score_summary"),
        score_confidence=evidence.get("confidence"),
        score_caps=evidence.get("caps_applied", []),
        score_definitions=evidence.get("definitions", {}),
        recommendation_reasons=evidence.get("career_fit", {}).get("recommendation_reasons", []),
    )
