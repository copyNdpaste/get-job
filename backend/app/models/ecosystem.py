from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class EcosystemOrganization(TimestampMixin, Base):
    __tablename__ = "ecosystem_organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    program_url: Mapped[str | None] = mapped_column(String(2048))
    fit_score: Mapped[int] = mapped_column(
        Integer, default=50, server_default="50", nullable=False
    )
    fit_reason: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    focus_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    operating_scale: Mapped[str | None] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    programs: Mapped[list["EcosystemProgram"]] = relationship(back_populates="organization")
    crawl_runs: Mapped[list["EcosystemCrawlRun"]] = relationship(back_populates="organization")


class EcosystemProgram(Base):
    __tablename__ = "ecosystem_programs"
    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_title", name="uq_ecosystem_program_title"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("ecosystem_organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    program_type: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    deadline_text: Mapped[str | None] = mapped_column(String(200))
    is_open: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization: Mapped["EcosystemOrganization"] = relationship(back_populates="programs")


class EcosystemCrawlRun(Base):
    __tablename__ = "ecosystem_crawl_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("ecosystem_organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_visited: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    programs_found: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    programs_created: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    programs_updated: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    error_log: Mapped[str | None] = mapped_column(Text)

    organization: Mapped["EcosystemOrganization"] = relationship(back_populates="crawl_runs")
