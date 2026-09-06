from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class JobSource(TimestampMixin, Base):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    crawler_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job_postings: Mapped[list["JobPosting"]] = relationship(back_populates="source")
    crawl_runs: Mapped[list["CrawlRun"]] = relationship(back_populates="source")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="crawl_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("job_sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    pages_visited: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    jobs_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    jobs_created: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    jobs_updated: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error_log: Mapped[str | None] = mapped_column(Text)

    source: Mapped[JobSource] = relationship(back_populates="crawl_runs")


from app.models.job import JobPosting  # noqa: E402
