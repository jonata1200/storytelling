import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.storytelling.service import (
    _bounded_required_str,
    _shot_narration_text,
)
from app.ui import page_runtime, pages
from app.ui.pages import _asset_url, _compact_project_title
from app.ui.project import actions as project_actions
from app.ui.workspace import storyboard_video_area
from app.ui.workspace.assets_area import _character_reference_sheet_asset


def test_settings_tab_key_keeps_data_tab_after_destructive_actions() -> None:
    assert pages._settings_tab_key("data") == "data"
    assert pages._settings_tab_key("Dados") == "data"
    assert pages._settings_tab_key("ia") == "ai"
    assert pages._settings_tab_key(None) == "profile"


def test_register_ui_pages_resolves_page_facade_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[str] = []

    def fake_register_home_pages(**kwargs: Any) -> None:
        registered.append("home")
        assert callable(kwargs["body_style"])
        assert callable(kwargs["project_cards"])
        assert callable(kwargs["home_sidebar"])

    def fake_register_settings_page(**kwargs: Any) -> None:
        registered.append("settings")
        assert callable(kwargs["save_avatar_file"])
        assert callable(kwargs["theme_toggle"])

    def fake_register_project_workspace_pages(**kwargs: Any) -> None:
        registered.append("workspace")
        assert callable(kwargs["project_summary"])
        assert callable(kwargs["workspace_header"])

    monkeypatch.setattr(page_runtime, "register_home_pages", fake_register_home_pages)
    monkeypatch.setattr(page_runtime, "register_settings_page", fake_register_settings_page)
    monkeypatch.setattr(
        page_runtime,
        "register_project_workspace_pages",
        fake_register_project_workspace_pages,
    )

    pages.register_ui_pages()

    assert registered == ["home", "settings", "workspace"]


@pytest.mark.asyncio
async def test_delete_lab_idea_does_not_remove_local_when_database_delete_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted_local: list[str] = []
    notifications: list[tuple[str, str | None]] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def fake_blocked_delete_status(session: Any, idea_id: str) -> str:
        return "blocked"

    monkeypatch.setattr(project_actions, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        project_actions,
        "delete_saved_idea",
        lambda idea_id: deleted_local.append(idea_id),
    )
    monkeypatch.setattr(
        project_actions,
        "hard_delete_story_idea_by_payload_id_status",
        fake_blocked_delete_status,
    )
    monkeypatch.setattr(
        project_actions.ui,
        "notify",
        lambda message, **kwargs: notifications.append((message, kwargs.get("color"))),
    )

    deleted = await project_actions._delete_lab_idea_from_ui("idea-linked", "saved")

    assert deleted is False
    assert deleted_local == []
    assert notifications[-1][1] == "warning"


def test_chat_prompt_title_is_compact() -> None:
    prompt = (
        "Quero criar uma historia sobre uma astronauta que recebe uma mensagem dela mesma "
        "vinda de dez anos no futuro e precisa escolher entre salvar a tripulacao ou voltar."
    )

    title = _compact_project_title(prompt)

    assert title == "Uma astronauta que recebe uma mensagem dela mesma vinda"
    assert len(title) < len(prompt)


def test_chat_prompt_title_uses_first_sentence() -> None:
    prompt = "A chave perdida. Depois disso, a historia revela um segredo familiar."

    assert _compact_project_title(prompt) == "A chave perdida"


def test_clean_idea_title_removes_numbered_prefix() -> None:
    assert pages._clean_idea_title("Ideia 06: Uma Comunidade") == "Uma Comunidade"
    assert pages._clean_idea_title("IDEIA 02 - O Trem") == "O Trem"


def test_ai_action_without_timestamp_is_stale() -> None:
    assert pages._ai_action_is_stale({"status": "running"}) is True


def test_recent_ai_action_is_not_stale() -> None:
    updated_at = datetime.now(UTC).isoformat()

    assert pages._ai_action_is_stale({"status": "running", "updated_at": updated_at}) is False


def test_project_ai_action_reads_production_metadata() -> None:
    summary = {
        "production_settings": SimpleNamespace(
            metadata_json={
                "ai_action": {
                    "action": "create_initial_script",
                    "status": "running",
                    "message": "Criando roteiro",
                }
            }
        )
    }

    action = pages._project_ai_action(summary)

    assert action["status"] == "running"
    assert action["message"] == "Criando roteiro"


def test_friendly_ai_error_explains_timeout() -> None:
    message = pages._friendly_ai_error(RuntimeError("Provider demorou mais de 60s"))

    assert "demorou demais" in message
    assert "modelo" in message


