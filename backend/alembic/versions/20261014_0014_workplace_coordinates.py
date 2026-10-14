"""Store authoritative public workplace coordinates without loading raw jobs in map queries."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261014_0014"
down_revision = "20261009_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_postings", sa.Column("workplace_coordinates", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_postings", "workplace_coordinates")
