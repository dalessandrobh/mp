from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok_and_current_mode():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert set(body["mode"]) == {
        "mock_marketplace",
        "mock_ads",
        "dry_run",
        "ai_autonomy_level",
        "llm_enabled",
    }


def test_response_carries_request_id():
    response = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
