"""Add durable job visibility state.

Revision ID: 20260712_0002
Revises: 20260712_0001
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0002"
down_revision: str | None = "20260712_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_job_postings_is_hidden", "job_postings", ["is_hidden"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_is_hidden", table_name="job_postings")
    op.drop_column("job_postings", "is_hidden")
