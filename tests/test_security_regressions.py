from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.auth.ui_middleware as ui_middleware
import app.auth.ui_routes as ui_routes
import app.providers.media_utils as media_utils
import app.video_generation.service as video_generation_service
from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.auth.ui_routes import _secure_cookie_enabled
from app.auth.user_store import create_user, verify_user
from app.config.runtime_preferences import load_runtime_preferences, save_runtime_preferences
from app.config.settings import get_settings
from app.core.enums import ProjectStatus
from app.projects.models import Project
from app.storytelling.idea_lab import load_generated_ideas
from app.storytelling.service import GenerationOutputError, _required_list
from app.video_generation.schemas import GenerateVideoClipsRequest
from app.workflows.state_machine import advance_project_status


def test_ui_middleware_requires_authentication() -> None:
    app = FastAPI()
    app.add_middleware(UIBasicAuthMiddleware)

    @app.get("/")
    async def home() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/", auth=("admin", "admin")).json() == {"ok": True}

    client.cookies.set(SESSION_COOKIE_NAME, create_session_token("jonata"))
    assert client.get("/").json() == {"ok": True}


def test_ui_middleware_keeps_registration_private_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ui_middleware,
        "get_settings",
        lambda: SimpleNamespace(allow_user_registration=False),
    )
    middleware = UIBasicAuthMiddleware(FastAPI())

    assert middleware._is_ui_scope({"type": "http", "path": "/register"}) is True
    assert middleware._is_ui_scope({"type": "http", "path": "/auth/register"}) is True
    assert middleware._is_ui_scope({"type": "http", "path": "/login"}) is False


@pytest.mark.asyncio
async def test_registration_routes_are_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ui_routes,
        "get_settings",
        lambda: SimpleNamespace(
            app_name="Storytelling",
            app_env="local",
            allow_user_registration=False,
        ),
    )

    def _unexpected_create_user(*args: object, **kwargs: object) -> object:
        raise AssertionError("create_user should not be called when registration is disabled")

    monkeypatch.setattr(ui_routes, "create_user", _unexpected_create_user)

    page = await ui_routes.register_page()
    assert page.status_code == 403
    assert "Cadastro desativado" in bytes(page.body).decode("utf-8")

    response = await ui_routes.register(username="novo", password="senha-segura")
    assert response.status_code == 403


def test_ui_middleware_protects_docs_and_openapi() -> None:
    app = FastAPI()
    app.add_middleware(UIBasicAuthMiddleware)

    @app.get("/docs")
    async def docs() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/openapi.json")
    async def openapi() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/docs", follow_redirects=False).status_code == 303
    assert client.get("/openapi.json", follow_redirects=False).status_code == 303
    assert client.get("/docs", auth=("admin", "admin")).status_code == 200
    assert client.get("/openapi.json", auth=("admin", "admin")).status_code == 200


def test_ui_middleware_does_not_mask_endpoint_exceptions() -> None:
    app = FastAPI()
    app.add_middleware(UIBasicAuthMiddleware)

    @app.get("/")
    async def home() -> dict[str, bool]:
        raise RuntimeError("boom")

    client = TestClient(app)
    with pytest.raises(RuntimeError, match="boom"):
        client.get("/", auth=("admin", "admin"))


def test_ui_session_cookie_is_secure_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    assert not _secure_cookie_enabled()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "production-secret")
    monkeypatch.setenv("API_BASIC_USERNAME", "prod-admin")
    monkeypatch.setenv("API_BASIC_PASSWORD", "prod-password")
    get_settings.cache_clear()
    try:
        assert _secure_cookie_enabled()
    finally:
        get_settings.cache_clear()


def test_local_user_store_creates_and_verifies_user(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    create_user("Jonata", "senha-segura", users_path)

    assert verify_user("jonata", "senha-segura", users_path)
    assert not verify_user("jonata", "senha-errada", users_path)

    with pytest.raises(ValueError, match="ja existe"):
        create_user("jonata", "outra-senha", users_path)


def test_ui_session_cookie_accepts_browser_cookie_header() -> None:
    app = FastAPI()
    app.add_middleware(UIBasicAuthMiddleware)

    @app.get("/")
    async def home() -> dict[str, bool]:
        return {"ok": True}

    token = create_session_token("jonata jesus")
    client = TestClient(app)
    response = client.get("/", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_runtime_preferences_are_allowlisted_and_reject_control_characters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "preferences.json"
    save_runtime_preferences({"USER_THEME": "light"}, path)
    assert load_runtime_preferences(path) == {"user_theme": "light"}

    with pytest.raises(ValueError, match="not allowed"):
        save_runtime_preferences({"DATABASE_URL": "attacker"}, path)
    with pytest.raises(ValueError, match="control character"):
        save_runtime_preferences({"OPENROUTER_DEFAULT_MODEL": "mock\nAPP_DEBUG=true"}, path)


def test_runtime_json_corruption_falls_back_safely(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"
    preferences_path.write_text("{broken", encoding="utf-8")
    assert load_runtime_preferences(preferences_path) == {}

    users_path = tmp_path / "users.json"
    users_path.write_text("{broken", encoding="utf-8")
    assert not verify_user("jonata", "senha-segura", users_path)

    ideas_path = tmp_path / "ideas.json"
    ideas_path.write_text("{broken", encoding="utf-8")
    assert load_generated_ideas(ideas_path) == []


def test_local_storage_helpers_reject_files_outside_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    inside = storage_root / "avatar.png"
    inside.write_bytes(b"avatar")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    monkeypatch.setattr(
        media_utils,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )
    monkeypatch.setattr(
        video_generation_service,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )

    assert media_utils.local_uri_to_data_url(inside.as_posix()).startswith("data:")
    assert media_utils.local_uri_to_data_url(outside.as_posix()) == outside.as_posix()
    assert video_generation_service._local_storage_path(inside.as_posix()) == inside.resolve()
    assert video_generation_service._local_storage_path(outside.as_posix()) is None


def test_generation_payload_validation_rejects_missing_lists() -> None:
    with pytest.raises(GenerationOutputError, match="ideas"):
        _required_list({}, "ideas", "generate_story_ideas")


def test_video_schema_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        GenerateVideoClipsRequest.model_validate({"provider": "unknown"})


def test_project_status_advances_only_through_valid_transitions() -> None:
    project = Project(title="Test", status=ProjectStatus.IDEA_APPROVAL)
    advance_project_status(project, ProjectStatus.STORY_APPROVAL)
    assert project.status == ProjectStatus.STORY_APPROVAL

    with pytest.raises(ValueError, match="Cannot advance"):
        advance_project_status(project, ProjectStatus.IDEA_GENERATION)
