from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class JobScore(Base):
    __tablename__ = "job_scores"
    __table_args__ = (
        UniqueConstraint("job_posting_id", "candidate_profile_id", name="uq_score_job_candidate"),
        CheckConstraint("grade IN ('S', 'A', 'B', 'C', 'Excluded')", name="job_grade"),
        CheckConstraint("total_fit_score BETWEEN 0 AND 100", name="total_fit_score_range"),
        CheckConstraint(
            "application_value_score BETWEEN 0 AND 100",
            name="application_value_score_range",
        ),
        CheckConstraint(
            "application_probability_score BETWEEN 0 AND 100",
            name="application_probability_score_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    eligibility_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    backend_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    database_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    system_design_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    infra_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    messaging_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    ai_product_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    product_ownership_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    collaboration_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    domain_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    salary_career_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    skill_gap_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total_fit_score: Mapped[float] = mapped_column(Float, default=0, index=True, nullable=False)
    application_value_score: Mapped[float] = mapped_column(
        Float, default=0, index=True, nullable=False
    )
    application_probability_score: Mapped[float] = mapped_column(
        Float, default=0, index=True, nullable=False
    )
    grade: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True, nullable=False)
    matching_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    missing_skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    risk_notes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    labels: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    recommended_resume_version: Mapped[str | None] = mapped_column(String(50))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(50), nullable=False)

    job_posting: Mapped["JobPosting"] = relationship(back_populates="scores")
    candidate_profile: Mapped["CandidateProfile"] = relationship(back_populates="scores")


from app.models.candidate import CandidateProfile  # noqa: E402
from app.models.job import JobPosting  # noqa: E402
