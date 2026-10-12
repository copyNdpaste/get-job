"""Regression tests for bounded detail loading and filtered query latency."""

import statistics
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.jobs import _base_query, _matches_post_filters, list_jobs, router
from app.db.base import Base
from app.db.session import get_db
from app.models import CandidateProfile, Company, JobPosting, JobScore, JobSource


@pytest.fixture(scope="module")
def filter_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(JobSource),
            [
                {"id": i, "name": name, "base_url": "https://example.com", "crawler_type": "http"}
                for i, name in enumerate(["wanted", "jobplanet", "rallit"], 1)
            ],
        )
        connection.execute(
            insert(Company), {"id": 1, "name": "Synthetic", "normalized_name": "synthetic"}
        )
        connection.execute(
            insert(CandidateProfile), {"id": 1, "name": "Synthetic", "profile_json": {}}
        )
        connection.execute(
            insert(JobPosting),
            [
                {
                    "id": i,
                    "source_id": i % 3 + 1,
                    "company_id": 1,
                    "external_job_id": str(i),
                    "title": "Python Backend Engineer",
                    "normalized_title": "python backend engineer",
                    "url": f"https://example.com/jobs/{i}",
                    "canonical_url": f"https://example.com/jobs/{i}",
                    "tech_stack": ["Python", "Django", "JavaScript"],
                    "experience_text": "경력 3~7년",
                    "description_text": "synthetic body " * 600,
                    "description_raw": "synthetic html " * 600,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "last_changed_at": now,
                    "content_hash": str(i),
                    "is_active": True,
                    "is_primary_posting": True,
                    "is_hidden": False,
                }
                for i in range(1, 3001)
            ],
        )
        connection.execute(
            insert(JobScore),
            [
                {
                    "id": i,
                    "job_posting_id": i,
                    "candidate_profile_id": 1,
                    "total_fit_score": 80,
                    "grade": "A",
                    "scored_at": now,
                    "scoring_version": "synthetic",
                    "evidence_json": {"unused_detail": "synthetic " * 600},
                }
                for i in range(1, 3001)
            ],
        )
    yield engine
    engine.dispose()


def test_filtered_request_loads_details_only_for_requested_page(filter_engine):
    loaded = []

    def on_load(target, _context):
        loaded.append(target.id)

    event.listen(JobPosting, "load", on_load)
    try:
        with Session(filter_engine) as session:
            response = list_jobs(
                session=session,
                tech=["Python"],
                exclude_tech=["Java"],
                experience=["career"],
                min_years=3,
                max_years=8,
                sort="collected",
                limit=25,
                offset=75,
            )
            assert response.total == 3000
            assert [item.id for item in response.items] == list(range(2925, 2900, -1))
            assert len(loaded) == 25
    finally:
        event.remove(JobPosting, "load", on_load)


def test_multiple_excluded_sources_compose_with_other_filters(filter_engine):
    app = FastAPI()
    app.include_router(router)

    def db():
        with Session(filter_engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        response = client.get(
            "/api/jobs",
            params=[
                ("exclude_source", "jobplanet"),
                ("exclude_source", "wanted"),
                ("tech", "Python"),
                ("min_years", "3"),
                ("min_fit_score", "70"),
                ("limit", "25"),
                ("offset", "25"),
            ],
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1000
        assert len(response.json()["items"]) == 25
        assert {item["source"] for item in response.json()["items"]} == {"rallit"}
        assert (
            client.get(
                "/api/jobs", params=[("source", "wanted"), ("exclude_source", "wanted")]
            ).json()["total"]
            == 0
        )
        assert client.get("/api/jobs", params=[("exclude_source", "x" * 51)]).status_code == 400


def test_filter_latency_improves_against_full_detail_scan(filter_engine):
    """Compare both paths on the same synthetic data, with separate sessions."""
    old_times, new_times = [], []
    for _ in range(3):
        with Session(filter_engine) as session:
            started = time.perf_counter()
            legacy_rows = [
                row
                for row in session.execute(_base_query()).all()
                if _matches_post_filters(row, ["Python"], ["Java"], {"career"}, 3, 8)
            ]
            old_times.append(time.perf_counter() - started)
            expected_total = len(legacy_rows)
            del legacy_rows
        with Session(filter_engine) as session:
            started = time.perf_counter()
            response = list_jobs(
                session=session,
                tech=["Python"],
                exclude_tech=["Java"],
                experience=["career"],
                min_years=3,
                max_years=8,
                limit=25,
            )
            new_times.append(time.perf_counter() - started)
            assert response.total == expected_total
    old_median, new_median = statistics.median(old_times), statistics.median(new_times)
    assert new_median < old_median * 0.65, (old_times, new_times)
    assert new_median < 1.0, new_times


def test_posted_period_unknown_opt_in_never_uses_collection_date(filter_engine):
    from datetime import timedelta

    with Session(filter_engine) as session:
        now = datetime.now(UTC)
        old = session.get(JobPosting, 1)
        recent = session.get(JobPosting, 2)
        old.posted_at = now - timedelta(days=60)
        recent.posted_at = now - timedelta(days=2)
        # All records were collected today. That must not make old/unknown dates recent.
        session.flush()
        strict = list_jobs(session=session, posted_within_days=30, tech=["Python"], limit=5)
        assert strict.total == 1
        assert strict.items[0].id == 2
        inclusive = list_jobs(session=session, posted_within_days=30,
                             include_unknown_posted=True, tech=["Python"], limit=5)
        assert inclusive.total == 2999
        assert all(item.id != 1 for item in inclusive.items)
        empty_period = list_jobs(session=session, include_unknown_posted=True, limit=5)
        assert empty_period.total == 3000