def test_expected_ai_timeout_logs_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_id = uuid4()

    with caplog.at_level(logging.WARNING):
        pages._log_ai_background_failure(
            "Nao foi possivel gerar roteiro inicial do projeto",
            project_id,
            RuntimeError("Provider demorou mais de 150s"),
        )

    assert caplog.records
    assert caplog.records[-1].levelno == logging.WARNING
    assert caplog.records[-1].exc_info is None
    assert "demorou demais" in caplog.records[-1].getMessage()


def test_ai_failure_notification_is_shown_once(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    storage: dict[str, Any] = {}
    popups: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        pages,
        "nicegui_app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
    )
    monkeypatch.setattr(
        pages.ui,
        "notify",
        lambda message, **kwargs: None,
    )
    monkeypatch.setattr(
        pages,
        "_show_ai_error_popup",
        lambda message, **kwargs: popups.append((str(message), kwargs.get("details"))),
    )
    summary = {
        "production_settings": SimpleNamespace(
            metadata_json={
                "ai_action": {
                    "action": "create_initial_script",
                    "status": "failed",
                    "message": "A IA nao conseguiu criar o roteiro inicial.",
                    "error": "O modelo de IA demorou demais para responder.",
                    "updated_at": "2026-07-22T10:00:00+00:00",
                }
            }
        )
    }

    pages._notify_ai_action_failure_once(project_id, summary)
    pages._notify_ai_action_failure_once(project_id, summary)

    assert popups == [
        (
            "O modelo de IA demorou demais para responder.",
            "O modelo de IA demorou demais para responder.",
        )
    ]


def test_ai_action_sync_adds_only_one_chat_message_per_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    storage: dict[str, Any] = {}
    monkeypatch.setattr(
        pages,
        "nicegui_app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
    )
    summary = {
        "production_settings": SimpleNamespace(
            metadata_json={
                "ai_action": {
                    "events": [
                        {
                            "id": "create_initial_script:1",
                            "action": "create_initial_script",
                            "status": "queued",
                            "message": "A IA vai iniciar a criacao do roteiro inicial.",
                        },
                        {
                            "id": "create_initial_script:2",
                            "action": "create_initial_script",
                            "status": "running",
                            "message": "A IA esta criando o roteiro inicial com base na ideia.",
                        },
                    ]
                }
            }
        )
    }

    pages._sync_ai_action_events_to_chat(project_id, summary)
    pages._sync_ai_action_events_to_chat(project_id, summary)

    messages = storage["project_assistant_messages"][str(project_id)]
    assert messages == [
        {
            "role": "assistant",
            "content": "A IA vai iniciar a criacao do roteiro inicial.",
            "event_id": "create_initial_script:1",
            "event_action": "create_initial_script",
        }
    ]


def test_safe_client_navigation_uses_captured_client() -> None:
    class FakeClient:
        is_deleted = False

        def __init__(self) -> None:
            self.opened: str | None = None

        def open(self, target: str) -> None:
            self.opened = target

        def run_javascript(self, code: str) -> None:
            raise AssertionError("reload should not be used")

    client = FakeClient()

    pages._safe_client_navigation(client, "/projects/123/storyboard")

    assert client.opened == "/projects/123/storyboard"


def test_safe_client_navigation_ignores_deleted_slot_runtime_error() -> None:
    class DeletedSlotClient:
        is_deleted = False

        def open(self, target: str) -> None:
            raise RuntimeError("The parent element this slot belongs to has been deleted.")

    pages._safe_client_navigation(DeletedSlotClient(), "/projects/123/storyboard")


def test_safe_refresh_ignores_deleted_slot_runtime_error() -> None:
    class DeletedRefreshable:
        def refresh(self) -> None:
            raise RuntimeError("The parent element this slot belongs to has been deleted.")

    pages._safe_refresh(DeletedRefreshable())


def test_retry_initial_script_opens_loading_dialog_and_watches_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    created_tasks: list[dict[str, Any]] = []
    timers: list[dict[str, Any]] = []
    notifications: list[str] = []

    class FakeDialog:
        opened = False

        def open(self) -> None:
            self.opened = True

    def fake_create(task: object, *, name: str) -> None:
        created_tasks.append({"task": task, "name": name})

    def fake_timer(interval: float, callback: object) -> None:
        timers.append({"interval": interval, "callback": callback})

    dialog = FakeDialog()
    monkeypatch.setattr(pages, "_resume_initial_script_in_background", lambda item_id: "task")
    monkeypatch.setattr(pages.background_tasks, "create", fake_create)
    monkeypatch.setattr(pages.ui, "timer", fake_timer)
    monkeypatch.setattr(
        pages.ui,
        "notify",
        lambda message, **kwargs: notifications.append(str(message)),
    )

    pages._retry_initial_script_from_ui(project_id, dialog)

    assert dialog.opened is True
    assert created_tasks == [{"task": "task", "name": f"retry initial script {project_id}"}]
    assert timers and timers[0]["interval"] == 5.0
    assert notifications == ["Retomando a criação do roteiro."]


