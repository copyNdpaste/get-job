from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('not_reviewed', 'interested', 'resume_preparing', 'applied', "
            "'document_passed', 'interview', 'offer', 'rejected', 'withdrawn')",
            name="application_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="not_reviewed",
        server_default="not_reviewed",
        index=True,
        nullable=False,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_version: Mapped[str | None] = mapped_column(String(100))
    contact_channel: Mapped[str | None] = mapped_column(String(100))
    interview_date: Mapped[date | None] = mapped_column(Date)
    expected_salary: Mapped[float | None] = mapped_column(Numeric(14, 2))
    memo: Mapped[str | None] = mapped_column(Text)

    job_posting: Mapped["JobPosting"] = relationship(back_populates="application")


from app.models.job import JobPosting  # noqa: E402
