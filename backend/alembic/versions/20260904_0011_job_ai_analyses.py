"""Cache structured LLM analyses for job and candidate inputs.

Revision ID: 20260904_0011
Revises: 20260831_0010
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260904_0011"
down_revision: str | None = "20260831_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_ai_analyses",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_posting_id",
            sa.BigInteger(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_profile_id",
            sa.BigInteger(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_posting_id",
            "candidate_profile_id",
            "analysis_type",
            "provider",
            "model",
            name="uq_job_ai_analysis_identity",
        ),
    )
    op.create_index(
        "ix_job_ai_analyses_job_posting_id", "job_ai_analyses", ["job_posting_id"]
    )
    op.create_index(
        "ix_job_ai_analyses_candidate_profile_id",
        "job_ai_analyses",
        ["candidate_profile_id"],
    )
    op.create_index("ix_job_ai_analyses_input_hash", "job_ai_analyses", ["input_hash"])


def downgrade() -> None:
    op.drop_index("ix_job_ai_analyses_input_hash", table_name="job_ai_analyses")
    op.drop_index("ix_job_ai_analyses_candidate_profile_id", table_name="job_ai_analyses")
    op.drop_index("ix_job_ai_analyses_job_posting_id", table_name="job_ai_analyses")
    op.drop_table("job_ai_analyses")
