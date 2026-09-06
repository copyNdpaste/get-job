"""Add founder-fit metadata to ecosystem organizations.

Revision ID: 20260827_0009
Revises: 20260821_0008
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0009"
down_revision: str | None = "20260821_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ecosystem_organizations",
        sa.Column("fit_score", sa.Integer(), server_default="50", nullable=False),
    )
    op.add_column(
        "ecosystem_organizations",
        sa.Column("fit_reason", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "ecosystem_organizations",
        sa.Column("focus_tags", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column("ecosystem_organizations", sa.Column("source_url", sa.String(2048)))
    op.add_column("ecosystem_organizations", sa.Column("operating_scale", sa.String(80)))


def downgrade() -> None:
    op.drop_column("ecosystem_organizations", "operating_scale")
    op.drop_column("ecosystem_organizations", "source_url")
    op.drop_column("ecosystem_organizations", "focus_tags")
    op.drop_column("ecosystem_organizations", "fit_reason")
    op.drop_column("ecosystem_organizations", "fit_score")
