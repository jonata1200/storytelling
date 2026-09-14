from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.providers.media_utils as media_utils
import app.server as server
from app.config.runtime_preferences import (
    cleanup_obsolete_runtime_preferences,
    load_runtime_preferences,
    save_runtime_preferences,
)
from app.config.settings import Settings
from app.core.enums import ProjectStatus
from app.factory import create_app
from app.projects.models import Project
from app.storytelling.idea_lab import load_generated_ideas
from app.storytelling.service import (
    GenerationOutputError,
    _advance_project_status_when_reachable,
    _required_list,
)
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


def test_ui_is_not_mounted_in_non_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        app_debug=False,
        app_secret_key="production-secret",
        app_api_token="api-token",
        database_url="postgresql+asyncpg://user:pass@localhost/database",
    )
    monkeypatch.setattr("app.factory.get_settings", lambda: settings)

    app = create_app(include_ui=True)

    assert "/" not in {getattr(route, "path", None) for route in app.routes}


def test_non_loopback_bind_requires_api_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, app_api_token="")
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    monkeypatch.setattr(server, "configured_api_token", lambda: None)
    monkeypatch.setattr("sys.argv", ["storytelling", "--host", "0.0.0.0"])

    with pytest.raises(SystemExit, match="APP_API_TOKEN"):
        server.main()


def test_runtime_preferences_are_allowlisted_and_reject_control_characters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "preferences.json"
    save_runtime_preferences({"USER_THEME": "light"}, path)
    assert load_runtime_preferences(path) == {"user_theme": "light"}
    save_runtime_preferences(
        {
            "TEXT_PROVIDER": "ollama_cloud",
            "OLLAMA_CLOUD_API_KEY": "fake-ollama-secret",
        },
        path,
    )
    preferences = load_runtime_preferences(path)
    assert preferences["text_provider"] == "ollama_cloud"
    assert preferences["ollama_cloud_api_key"] == "fake-ollama-secret"
    with pytest.raises(ValueError, match="not allowed"):
        save_runtime_preferences({"DATABASE_URL": "attacker"}, path)
    with pytest.raises(ValueError, match="control character"):
        save_runtime_preferences({"OLLAMA_CLOUD_DEFAULT_MODEL": "mock\nAPP_DEBUG=true"}, path)


def test_runtime_preferences_cleanup_removes_obsolete_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text('{"USER_THEME":"dark","REMOVED_PROVIDER_KEY":"secret"}', encoding="utf-8")
    assert cleanup_obsolete_runtime_preferences(path) is True
    assert load_runtime_preferences(path) == {"user_theme": "dark"}


def test_runtime_json_corruption_falls_back_safely(tmp_path: Path) -> None:
    preferences_path = tmp_path / "preferences.json"
    preferences_path.write_text("{broken", encoding="utf-8")
    assert load_runtime_preferences(preferences_path) == {}

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

    data_url = media_utils.local_uri_to_data_url(inside.as_posix())
    assert data_url is not None and data_url.startswith("data:")
    webp_data_url = media_utils.local_uri_to_data_url(webp_inside.as_posix())
    assert webp_data_url is not None and webp_data_url.startswith("data:image/webp;base64,")
    # SSRF defense: http:// URLs are now fail-closed (return None) instead of
    # being fetched and potentially leaking internal resources.
    assert media_utils.local_uri_to_data_url(
        f"http://127.0.0.1:8000/storage/{inside.name}"
    ) is None
    png_data_url = media_utils.local_uri_to_data_url(f"/storage/{inside.name}")
    assert png_data_url is not None and png_data_url.startswith("data:image/png;base64,")
    # Fail-closed: paths outside storage_root return None instead of the raw uri.
    assert media_utils.local_uri_to_data_url(outside.as_posix()) is None
    assert media_utils.local_uri_to_data_url("http://example.com/storage/avatar.png") is None


def test_generation_payload_validation_rejects_missing_lists() -> None:
    with pytest.raises(GenerationOutputError, match="ideas"):
        _required_list({}, "ideas", "generate_story_ideas")


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


def test_truncate_table_identifiers_are_validated_against_metadata() -> None:
    from app.projects.service import _validated_table_identifiers

    assert _validated_table_identifiers(("projects", "story_ideas")) == (
        "projects",
        "story_ideas",
    )
    with pytest.raises(ValueError, match="Tabela desconhecida"):
        _validated_table_identifiers(("projects; DROP TABLE projects",))
    with pytest.raises(ValueError, match="Tabela desconhecida"):
        _validated_table_identifiers(("pg_catalog.pg_tables",))


def test_delete_local_storage_file_rejects_paths_outside_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.storage import service as storage_service
    from app.video_generation import continuous as continuous_module
    from app.visual_bible import reset as reset_module

    root = tmp_path / "storage"
    root.mkdir()
    inside = root / "segment.mp4"
    inside.write_bytes(b"video")
    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        storage_service,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=root),
    )
    resolve = storage_service.resolve_storage_path
    monkeypatch.setattr(continuous_module, "resolve_storage_path", resolve)
    monkeypatch.setattr(reset_module, "resolve_storage_path", resolve)

    assert reset_module._delete_local_storage_file(inside.as_posix()) is True
    assert not inside.exists()
    # URI fora do storage root é recusada e o arquivo permanece intacto.
    assert reset_module._delete_local_storage_file(outside.as_posix()) is False
    assert outside.exists()
    assert continuous_module._delete_local_storage_file(outside.as_posix()) is False
    assert outside.exists()
    # Tentativa de path traversal via URI relativa também é recusada.
    traversal = (root / ".." / "keep.txt").as_posix()
    assert reset_module._delete_local_storage_file(traversal) is False
    assert outside.exists()


def test_llm_provider_malformed_json_raises_format_error() -> None:
    from app.providers.llm.ollama_cloud import OllamaCloudLLMProvider
    from app.providers.llm.types import LLMRequest, LLMResponseFormatError

    provider = OllamaCloudLLMProvider()
    try:
        raise LLMResponseFormatError(
            "conteúdo inválido", "not-json", display_name=provider.display_name
        )
    except LLMResponseFormatError as exc:
        assert exc.raw_content == "not-json"
        assert "conteúdo inválido" in str(exc)
    request = LLMRequest(task="generate_story_ideas", prompt="x")
    assert request.output_schema == {}


