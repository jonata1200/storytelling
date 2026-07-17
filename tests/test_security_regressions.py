from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.auth.ui_middleware import UIBasicAuthMiddleware
from app.auth.user_store import create_user, verify_user
from app.config.runtime_preferences import load_runtime_preferences, save_runtime_preferences
from app.core.enums import ProjectStatus
from app.projects.models import Project
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


def test_local_user_store_creates_and_verifies_user(tmp_path: Path) -> None:
    users_path = tmp_path / "users.json"
    create_user("Jonata", "senha-segura", users_path)

    assert verify_user("jonata", "senha-segura", users_path)
    assert not verify_user("jonata", "senha-errada", users_path)

    with pytest.raises(ValueError, match="ja existe"):
        create_user("jonata", "outra-senha", users_path)


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


def test_video_schema_rejects_unimplemented_provider() -> None:
    with pytest.raises(ValidationError):
        GenerateVideoClipsRequest.model_validate({"provider": "openrouter"})


def test_project_status_advances_only_through_valid_transitions() -> None:
    project = Project(title="Test", status=ProjectStatus.IDEA_APPROVAL)
    advance_project_status(project, ProjectStatus.STORY_APPROVAL)
    assert project.status == ProjectStatus.STORY_APPROVAL

    with pytest.raises(ValueError, match="Cannot advance"):
        advance_project_status(project, ProjectStatus.IDEA_GENERATION)
