"""Store private source documents in the local database."""

import sqlalchemy as sa

from alembic import op

revision = "20261015_0016"
down_revision = "20261014_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("private_documents")
