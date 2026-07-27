import pytest
from fastapi.testclient import TestClient
from pytest import approx

from app.config.settings import get_settings
from app.factory import create_app


def test_auth_me_uses_local_user_in_local_environment() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {"username": "local-user"}


def test_health_live_does_not_require_authentication() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_live_health() -> None:
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


def test_operational_api_endpoint_requires_authentication_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-production")
    get_settings.cache_clear()
    try:
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
        assert response.status_code == 401
        assert client.get("/api/v1/health/live").status_code == 200
        assert client.get("/api/v1/health/ready").status_code == 401
    finally:
        get_settings.cache_clear()
