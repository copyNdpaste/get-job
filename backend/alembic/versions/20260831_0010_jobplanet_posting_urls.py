"""Correct persisted JobPlanet posting URLs.

Revision ID: 20260831_0010
Revises: 20260827_0009
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0010"
down_revision: str | None = "20260827_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUERY_URL_PREFIX = "https://www.jobplanet.co.kr/job/search?posting_ids%5B%5D="
LEGACY_URL_PREFIX = "https://www.jobplanet.co.kr/job/search/"


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE job_postings
            SET url = :query_prefix || external_job_id,
                canonical_url = :query_prefix || external_job_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE source_id IN (
                SELECT id FROM job_sources WHERE name = 'jobplanet'
            )
              AND (
                  url LIKE :legacy_pattern
                  OR canonical_url LIKE :legacy_pattern
              )
            """
        ),
        {
            "query_prefix": QUERY_URL_PREFIX,
            "legacy_pattern": f"{LEGACY_URL_PREFIX}%",
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE job_postings
            SET url = :legacy_prefix || external_job_id,
                canonical_url = :legacy_prefix || external_job_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE source_id IN (
                SELECT id FROM job_sources WHERE name = 'jobplanet'
            )
              AND (
                  url = :query_prefix || external_job_id
                  OR canonical_url = :query_prefix || external_job_id
              )
            """
        ),
        {
            "legacy_prefix": LEGACY_URL_PREFIX,
            "query_prefix": QUERY_URL_PREFIX,
        },
    )
