from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_rocketpunch_network_crawl_is_rejected_by_policy() -> None:
    response = TestClient(app).post("/api/crawl/rocketpunch", json={})

    assert response.status_code == 400
    assert "import-html" in response.json()["detail"]


def test_saramin_collection_requires_an_approved_official_api_key() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_enabled=False, saramin_api_key=None
    )
    try:
        response = TestClient(app).post("/api/crawl/saramin", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "공식 API 승인" in response.json()["detail"]
