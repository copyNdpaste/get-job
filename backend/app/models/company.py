from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(255))
    company_size: Mapped[str | None] = mapped_column(String(100))
    investment_stage: Mapped[str | None] = mapped_column(String(100))
    total_investment: Mapped[str | None] = mapped_column(String(100))
    annual_revenue: Mapped[str | None] = mapped_column(String(100))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    developer_count: Mapped[int | None] = mapped_column(Integer)
    employee_count_source: Mapped[str | None] = mapped_column(String(100))
    employee_count_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profitability_status: Mapped[str] = mapped_column(
        String(30), default="undisclosed", server_default="undisclosed", nullable=False
    )
    financial_history: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    funding_history: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_TYPE, default=list, nullable=False
    )
    facts_source_urls: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    facts_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    groupby_profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_registration_number: Mapped[str | None] = mapped_column(String(20))
    dart_corp_code: Mapped[str | None] = mapped_column(String(8), index=True)
    location: Mapped[str | None] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(2048))
    source_urls: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)

    job_postings: Mapped[list["JobPosting"]] = relationship(back_populates="company")


from app.models.job import JobPosting  # noqa: E402
