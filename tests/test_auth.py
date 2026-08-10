import time
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

import app.auth.passwords as auth_passwords
import app.auth.service as auth_service
import app.auth.ui_middleware as auth_ui_middleware
from app.auth.csrf import create_csrf_token, verify_csrf_token
from app.auth.passwords import (
    hash_password,
    normalize_email,
    validate_strong_password,
    verify_password,
)
from app.auth.session import (
    SESSION_COOKIE_NAME,
    create_persistent_session_token,
    revoke_persistent_session_token,
    verify_persistent_session_token,
)
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.auth.ui_routes import _auth_page
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


class _FakeScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def first(self) -> object | None:
        return self.value


class _FakeExecuteResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self.value)


class _FakeSessionStore:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.persisted: object | None = None
        self.committed = False

    def add(self, value: object) -> None:
        self.added.append(value)
        self.persisted = value

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, _statement: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self.persisted)


@pytest.fixture(scope="module")
def local_api_client() -> Iterator[TestClient]:
    with TestClient(create_app(include_ui=False)) as client:
        yield client


def test_auth_me_uses_local_user_in_local_environment(local_api_client: TestClient) -> None:
    response = local_api_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {"username": "local-user"}


def test_csrf_tokens_require_cookie_and_form_match() -> None:
    token = create_csrf_token()

    assert verify_csrf_token(token, token)
    assert not verify_csrf_token(token, create_csrf_token())
    assert not verify_csrf_token(None, token)


@pytest.mark.asyncio
async def test_persistent_session_token_can_be_revoked() -> None:
    user = User(email="user@example.com", display_name="User", password_hash="hash")
    session = _FakeSessionStore()

    token = await create_persistent_session_token(cast(AsyncSession, session), user)

    assert await verify_persistent_session_token(cast(AsyncSession, session), token) == user.email
    assert await revoke_persistent_session_token(cast(AsyncSession, session), token)
    assert await verify_persistent_session_token(cast(AsyncSession, session), token) is None


def test_health_live_does_not_require_authentication(local_api_client: TestClient) -> None:
    response = local_api_client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_operational_api_endpoint_does_not_require_authentication(
    local_api_client: TestClient,
) -> None:
    response = local_api_client.post(
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

    async def fake_verify_persistent_session(
        _session: object, _token: str
    ) -> str | None:
        return "jonata"

    monkeypatch.setattr(
        auth_ui_middleware,
        "verify_persistent_session_token",
        fake_verify_persistent_session,
    )
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

        client.cookies.set(SESSION_COOKIE_NAME, "sid-persistent-token")
        allowed = client.get("/settings", follow_redirects=False)
        assert allowed.status_code == 200
    finally:
        get_settings.cache_clear()


def test_auth_rate_limit_prunes_stale_attempt_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth import ui_routes as auth_ui_routes

    monkeypatch.setattr(
        auth_ui_routes,
        "_AUTH_ATTEMPTS",
        {
            "stale:user": [time.monotonic() - 300],
            "active:user": [time.monotonic()],
        },
    )

    auth_ui_routes._prune_stale_auth_attempts(time.monotonic() - 60)

    assert "stale:user" not in auth_ui_routes._AUTH_ATTEMPTS
    assert "active:user" in auth_ui_routes._AUTH_ATTEMPTS


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


def test_password_hash_verification_is_defensive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_passwords, "PBKDF2_ITERATIONS", 1)
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
    monkeypatch.setattr(auth_service, "hash_password", lambda password: f"hashed::{password}")
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
    assert user.password_hash == "hashed::Se1!ha"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_register_user_rejects_duplicate_email(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_user = User(
        email="user@example.com",
        display_name="User",
        password_hash="stored-hash",
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
        password_hash="stored-hash",
    )

    async def found_user(_session: AsyncSession, _email: str) -> User | None:
        return existing_user

    monkeypatch.setattr(auth_service, "get_user_by_email", found_user)
    monkeypatch.setattr(
        auth_service,
        "verify_password",
        lambda password, stored_hash: password == "Se1!ha" and stored_hash == "stored-hash",
    )
    fake_session = cast(AsyncSession, _FakeAuthSession())

    assert await auth_service.authenticate_user(fake_session, "USER@example.com", "Se1!ha")
    assert await auth_service.authenticate_user(fake_session, "USER@example.com", "errada") is None


def test_login_and_register_pages_use_email_fields() -> None:
    login_response = _auth_page("login", registration_available=True)
    register_response = _auth_page("register", registration_available=True)
    login_html = bytes(login_response.body).decode()
    register_html = bytes(register_response.body).decode()

    assert login_response.status_code == 200
    assert register_response.status_code == 200
    assert 'name="email" type="email"' in login_html
    assert 'name="email" type="email"' in register_html
    assert "6+ caracteres" in register_html
