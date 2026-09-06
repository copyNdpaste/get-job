from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class DailyRecommendationBatch(TimestampMixin, Base):
    __tablename__ = "daily_recommendation_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recommendation_date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slack_status: Mapped[str] = mapped_column(
        String(30), default="pending", server_default="pending", nullable=False
    )
    slack_error: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["DailyRecommendationItem"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="DailyRecommendationItem.rank",
    )


class DailyRecommendationItem(Base):
    __tablename__ = "daily_recommendation_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "job_posting_id", name="uq_daily_batch_job"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("daily_recommendation_batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    application_value_score: Mapped[float] = mapped_column(Float, nullable=False)

    batch: Mapped[DailyRecommendationBatch] = relationship(back_populates="items")
    job_posting: Mapped["JobPosting"] = relationship()


from app.models.job import JobPosting  # noqa: E402
