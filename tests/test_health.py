from fastapi.testclient import TestClient

from app.factory import create_app


def test_live_health() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