def test_legacy_assistant_greeting_is_removed_from_chat_history() -> None:
    assert (
        pages._is_legacy_assistant_greeting(
            "assistant",
            "Estou acompanhando esta etapa. Posso revisar, propor variações.",
        )
        is True
    )
    assert pages._is_legacy_assistant_greeting("assistant", "Resposta real do agente.") is False


def test_asset_url_maps_local_storage_file_to_public_storage_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    image_path = storage_root / "mock_images" / "project 1" / "front view.svg"
    image_path.parent.mkdir(parents=True)
    image_path.write_text("<svg />", encoding="utf-8")
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )

    assert _asset_url(image_path.as_posix()) == (
        "/storage/mock_images/project%201/front%20view.svg"
    )


def test_asset_url_maps_storage_prefixed_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )

    assert _asset_url("storage/openrouter_images/project-1/front view.png") == (
        "/storage/openrouter_images/project-1/front%20view.png"
    )


def test_asset_url_rejects_files_outside_configured_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    outside_file = tmp_path / "outside.svg"
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=storage_root),
    )

    assert _asset_url(outside_file.as_posix()) == ""


def test_visual_references_are_sorted_by_expected_view_order() -> None:
    target_id = uuid4()
    project_id = uuid4()
    now = datetime.now()
    back = SimpleNamespace(
        project_id=project_id,
        target_kind="character",
        target_id=target_id,
        view_type="back_view",
        created_at=now,
    )
    reference_sheet = SimpleNamespace(
        project_id=project_id,
        target_kind="character",
        target_id=target_id,
        view_type="character_reference_sheet",
        created_at=now + timedelta(seconds=1),
    )

    references = pages._visual_references_for(
        {"visual_refs": [back, reference_sheet]},
        "character",
        target_id,
    )

    assert references == [reference_sheet, back]


def test_visual_references_prefer_newest_image_for_same_view() -> None:
    target_id = uuid4()
    project_id = uuid4()
    now = datetime.now()
    older = SimpleNamespace(
        project_id=project_id,
        target_kind="prop",
        target_id=target_id,
        view_type="front",
        created_at=now,
    )
    newer = SimpleNamespace(
        project_id=project_id,
        target_kind="prop",
        target_id=target_id,
        view_type="front",
        created_at=now + timedelta(minutes=1),
    )

    references = pages._visual_references_for(
        {"visual_refs": [older, newer]},
        "prop",
        target_id,
    )

    assert references == [newer, older]


def test_character_reference_sheet_asset_is_available_only_for_characters() -> None:
    front_reference = (
        SimpleNamespace(view_type="front_portrait"),
        object(),
        "/storage/front.png",
    )
    reference_sheet = (
        SimpleNamespace(view_type="character_reference_sheet"),
        object(),
        "/storage/sheet.png",
    )
    reference_assets: list[Any] = [front_reference, reference_sheet]

    assert _character_reference_sheet_asset("character", reference_assets) == reference_sheet
    assert _character_reference_sheet_asset("location", reference_assets) is None
    assert _character_reference_sheet_asset("prop", reference_assets) is None


def test_storyboard_frame_image_url_uses_frame_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_id = uuid4()
    frame = SimpleNamespace(asset_id=asset_id)
    asset = SimpleNamespace(
        id=asset_id,
        storage_uri="storage/storyboards/frame.bin",
        content_type="image/webp",
    )
    monkeypatch.setattr(
        storyboard_video_area,
        "asset_url",
        lambda storage_uri: f"/resolved/{storage_uri}",
    )
    monkeypatch.setattr(storyboard_video_area, "_local_asset_file_exists", lambda _uri: True)

    image_url = storyboard_video_area._storyboard_frame_image_url(
        {"assets": [asset]},
        frame,
    )

    assert image_url == f"/api/v1/assets/{asset_id}/content"


def test_storyboard_frame_image_url_ignores_missing_local_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_id = uuid4()
    frame = SimpleNamespace(asset_id=asset_id)
    asset = SimpleNamespace(id=asset_id, storage_uri="storage/storyboards/missing.png")
    monkeypatch.setattr(storyboard_video_area, "_local_asset_file_exists", lambda _uri: False)

    image_url = storyboard_video_area._storyboard_frame_image_url(
        {"assets": [asset]},
        frame,
    )

    assert image_url == ""


def test_visual_library_cards_ready_when_any_card_type_exists() -> None:
    assert pages._visual_library_cards_ready(
        {"characters": [object()], "locations": [object()], "props": [object()]}
    )
    assert pages._visual_library_cards_ready(
        {"characters": [object()], "locations": [], "props": [object()]}
    )
    assert pages._visual_library_cards_ready(
        {"characters": [], "locations": [object()], "props": []}
    )
    assert not pages._visual_library_cards_ready({"characters": [], "locations": [], "props": []})


