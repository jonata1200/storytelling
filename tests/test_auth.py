from fastapi.testclient import TestClient
from pytest import approx

from app.factory import create_app


def test_auth_me_is_not_registered() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 404


def test_health_live_does_not_require_authentication() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_operational_api_endpoint_does_not_require_authentication() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.post(
        "/api/v1/costs/estimate",
        json={
            "generation_count": 2,
            "average_units": "10",
            "unit_cost": "0.5",
            "uncertainty_ratio": "0.1",
        },
    )

    assert response.status_code == 200
    assert float(response.json()["estimated"]) == approx(10.0)
