from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class JobPosting(TimestampMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_job_id", name="uq_job_source_external_id"),
        Index("ix_job_company_title", "company_id", "normalized_title"),
        Index("ix_job_active_last_seen", "is_active", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("job_sources.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    external_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), index=True, nullable=False)
    job_category: Mapped[str | None] = mapped_column(String(100), index=True)
    employment_type: Mapped[str | None] = mapped_column(String(100))
    description_raw: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    main_tasks: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    requirements: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    preferred_requirements: Mapped[list[str]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    benefits: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    tech_stack: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    hiring_process: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    has_coding_test: Mapped[bool | None] = mapped_column(Boolean, index=True)
    interview_count: Mapped[int | None] = mapped_column(Integer, index=True)
    experience_text: Mapped[str | None] = mapped_column(String(500))
    min_experience: Mapped[int | None] = mapped_column(Integer)
    max_experience: Mapped[int | None] = mapped_column(Integer)
    experience_type: Mapped[str | None] = mapped_column(String(30))
    is_experience_eligible: Mapped[bool | None] = mapped_column(Boolean)
    experience_reason: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_text: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500), index=True)
    remote_type: Mapped[str | None] = mapped_column(String(100), index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True, nullable=False
    )
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    crawl_status: Mapped[str] = mapped_column(String(30), default="success", nullable=False)
    crawl_error: Mapped[str | None] = mapped_column(Text)
    duplicate_group_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    is_primary_posting: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    duplicate_reason: Mapped[str | None] = mapped_column(String(255))

    source: Mapped["JobSource"] = relationship(back_populates="job_postings")
    company: Mapped["Company"] = relationship(back_populates="job_postings")
    snapshots: Mapped[list["JobPostingSnapshot"]] = relationship(
        back_populates="job_posting", cascade="all, delete-orphan"
    )
    scores: Mapped[list["JobScore"]] = relationship(
        back_populates="job_posting", cascade="all, delete-orphan"
    )
    application: Mapped["Application | None"] = relationship(
        back_populates="job_posting", cascade="all, delete-orphan", uselist=False
    )


_VISIBLE_ACTIVE = (
    JobPosting.is_primary_posting.is_(True)
    & JobPosting.is_active.is_(True)
    & JobPosting.is_hidden.is_(False)
)
for _name, _columns in (
    (
        "ix_job_visible_latest",
        (
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
            JobPosting.id.desc(),
        ),
    ),
    (
        "ix_job_visible_source_latest",
        (
            JobPosting.source_id,
            func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at).desc(),
            JobPosting.id.desc(),
        ),
    ),
    ("ix_job_visible_collected", (JobPosting.first_seen_at.desc(), JobPosting.id.desc())),
):
    Index(_name, *_columns, postgresql_where=_VISIBLE_ACTIVE, sqlite_where=_VISIBLE_ACTIVE)


class JobPostingSnapshot(Base):
    __tablename__ = "job_posting_snapshots"
    __table_args__ = (
        UniqueConstraint("job_posting_id", "content_hash", name="uq_snapshot_job_content_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_content: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    job_posting: Mapped[JobPosting] = relationship(back_populates="snapshots")


from app.models.application import Application  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.crawl import JobSource  # noqa: E402
from app.models.score import JobScore  # noqa: E402
