"""Create initial job analysis schema.

Revision ID: 20260712_0001
Revises:
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260712_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

jsonb = postgresql.JSONB(astext_type=sa.Text())


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "job_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("crawler_type", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("industry", sa.String(255)),
        sa.Column("company_size", sa.String(100)),
        sa.Column("investment_stage", sa.String(100)),
        sa.Column("total_investment", sa.String(100)),
        sa.Column("annual_revenue", sa.String(100)),
        sa.Column("location", sa.String(500)),
        sa.Column("website", sa.String(2048)),
        sa.Column("source_urls", jsonb, nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("profile_json", jsonb, nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_id",
            sa.BigInteger(),
            sa.ForeignKey("job_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pages_visited", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_log", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_crawl_runs_crawl_run_status"),
        ),
    )
    op.create_index("ix_crawl_runs_source_id", "crawl_runs", ["source_id"])
    op.create_index("ix_crawl_runs_status", "crawl_runs", ["status"])
    op.create_table(
        "job_postings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_id",
            sa.BigInteger(),
            sa.ForeignKey("job_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_job_id", sa.String(255), nullable=False),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("job_category", sa.String(100)),
        sa.Column("employment_type", sa.String(100)),
        sa.Column("description_raw", sa.Text()),
        sa.Column("description_text", sa.Text()),
        sa.Column("main_tasks", jsonb, nullable=False),
        sa.Column("requirements", jsonb, nullable=False),
        sa.Column("preferred_requirements", jsonb, nullable=False),
        sa.Column("benefits", jsonb, nullable=False),
        sa.Column("tech_stack", jsonb, nullable=False),
        sa.Column("experience_text", sa.String(500)),
        sa.Column("min_experience", sa.Integer()),
        sa.Column("max_experience", sa.Integer()),
        sa.Column("experience_type", sa.String(30)),
        sa.Column("is_experience_eligible", sa.Boolean()),
        sa.Column("experience_reason", sa.Text()),
        sa.Column("salary_min", sa.Numeric(14, 2)),
        sa.Column("salary_max", sa.Numeric(14, 2)),
        sa.Column("salary_text", sa.String(500)),
        sa.Column("location", sa.String(500)),
        sa.Column("remote_type", sa.String(100)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("crawl_status", sa.String(30), nullable=False),
        sa.Column("crawl_error", sa.Text()),
        sa.Column("duplicate_group_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_primary_posting", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("duplicate_reason", sa.String(255)),
        *timestamp_columns(),
        sa.UniqueConstraint("source_id", "external_job_id", name="uq_job_source_external_id"),
    )
    for name, columns in [
        ("ix_job_postings_source_id", ["source_id"]),
        ("ix_job_postings_company_id", ["company_id"]),
        ("ix_job_postings_normalized_title", ["normalized_title"]),
        ("ix_job_postings_canonical_url", ["canonical_url"]),
        ("ix_job_postings_job_category", ["job_category"]),
        ("ix_job_postings_location", ["location"]),
        ("ix_job_postings_remote_type", ["remote_type"]),
        ("ix_job_postings_content_hash", ["content_hash"]),
        ("ix_job_postings_duplicate_group_id", ["duplicate_group_id"]),
        ("ix_job_company_title", ["company_id", "normalized_title"]),
        ("ix_job_active_last_seen", ["is_active", "last_seen_at"]),
    ]:
        op.create_index(name, "job_postings", columns)
    op.create_table(
        "job_posting_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_posting_id",
            sa.BigInteger(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("structured_content", jsonb, nullable=False),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_posting_id", "content_hash", name="uq_snapshot_job_content_hash"),
    )
    op.create_index(
        "ix_job_posting_snapshots_job_posting_id", "job_posting_snapshots", ["job_posting_id"]
    )
    op.create_table(
        "job_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_posting_id",
            sa.BigInteger(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_profile_id",
            sa.BigInteger(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("eligibility_score", sa.Float(), nullable=False),
        sa.Column("backend_score", sa.Float(), nullable=False),
        sa.Column("database_score", sa.Float(), nullable=False),
        sa.Column("system_design_score", sa.Float(), nullable=False),
        sa.Column("infra_score", sa.Float(), nullable=False),
        sa.Column("messaging_score", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("ai_product_score", sa.Float(), nullable=False),
        sa.Column("product_ownership_score", sa.Float(), nullable=False),
        sa.Column("collaboration_score", sa.Float(), nullable=False),
        sa.Column("domain_score", sa.Float(), nullable=False),
        sa.Column("salary_career_score", sa.Float(), nullable=False),
        sa.Column("skill_gap_score", sa.Float(), nullable=False),
        sa.Column("total_fit_score", sa.Float(), nullable=False),
        sa.Column("application_value_score", sa.Float(), nullable=False),
        sa.Column("application_probability_score", sa.Float(), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("matching_reasons", jsonb, nullable=False),
        sa.Column("missing_skills", jsonb, nullable=False),
        sa.Column("risk_notes", jsonb, nullable=False),
        sa.Column("evidence_json", jsonb, nullable=False),
        sa.Column("labels", jsonb, nullable=False),
        sa.Column("recommended_resume_version", sa.String(50)),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scoring_version", sa.String(50), nullable=False),
        sa.UniqueConstraint(
            "job_posting_id", "candidate_profile_id", name="uq_score_job_candidate"
        ),
        sa.CheckConstraint(
            "grade IN ('S', 'A', 'B', 'C', 'Excluded')",
            name=op.f("ck_job_scores_job_grade"),
        ),
        sa.CheckConstraint(
            "total_fit_score BETWEEN 0 AND 100",
            name=op.f("ck_job_scores_total_fit_score_range"),
        ),
        sa.CheckConstraint(
            "application_value_score BETWEEN 0 AND 100",
            name=op.f("ck_job_scores_application_value_score_range"),
        ),
        sa.CheckConstraint(
            "application_probability_score BETWEEN 0 AND 100",
            name=op.f("ck_job_scores_application_probability_score_range"),
        ),
    )
    for column in [
        "job_posting_id",
        "candidate_profile_id",
        "total_fit_score",
        "application_value_score",
        "application_probability_score",
        "grade",
        "priority",
    ]:
        op.create_index(f"ix_job_scores_{column}", "job_scores", [column])
    op.create_table(
        "applications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_posting_id",
            sa.BigInteger(),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(30), server_default="not_reviewed", nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("resume_version", sa.String(100)),
        sa.Column("contact_channel", sa.String(100)),
        sa.Column("interview_date", sa.Date()),
        sa.Column("expected_salary", sa.Numeric(14, 2)),
        sa.Column("memo", sa.Text()),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('not_reviewed', 'interested', 'resume_preparing', 'applied', "
            "'document_passed', 'interview', 'offer', 'rejected', 'withdrawn')",
            name=op.f("ck_applications_application_status"),
        ),
    )
    op.create_index("ix_applications_status", "applications", ["status"])


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("job_scores")
    op.drop_table("job_posting_snapshots")
    op.drop_table("job_postings")
    op.drop_table("crawl_runs")
    op.drop_table("candidate_profiles")
    op.drop_table("companies")
    op.drop_table("job_sources")
