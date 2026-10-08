"""Index visible active job list ordering, including source-filtered lists."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261009_0013"
down_revision: str | None = "20260906_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREDICATE = sa.text("is_primary_posting IS TRUE AND is_active IS TRUE AND is_hidden IS FALSE")
INDEXES = {
    "ix_job_visible_latest": [
        sa.text("coalesce(posted_at, first_seen_at) DESC"),
        sa.text("id DESC"),
    ],
    "ix_job_visible_source_latest": [
        "source_id",
        sa.text("coalesce(posted_at, first_seen_at) DESC"),
        sa.text("id DESC"),
    ],
    "ix_job_visible_collected": [sa.text("first_seen_at DESC"), sa.text("id DESC")],
}


def upgrade() -> None:
    for name, columns in INDEXES.items():
        op.create_index(name, "job_postings", columns, postgresql_where=PREDICATE)
    op.execute("ANALYZE job_postings")


def downgrade() -> None:
    for name in reversed(INDEXES):
        op.drop_index(name, table_name="job_postings")
