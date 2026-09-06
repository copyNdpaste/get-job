from typing import Any

from sqlalchemy import JSON, BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class CandidateProfile(TimestampMixin, Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)

    scores: Mapped[list["JobScore"]] = relationship(
        back_populates="candidate_profile", cascade="all, delete-orphan"
    )


from app.models.score import JobScore  # noqa: E402
