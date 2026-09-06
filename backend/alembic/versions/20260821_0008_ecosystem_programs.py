"""Add startup ecosystem organizations and public program monitoring.

Revision ID: 20260821_0008
Revises: 20260813_0007
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0008"
down_revision: str | None = "20260813_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecosystem_organizations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("organization_type", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("website_url", sa.String(2048), nullable=False),
        sa.Column("program_url", sa.String(2048)),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_ecosystem_organizations_slug", "ecosystem_organizations", ["slug"])
    op.create_table(
        "ecosystem_programs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("program_type", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("deadline_text", sa.String(200)),
        sa.Column("is_open", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["ecosystem_organizations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "organization_id", "normalized_title", name="uq_ecosystem_program_title"
        ),
    )
    op.create_index(
        "ix_ecosystem_programs_organization_id", "ecosystem_programs", ["organization_id"]
    )
    op.create_table(
        "ecosystem_crawl_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages_visited", sa.Integer(), server_default="0", nullable=False),
        sa.Column("programs_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("programs_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("programs_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_log", sa.Text()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["ecosystem_organizations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ecosystem_crawl_runs_organization_id", "ecosystem_crawl_runs", ["organization_id"]
    )
    op.create_index("ix_ecosystem_crawl_runs_status", "ecosystem_crawl_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ecosystem_crawl_runs_status", table_name="ecosystem_crawl_runs")
    op.drop_index("ix_ecosystem_crawl_runs_organization_id", table_name="ecosystem_crawl_runs")
    op.drop_table("ecosystem_crawl_runs")
    op.drop_index("ix_ecosystem_programs_organization_id", table_name="ecosystem_programs")
    op.drop_table("ecosystem_programs")
    op.drop_index("ix_ecosystem_organizations_slug", table_name="ecosystem_organizations")
    op.drop_table("ecosystem_organizations")
