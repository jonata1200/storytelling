from fastapi.testclient import TestClient

from app.factory import create_app


def test_auth_me_requires_basic_auth() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_auth_me_accepts_default_credentials() -> None:
    client = TestClient(create_app(include_ui=False))
    response = client.get("/api/v1/auth/me", auth=("admin", "admin"))
    assert response.status_code == 200
    assert response.json() == {"username": "admin"}
