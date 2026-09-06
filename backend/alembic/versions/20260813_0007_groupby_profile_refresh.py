"""Track completed GroupBy company-profile refreshes.

Revision ID: 20260813_0007
Revises: 20260813_0006
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0007"
down_revision: str | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies", sa.Column("groupby_profile_updated_at", sa.DateTime(timezone=True))
    )
    op.execute(
        "UPDATE companies SET groupby_profile_updated_at = facts_updated_at "
        "WHERE jsonb_array_length(funding_history) > 0"
    )


def downgrade() -> None:
    op.drop_column("companies", "groupby_profile_updated_at")
