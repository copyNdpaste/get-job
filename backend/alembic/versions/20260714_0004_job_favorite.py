"""Add durable job favorite state.

Revision ID: 20260714_0004
Revises: 20260714_0003
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260714_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("is_favorite", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_job_postings_is_favorite", "job_postings", ["is_favorite"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_is_favorite", table_name="job_postings")
    op.drop_column("job_postings", "is_favorite")
