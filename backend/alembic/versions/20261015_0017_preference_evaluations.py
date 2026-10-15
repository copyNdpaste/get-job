"""Persistent, resumable preference scoring queue."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261015_0017"
down_revision = "20261015_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preference_evaluations",
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("model", sa.String(120)),
        sa.Column("error_code", sa.String(50)),
        sa.Column("evaluation", JSONB()),
    )
    op.create_index("ix_preference_ready", "preference_evaluations", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("preference_evaluations")
