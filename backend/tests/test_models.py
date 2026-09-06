from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.db.base import Base


def test_required_tables_are_registered() -> None:
    configure_mappers()

    assert set(Base.metadata.tables) == {
        "ai_analysis_days",
        "ai_analysis_usage",
        "job_sources",
        "companies",
        "job_postings",
        "job_posting_snapshots",
        "candidate_profiles",
        "job_scores",
        "job_ai_analyses",
        "applications",
        "crawl_runs",
        "daily_recommendation_batches",
        "daily_recommendation_items",
        "ecosystem_organizations",
        "ecosystem_programs",
        "ecosystem_crawl_runs",
    }


def test_job_posting_contains_tracking_and_deduplication_fields() -> None:
    columns = Base.metadata.tables["job_postings"].columns

    for name in [
        "first_seen_at",
        "last_seen_at",
        "last_changed_at",
        "is_hidden",
        "is_favorite",
        "hiring_process",
        "has_coding_test",
        "interview_count",
        "content_hash",
        "duplicate_group_id",
        "is_primary_posting",
        "duplicate_reason",
    ]:
        assert name in columns


def test_score_keeps_explainability_fields() -> None:
    columns = Base.metadata.tables["job_scores"].columns

    for name in ["matching_reasons", "missing_skills", "risk_notes", "evidence_json"]:
        assert name in columns


def test_ai_analysis_cache_stores_only_structured_output_and_invalidation_metadata() -> None:
    columns = Base.metadata.tables["job_ai_analyses"].columns

    assert {
        "job_posting_id",
        "candidate_profile_id",
        "analysis_type",
        "provider",
        "model",
        "input_hash",
        "payload_json",
        "generated_at",
    }.issubset(columns.keys())
    assert "prompt" not in columns
    assert "candidate_profile" not in columns


def test_company_keeps_structured_public_facts() -> None:
    columns = Base.metadata.tables["companies"].columns

    assert {
        "employee_count",
        "developer_count",
        "profitability_status",
        "financial_history",
        "funding_history",
        "facts_source_urls",
        "facts_updated_at",
        "groupby_profile_updated_at",
        "dart_corp_code",
    }.issubset(columns.keys())


def test_daily_recommendation_history_stores_only_job_and_score_snapshots() -> None:
    batch_columns = Base.metadata.tables["daily_recommendation_batches"].columns
    item_columns = Base.metadata.tables["daily_recommendation_items"].columns

    assert {"recommendation_date", "generated_at", "slack_status"}.issubset(batch_columns.keys())
    assert {"job_posting_id", "rank", "fit_score", "application_value_score"}.issubset(
        item_columns.keys()
    )
    assert "candidate_profile" not in item_columns
    assert "resume_text" not in item_columns


def test_source_external_id_is_unique_per_source() -> None:
    constraints = Base.metadata.tables["job_postings"].constraints

    assert any(constraint.name == "uq_job_source_external_id" for constraint in constraints)


def test_ecosystem_programs_keep_public_url_and_seen_timestamps() -> None:
    columns = Base.metadata.tables["ecosystem_programs"].columns

    assert {"url", "normalized_title", "first_seen_at", "last_seen_at", "is_open"}.issubset(
        columns.keys()
    )
