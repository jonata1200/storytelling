from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.providers.media_utils as media_utils
import app.ui.workspace.assets_area as assets_area
import app.video_generation.service as video_generation_service
from app.auth.user_store import create_user, verify_user
from app.config.runtime_preferences import load_runtime_preferences, save_runtime_preferences
from app.core.enums import ProjectStatus
from app.projects.models import Project
from app.storytelling.idea_lab import load_generated_ideas
from app.storytelling.service import (
    GenerationOutputError,
    _advance_project_status_when_reachable,
    _required_list,
)
from app.video_generation.schemas import GenerateVideoClipsRequest
from app.workflows.state_machine import advance_project_status


def test_app_routes_do_not_require_authentication() -> None:
    app = FastAPI()

    @app.get("/docs")
    async def docs() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/openapi.json")
    async def openapi() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/docs", follow_redirects=False).status_code == 200
    assert client.get("/openapi.json", follow_redirects=False).status_code == 200


def test_app_without_auth_does_not_mask_endpoint_exceptions() -> None:
    app = FastAPI()

    @app.get("/")
    async def home() -> dict[str, bool]:
        raise RuntimeError("boom")

    client = TestClient(app)
    with pytest.raises(RuntimeError, match="boom"):
        client.get("/")


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
    save_runtime_preferences({"AI_PROVIDER": "ollama_cloud"}, path)
    assert load_runtime_preferences(path)["ai_provider"] == "ollama_cloud"
    save_runtime_preferences(
        {
            "TEXT_PROVIDER_FALLBACKS": "",
            "OLLAMA_CLOUD_API_KEY": "ollama-secret",
            "OLLAMA_CLOUD_DEFAULT_MODEL": "deepseek-v4-flash:cloud",
            "GOOGLE_AI_API_KEY": "google-secret",
            "GOOGLE_AI_IMAGE_MODEL": "gemini-3.1-flash-lite-image",
            "GOOGLE_AI_VIDEO_MODEL": "veo-3.1-fast-generate-preview",
            "SPEECH_PROVIDER": "elevenlabs",
            "SPEECH_TIMEOUT_SECONDS": "120",
            "ELEVENLABS_API_KEY": "eleven-secret",
            "ELEVENLABS_VOICE_ID": "voice-1",
            "ELEVENLABS_SPEECH_MODEL": "eleven_multilingual_v2",
            "DUBBING_TARGET_LANG": "en",
        },
        path,
    )
    preferences = load_runtime_preferences(path)
    assert preferences["text_provider_fallbacks"] == ""
    assert preferences["ollama_cloud_api_key"] == "ollama-secret"
    assert preferences["ollama_cloud_default_model"] == "deepseek-v4-flash:cloud"
    assert preferences["google_ai_api_key"] == "google-secret"
    assert preferences["google_ai_image_model"] == "gemini-3.1-flash-lite-image"
    assert preferences["google_ai_video_model"] == "veo-3.1-fast-generate-preview"
    assert preferences["speech_provider"] == "elevenlabs"
    assert preferences["speech_timeout_seconds"] == "120"
    assert preferences["elevenlabs_api_key"] == "eleven-secret"
    assert preferences["elevenlabs_voice_id"] == "voice-1"
    assert preferences["elevenlabs_speech_model"] == "eleven_multilingual_v2"
    assert preferences["dubbing_target_lang"] == "en"
    with pytest.raises(ValueError, match="not allowed"):
        save_runtime_preferences({"DATABASE_URL": "attacker"}, path)
    with pytest.raises(ValueError, match="control character"):
        save_runtime_preferences({"OLLAMA_CLOUD_DEFAULT_MODEL": "mock\nAPP_DEBUG=true"}, path)


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
    webp_inside = storage_root / "portrait.webp"
    webp_inside.write_bytes(b"webp")
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
    assert media_utils.local_uri_to_data_url(webp_inside.as_posix()).startswith(
        "data:image/webp;base64,"
    )
    assert media_utils.local_uri_to_data_url(
        f"http://127.0.0.1:8000/storage/{inside.name}"
    ).startswith("data:image/png;base64,")
    assert media_utils.local_uri_to_data_url(f"/storage/{inside.name}").startswith(
        "data:image/png;base64,"
    )
    assert media_utils.local_uri_to_data_url(outside.as_posix()) == outside.as_posix()
    assert (
        media_utils.local_uri_to_data_url("http://example.com/storage/avatar.png")
        == "http://example.com/storage/avatar.png"
    )
    assert video_generation_service._local_storage_path(inside.as_posix()) == inside.resolve()
    assert video_generation_service._local_storage_path(outside.as_posix()) is None


def test_visual_library_tab_is_persisted_per_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage: dict[str, str] = {}
    monkeypatch.setattr(
        assets_area,
        "nicegui_app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
    )
    project_id = uuid4()

    assert assets_area._read_visual_library_active_tab(project_id) == "characters"
    assets_area._store_visual_library_active_tab(project_id, "locations")
    assert assets_area._read_visual_library_active_tab(project_id) == "locations"
    assets_area._store_visual_library_active_tab(project_id, "unexpected")
    assert assets_area._read_visual_library_active_tab(project_id) == "characters"


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


def test_script_regeneration_does_not_move_advanced_project_backwards() -> None:
    project = Project(title="Test", status=ProjectStatus.VISUAL_BIBLE_GENERATION)

    _advance_project_status_when_reachable(project, ProjectStatus.SCRIPT_APPROVAL)

    assert project.status == ProjectStatus.VISUAL_BIBLE_GENERATION

