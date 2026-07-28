import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import approx

from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.auth.ui_middleware import UIBasicAuthMiddleware
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


def test_ui_middleware_redirects_unauthenticated_users_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-production")
    get_settings.cache_clear()
    try:
        app = FastAPI()
        app.add_middleware(UIBasicAuthMiddleware)

        @app.get("/login")
        async def login_page() -> dict[str, bool]:
            return {"login": True}

        @app.get("/settings")
        async def settings_page() -> dict[str, bool]:
            return {"settings": True}

        client = TestClient(app)
        blocked = client.get("/settings", follow_redirects=False)
        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/login"
        assert client.get("/login").status_code == 200

        token = create_session_token("jonata")
        client.cookies.set(SESSION_COOKIE_NAME, token)
        allowed = client.get("/settings", follow_redirects=False)
        assert allowed.status_code == 200
    finally:
        get_settings.cache_clear()


def test_docs_are_not_public_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-production")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app(include_ui=False))
        response = client.get("/docs", follow_redirects=False)
        assert response.status_code != 200
    finally:
        get_settings.cache_clear()
