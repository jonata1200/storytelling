from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

import app.auth.service as auth_service
from app.auth.passwords import (
    hash_password,
    normalize_email,
    validate_strong_password,
    verify_password,
)
from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.config.settings import get_settings
from app.factory import create_app
from app.projects.models import User


class _FakeAuthSession:
    def __init__(self, user_count: int = 0) -> None:
        self.user_count = user_count
        self.added: list[User] = []
        self.committed = False
        self.refreshed: list[User] = []

    def add(self, user: object) -> None:
        assert isinstance(user, User)
        self.added.append(user)

    async def commit(self) -> None:
        self.committed = True

    async def scalar(self, _statement: object) -> int:
        return self.user_count

    async def refresh(self, user: object) -> None:
        assert isinstance(user, User)
        self.refreshed.append(user)


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


def test_normalize_email_requires_valid_email() -> None:
    assert normalize_email("  USER@Example.COM ") == "user@example.com"

    with pytest.raises(ValueError, match="e-mail válido"):
        normalize_email("sem-email")


def test_strong_password_validation() -> None:
    validate_strong_password("Se1!ha", "user@example.com")

    with pytest.raises(ValueError, match="pelo menos 6"):
        validate_strong_password("S1!a")
    with pytest.raises(ValueError, match="maiúscula"):
        validate_strong_password("senhaforte123!")
    with pytest.raises(ValueError, match="partes do e-mail"):
        validate_strong_password("UserSenhaForte123!", "user@example.com")


def test_password_hash_verification_is_defensive() -> None:
    stored_hash = hash_password("Se1!ha")

    assert verify_password("Se1!ha", stored_hash)
    assert not verify_password("senha-errada", stored_hash)
    assert not verify_password("Se1!ha", "pbkdf2_sha256$260000$not-hex$digest")
    assert not verify_password("Se1!ha", "broken")


@pytest.mark.asyncio
async def test_register_user_normalizes_email_and_hashes_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_USER_REGISTRATION", "true")
    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    get_settings.cache_clear()

    async def missing_user(_session: AsyncSession, _email: str) -> User | None:
        return None

    monkeypatch.setattr(auth_service, "get_user_by_email", missing_user)
    fake_session = _FakeAuthSession()

    user = await auth_service.register_user(
        cast(AsyncSession, fake_session),
        "  USER@Example.COM ",
        "Se1!ha",
        "  Jonata  ",
    )

    assert fake_session.added == [user]
    assert fake_session.committed
    assert fake_session.refreshed == [user]
    assert user.email == "user@example.com"
    assert user.display_name == "Jonata"
    assert user.password_hash != "Se1!ha"
    assert verify_password("Se1!ha", user.password_hash)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_register_user_rejects_duplicate_email(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_user = User(
        email="user@example.com",
        display_name="User",
        password_hash=hash_password("Se1!ha"),
    )

    async def found_user(_session: AsyncSession, _email: str) -> User | None:
        return existing_user

    monkeypatch.setattr(auth_service, "get_user_by_email", found_user)
    fake_session = _FakeAuthSession()

    with pytest.raises(ValueError, match="já está cadastrado"):
        await auth_service.register_user(
            cast(AsyncSession, fake_session),
            "user@example.com",
            "Se1!ha",
        )

    assert fake_session.added == []
    assert not fake_session.committed


@pytest.mark.asyncio
async def test_register_user_rejects_second_user_in_single_user_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_USER_REGISTRATION", "true")
    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    get_settings.cache_clear()

    async def missing_user(_session: AsyncSession, _email: str) -> User | None:
        return None

    monkeypatch.setattr(auth_service, "get_user_by_email", missing_user)
    fake_session = _FakeAuthSession(user_count=1)

    try:
        with pytest.raises(ValueError, match="já possui um usuário"):
            await auth_service.register_user(
                cast(AsyncSession, fake_session),
                "new@example.com",
                "Se1!ha",
            )
    finally:
        get_settings.cache_clear()

    assert fake_session.added == []
    assert not fake_session.committed


@pytest.mark.asyncio
async def test_register_user_rejects_when_registration_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_USER_REGISTRATION", "false")
    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    get_settings.cache_clear()

    async def missing_user(_session: AsyncSession, _email: str) -> User | None:
        return None

    monkeypatch.setattr(auth_service, "get_user_by_email", missing_user)
    fake_session = _FakeAuthSession()

    try:
        with pytest.raises(ValueError, match="Cadastro desativado"):
            await auth_service.register_user(
                cast(AsyncSession, fake_session),
                "new@example.com",
                "Se1!ha",
            )
    finally:
        get_settings.cache_clear()

    assert fake_session.added == []
    assert not fake_session.committed


@pytest.mark.asyncio
async def test_authenticate_user_checks_email_and_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_user = User(
        email="user@example.com",
        display_name="User",
        password_hash=hash_password("Se1!ha"),
    )

    async def found_user(_session: AsyncSession, _email: str) -> User | None:
        return existing_user

    monkeypatch.setattr(auth_service, "get_user_by_email", found_user)
    fake_session = cast(AsyncSession, _FakeAuthSession())

    assert await auth_service.authenticate_user(fake_session, "USER@example.com", "Se1!ha")
    assert await auth_service.authenticate_user(fake_session, "USER@example.com", "errada") is None


def test_login_and_register_pages_use_email_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_USER_REGISTRATION", "true")
    monkeypatch.setenv("SINGLE_USER_MODE", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app(include_ui=False))

        login_response = client.get("/login")
        register_response = client.get("/register")

        assert login_response.status_code == 200
        assert register_response.status_code == 200
        assert 'name="email" type="email"' in login_response.text
        assert 'name="email" type="email"' in register_response.text
        assert "6+ caracteres" in register_response.text
    finally:
        get_settings.cache_clear()