def test_visual_batch_requests_include_all_missing_views() -> None:
    character_id = uuid4()
    location_id = uuid4()
    prop_id = uuid4()
    summary = {
        "characters": [SimpleNamespace(id=character_id)],
        "locations": [SimpleNamespace(id=location_id)],
        "props": [SimpleNamespace(id=prop_id)],
        "visual_refs": [
            SimpleNamespace(
                target_kind="character",
                target_id=character_id,
                view_type="front_portrait",
            )
        ],
    }

    requests = pages._visual_batch_requests(summary)

    assert requests == [
        (
            "character",
            character_id,
            ["character_reference_sheet"],
        ),
        ("location", location_id, ["establishing"]),
        ("prop", prop_id, ["front"]),
    ]


def test_visual_card_detail_formats_character_profile_without_raw_dict() -> None:
    detail = pages._visual_card_detail(
        "character",
        {
            "arc": "",
            "eyes": "olhos expressivos",
            "hair": "cabelo grisalho preso",
            "base_outfit": "xale de retalhos",
        },
    )

    assert detail == "olhos expressivos, cabelo grisalho preso, xale de retalhos"
    assert "{" not in detail
    assert "'arc'" not in detail


def test_visual_card_detail_formats_location_profile() -> None:
    detail = pages._visual_card_detail(
        "location",
        {
            "lighting": "luz natural suave",
            "materials": ["madeira", "tecidos simples"],
            "layout": "sala pequena com janela lateral",
        },
    )

    assert detail == "luz natural suave, madeira, tecidos simples, sala pequena com janela lateral"


def test_visual_card_detail_prefers_explicit_description() -> None:
    detail = pages._visual_card_detail(
        "prop",
        {
            "description": "Objeto afetivo de payoff narrativo.",
            "material": "papel",
        },
    )

    assert detail == "Objeto afetivo de payoff narrativo."


def test_shot_narration_falls_back_to_action_when_empty() -> None:
    payload = {
        "narration_text": "",
        "dialogue_text": "",
        "action": "Clara abre a carta diante da janela.",
    }

    assert _shot_narration_text(payload, "shot") == "Clara abre a carta diante da janela."


def test_bounded_required_str_preserves_database_limits() -> None:
    payload = {"camera_movement": "Camera em travelling lateral com zoom suave e muito detalhe"}

    assert _bounded_required_str(payload, "camera_movement", "shot", 24) == (
        "Camera em travelling..."
    )


def test_scenes_are_ordered_by_scene_number_for_display() -> None:
    scenes = [
        SimpleNamespace(scene_number=3),
        SimpleNamespace(scene_number=1),
        SimpleNamespace(scene_number=2),
    ]

    ordered = pages._ordered_scenes(scenes)

    assert [scene.scene_number for scene in ordered] == [1, 2, 3]


def test_characters_section_unlocks_when_script_exists_without_shots() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "bibles": 1,
        "scripts": 1,
        "scenes": 0,
        "shots": 0,
        "characters": 0,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("assets", counts)

    assert pages._step_ready("script", counts) is True
    assert allowed is True
    assert reason == ""


def test_script_section_is_entry_point() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "scripts": 0,
        "scenes": 0,
        "shots": 0,
        "characters": 0,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("script", counts)

    assert allowed is True
    assert reason == ""
    assert pages._first_available_workspace_section(counts) == "script"


def test_unknown_workspace_section_is_rejected() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "scripts": 1,
        "scenes": 1,
        "shots": 1,
        "characters": 3,
        "frames": 6,
        "animatics": 1,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("bible", counts)

    assert allowed is False
    assert reason == "Etapa desconhecida."
    assert pages._first_available_workspace_section(counts) == "script"


def test_storyboard_section_waits_for_all_visual_references() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "scripts": 1,
        "scenes": 2,
        "shots": 8,
        "characters": 2,
        "locations": 1,
        "props": 1,
        "visual_refs": 5,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("storyboard", counts)

    assert pages._step_ready("visual", counts) is False
    assert allowed is False
    assert "Gere todas as imagens" in reason


def test_storyboard_section_unlocks_after_visual_references_are_complete() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "scripts": 1,
        "scenes": 2,
        "shots": 8,
        "characters": 2,
        "locations": 1,
        "props": 1,
        "visual_refs": 6,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("storyboard", counts)

    assert pages._step_ready("visual", counts) is True
    assert allowed is True
    assert reason == ""


def test_production_steps_do_not_include_story_bible() -> None:
    step_keys = [step.key for step in pages.PRODUCTION_STEPS]

    assert "script" in step_keys
    assert "bible" not in step_keys


def test_workspace_tabs_start_with_script() -> None:
    tab_keys = [key for _, key in pages.WORKSPACE_TABS]

    assert tab_keys[:2] == ["script", "assets"]
