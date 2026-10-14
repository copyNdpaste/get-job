"""Record public status-check evidence separately from publication dates."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261014_0015"
down_revision = "20261014_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_postings", sa.Column("availability_check", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_postings", "availability_check")
