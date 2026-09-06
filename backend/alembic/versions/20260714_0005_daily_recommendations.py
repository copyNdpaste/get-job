"""Add local daily recommendation history.

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_recommendation_batches",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("recommendation_date", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slack_status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("slack_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_recommendation_batches")),
        sa.UniqueConstraint(
            "recommendation_date",
            name=op.f("uq_daily_recommendation_batches_recommendation_date"),
        ),
    )
    op.create_index(
        op.f("ix_daily_recommendation_batches_recommendation_date"),
        "daily_recommendation_batches",
        ["recommendation_date"],
        unique=True,
    )
    op.create_table(
        "daily_recommendation_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("job_posting_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=False),
        sa.Column("application_value_score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["daily_recommendation_batches.id"],
            name=op.f("fk_daily_recommendation_items_batch_id_daily_recommendation_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"],
            ["job_postings.id"],
            name=op.f("fk_daily_recommendation_items_job_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_recommendation_items")),
        sa.UniqueConstraint("batch_id", "job_posting_id", name="uq_daily_batch_job"),
    )
    op.create_index(
        op.f("ix_daily_recommendation_items_batch_id"),
        "daily_recommendation_items",
        ["batch_id"],
    )
    op.create_index(
        op.f("ix_daily_recommendation_items_job_posting_id"),
        "daily_recommendation_items",
        ["job_posting_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_daily_recommendation_items_job_posting_id"),
        table_name="daily_recommendation_items",
    )
    op.drop_index(
        op.f("ix_daily_recommendation_items_batch_id"),
        table_name="daily_recommendation_items",
    )
    op.drop_table("daily_recommendation_items")
    op.drop_index(
        op.f("ix_daily_recommendation_batches_recommendation_date"),
        table_name="daily_recommendation_batches",
    )
    op.drop_table("daily_recommendation_batches")
