from fastapi.testclient import TestClient

from app.factory import create_app


def test_correlation_id_middleware_sets_response_header() -> None:
    client = TestClient(create_app(include_ui=False))

    response = client.get("/api/v1/health/live", headers={"x-correlation-id": "test-cid"})

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "test-cid"
    assert "x-process-time-ms" in response.headers
