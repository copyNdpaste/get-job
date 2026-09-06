"""Add structured company size, financial, and funding facts.

Revision ID: 20260813_0006
Revises: 20260714_0005
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0006"
down_revision: str | None = "20260714_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("companies", sa.Column("employee_count", sa.Integer()))
    op.add_column("companies", sa.Column("developer_count", sa.Integer()))
    op.add_column("companies", sa.Column("employee_count_source", sa.String(100)))
    op.add_column("companies", sa.Column("employee_count_as_of", sa.DateTime(timezone=True)))
    op.add_column(
        "companies",
        sa.Column(
            "profitability_status",
            sa.String(30),
            server_default="undisclosed",
            nullable=False,
        ),
    )
    op.add_column(
        "companies",
        sa.Column("financial_history", jsonb, server_default="[]", nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("funding_history", jsonb, server_default="[]", nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("facts_source_urls", jsonb, server_default="[]", nullable=False),
    )
    op.add_column("companies", sa.Column("facts_updated_at", sa.DateTime(timezone=True)))
    op.add_column("companies", sa.Column("business_registration_number", sa.String(20)))
    op.add_column("companies", sa.Column("dart_corp_code", sa.String(8)))
    op.create_index("ix_companies_dart_corp_code", "companies", ["dart_corp_code"])


def downgrade() -> None:
    op.drop_index("ix_companies_dart_corp_code", table_name="companies")
    for column in (
        "dart_corp_code",
        "business_registration_number",
        "facts_updated_at",
        "facts_source_urls",
        "funding_history",
        "financial_history",
        "profitability_status",
        "employee_count_as_of",
        "employee_count_source",
        "developer_count",
        "employee_count",
    ):
        op.drop_column("companies", column)
