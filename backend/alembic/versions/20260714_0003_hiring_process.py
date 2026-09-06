"""Add structured hiring process fields.

Revision ID: 20260714_0003
Revises: 20260712_0002
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260714_0003"
down_revision: str | None = "20260712_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column(
            "hiring_process",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("job_postings", sa.Column("has_coding_test", sa.Boolean(), nullable=True))
    op.add_column("job_postings", sa.Column("interview_count", sa.Integer(), nullable=True))
    op.create_index(
        "ix_job_postings_has_coding_test", "job_postings", ["has_coding_test"]
    )
    op.create_index("ix_job_postings_interview_count", "job_postings", ["interview_count"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_interview_count", table_name="job_postings")
    op.drop_index("ix_job_postings_has_coding_test", table_name="job_postings")
    op.drop_column("job_postings", "interview_count")
    op.drop_column("job_postings", "has_coding_test")
    op.drop_column("job_postings", "hiring_process")
