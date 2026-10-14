import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.crawler.domain import CollectedJob
from app.crawler.persistence import upsert_collected_job
from app.db.base import Base
from app.db.session import get_db
from app.job_locations import map_location, source_coordinates, validated_point
from app.main import app
from app.models import JobPosting, JobSource


@pytest.mark.parametrize(
    "lat,lng", [(None, 127), (True, 127), ("nan", 127), (91, 127), (37, 181), (0, 0)]
)
def test_invalid_coordinates_are_not_mapped(lat, lng):
    assert validated_point(lat, lng) is None


def test_only_explicit_workplace_geometry_is_used():
    raw = json.dumps(
        {
            "data": {
                "job": {
                    "address": {
                        "geo_location": {
                            "location": {"lat": 37.5, "lng": 127.1},
                            "viewport": {"lat": 38, "lng": 128},
                        }
                    }
                }
            }
        }
    )
    assert source_coordinates("wanted", raw) == {
        "latitude": 37.5,
        "longitude": 127.1,
        "provider": "wanted",
    }
    assert source_coordinates("other", raw) is None
    assert source_coordinates("wanted", "<html>") is None
    assert map_location("서울시 강남구 가상로 123", None)["precision"] == "region"
    assert map_location("경기도 광주시", None)["precision"] == "unknown"
    assert map_location("재택근무", None)["latitude"] is None


def test_map_uses_same_filters_and_year_and_avoids_job_bodies():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for source_name, posted, stack in [
            ("wanted", datetime(2026, 1, 1, tzinfo=UTC), ["Python"]),
            ("jobplanet", datetime(2026, 2, 1, tzinfo=UTC), ["Python"]),
            ("jumpit", datetime(2024, 1, 1, tzinfo=UTC), ["Python"]),
            ("rallit", None, ["Java"]),
        ]:
            source = JobSource(
                name=source_name, base_url=f"https://{source_name}.example", crawler_type="http"
            )
            session.add(source)
            session.flush()
            upsert_collected_job(
                session,
                source,
                CollectedJob(
                    source_name=source_name,
                    external_job_id="synthetic",
                    company_name="가상 기업",
                    title="Python Backend",
                    url=f"https://{source_name}.example/jobs/1",
                    description_raw="synthetic",
                    description_text="synthetic",
                    location="서울시 강남구 가상로 123",
                    posted_at=posted,
                    tech_stack=stack,
                ),
            )
        session.commit()
        statements = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda conn, cursor, statement, parameters, context, many: statements.append(statement),
        )
        app.dependency_overrides[get_db] = lambda: session
        try:
            client = TestClient(app)
            filters = "posted_in_year=2026&exclude_source=jobplanet&tech=Python"
            listing = client.get(f"/api/jobs?{filters}").json()
            statements.clear()
            response = client.get(f"/api/jobs?map_view=true&limit=5000&{filters}")
            assert response.status_code == 200, response.text
            mapped = response.json()
            assert mapped["total"] == listing["total"] == 1
            assert [j["id"] for j in mapped["items"]] == [j["id"] for j in listing["items"]]
            assert mapped["items"][0]["precision"] == "region"
            assert all(
                "description_raw" not in query and "description_text" not in query
                for query in statements
            )
            assert client.get("/api/jobs?limit=5000").status_code == 422
            assert (
                client.get(
                    "/api/jobs?map_view=true&posted_in_year=2026&include_unknown_posted=true"
                ).json()["total"]
                == 3
            )
            row = session.query(JobPosting).join(JobSource).filter(JobSource.name == "wanted").one()
            row.posted_at = datetime(2025, 12, 31, 15, 0, tzinfo=UTC)
            session.commit()
            assert client.get(f"/api/jobs?map_view=true&{filters}").json()["total"] == 1
        finally:
            app.dependency_overrides.clear()


def test_map_projection_stays_fast_for_many_rows():
    # Large synthetic bodies deliberately magnify an accidental full-row map query.
    from time import perf_counter

    from app.api.jobs import list_jobs
    from app.models import Company

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = JobSource(name="wanted", base_url="https://example.invalid", crawler_type="http")
        company = Company(name="Synthetic", normalized_name="synthetic", source_urls=[])
        session.add_all([source, company])
        session.flush()
        now = datetime(2026, 10, 1, tzinfo=UTC)
        session.add_all(
            [
                JobPosting(
                    id=index + 1,
                    source_id=source.id,
                    company_id=company.id,
                    external_job_id=str(index),
                    title="Python developer",
                    normalized_title="python developer",
                    url=f"https://example.invalid/jobs/{index}",
                    canonical_url=f"https://example.invalid/jobs/{index}",
                    content_hash=str(index),
                    description_raw="X" * 50000,
                    description_text="Y" * 50000,
                    tech_stack=["Python"],
                    location="서울시 강남구",
                    posted_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_changed_at=now,
                )
                for index in range(500)
            ]
        )
        session.commit()
        start = perf_counter()
        result = list_jobs(
            session,
            map_view=True,
            limit=5000,
            posted_in_year=2026,
            exclude_source=["jobplanet"],
            tech=["Python"],
        )
        elapsed = perf_counter() - start
        assert result.total == len(result.items) == 500
        assert elapsed < 2.0, f"Map query took {elapsed:.3f}s for 500 jobs"
