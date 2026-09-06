"""Content-free analysis call ledger and atomic daily reservations."""

import sqlalchemy as sa

from alembic import op

revision = "20260906_0012"
down_revision = "20260904_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_analysis_days",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("reviews", sa.Integer(), nullable=False),
    )
    op.create_table(
        "ai_analysis_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
    )
    op.create_index("ix_ai_analysis_usage_created_at", "ai_analysis_usage", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_analysis_usage")
    op.drop_table("ai_analysis_days")
