import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.storytelling.service import (
    _bounded_required_str,
    _shot_narration_text,
)
from app.ui import page_runtime, pages
from app.ui.pages import _compact_project_title
from app.ui.project import actions as project_actions
from app.ui.routes import home_pages
from app.ui.shared import assistant_state
from app.ui.shared.page_config import LoadingStatus, action_loading_copy
from app.ui.workspace import script_area


def test_settings_tab_key_keeps_data_tab_after_destructive_actions() -> None:
    assert pages._settings_tab_key("data") == "data"
    assert pages._settings_tab_key("Dados") == "data"
    assert pages._settings_tab_key("ia") == "ai"
    assert pages._settings_tab_key(None) == "ai"

def test_assistant_loading_copy_lists_created_and_pending_work() -> None:
    title, status = action_loading_copy(
        "approve_storyboard_prompt",
        {
            "scripts": 1,
            "scenes": 2,
            "shots": 5,
            "characters": 1,
            "locations": 1,
            "visual_refs": 3,
            "frames": 2,
            "animatics": 0,
        },
    )

    assert title == "Aprovando prompts de storyboard"
    assert isinstance(status, LoadingStatus)
    assert status.completed == 2
    assert status.total == 6
    assert status.unit_label == "item"
    created = [item.label for item in status.created]
    missing = [item.label for item in status.missing]
    assert "1 roteiro" in created
    assert "2 quadros de storyboard" in created
    assert "3 quadros de storyboard" in missing
    assert "animatic" in missing

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

    pages.register_ui_pages(pages)

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

    assert title == "Uma Astronauta que Recebe uma Mensagem Dela Mesma Vinda"
    assert len(title) < len(prompt)

def test_chat_prompt_title_uses_first_sentence() -> None:
    prompt = "A chave perdida. Depois disso, a historia revela um segredo familiar."

    assert _compact_project_title(prompt) == "A Chave Perdida"

def test_dashboard_prompt_enter_key_submits_without_breaking_shift_enter() -> None:
    handler = home_pages.DASHBOARD_PROMPT_KEYDOWN_JS

    assert "event.key === 'Enter'" in handler
    assert "!event.shiftKey" in handler
    assert "event.preventDefault()" in handler
    assert "emit()" in handler

def test_idea_generation_progress_detail_keeps_user_informed() -> None:
    waiting = home_pages._idea_generation_progress_detail(0, 3, elapsed_seconds=15)
    progressed = home_pages._idea_generation_progress_detail(
        1,
        3,
        latest_title="A Porta Azul",
    )

    assert "ainda esta respondendo" in waiting
    assert "Criado: nada ainda." in waiting
    assert "Falta criar: 3 ideia(s)." in waiting
    assert "Criado: 1 ideia(s)." in progressed
    assert "Falta criar: 2 ideia(s)." in progressed
    assert "A Porta Azul" in progressed

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

def test_script_editor_state_starts_with_current_script_values() -> None:
    state = script_area.script_editor_state(" Roteiro atual ", "Cena 01\nINT. CASA - DIA")

    assert state == {
        "title": " Roteiro atual ",
        "content": "Cena 01\nINT. CASA - DIA",
        "saving": "false",
    }

def test_notify_client_uses_captured_client_outbox() -> None:
    messages: list[tuple[str, dict[str, str], str]] = []
    client = SimpleNamespace(
        id="client-1",
        is_deleted=False,
        outbox=SimpleNamespace(
            enqueue_message=lambda event, payload, client_id: messages.append(
                (event, payload, client_id)
            )
        ),
    )

    script_area._notify_client(client, "Salvando roteiro...", "info")

    assert messages == [
        (
            "notify",
            {"message": "Salvando roteiro...", "color": "info"},
            "client-1",
        )
    ]

@pytest.mark.asyncio
async def test_manual_script_save_refreshes_scene_plan_without_visual_bible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    artifact_id = uuid4()
    calls: list[str] = []
    notifications: list[tuple[str, str | None]] = []

    script = SimpleNamespace(
        id=script_id,
        project_id=project_id,
        artifact_id=artifact_id,
        title="Roteiro antigo",
        content="Conteúdo antigo",
        language="pt-BR",
        target_duration_seconds=60,
        word_count=2,
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        name="Roteiro antigo",
        current_version=1,
    )

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, model: object, item_id: object) -> object | None:
            if model is script_area.Script and item_id == script_id:
                return script
            if model is script_area.Artifact and item_id == artifact_id:
                return artifact
            return None

        def add(self, item: object) -> None:
            calls.append(type(item).__name__)

        async def commit(self) -> None:
            calls.append("commit")

    async def fake_create_artifact_version(
        session: object,
        requested_artifact: object,
        payload: dict[str, Any],
        change_note: str | None = None,
        mark_downstream_stale: bool = True,
    ) -> object:
        calls.append("version")
        artifact.current_version += 1
        assert payload["title"] == "Roteiro novo"
        assert change_note == "Script edited manually in UI"
        assert mark_downstream_stale is False
        return object()

    async def fake_refresh_derivatives(
        requested_project_id: object,
        requested_script_id: object,
    ) -> None:
        calls.append("refresh_derivatives")
        assert requested_project_id == project_id
        assert requested_script_id == script_id

    monkeypatch.setattr(script_area, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(script_area, "create_artifact_version", fake_create_artifact_version)
    monkeypatch.setattr(
        script_area,
        "_refresh_script_derivatives_from_ui",
        fake_refresh_derivatives,
    )
    monkeypatch.setattr(
        script_area.ui,
        "notify",
        lambda message, color=None, **_kwargs: notifications.append((message, color)),
    )
    monkeypatch.setattr(script_area.ui.navigate, "reload", lambda: calls.append("reload"))

    await script_area.save_script_from_ui(
        project_id,
        script_id,
        " Roteiro novo ",
        "Cena nova com conflito visual.",
    )

    assert script.title == "Roteiro novo"
    assert script.content == "Cena nova com conflito visual."
    assert calls == ["version", "ScriptVersion", "commit", "refresh_derivatives", "reload"]
    assert notifications == [("Roteiro salvo.", "positive")]

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
            "Não foi possível gerar roteiro inicial do projeto",
            project_id,
            RuntimeError("Provider demorou mais de 150s"),
        )

    assert caplog.records
    assert caplog.records[-1].levelno == logging.WARNING
    assert caplog.records[-1].exc_info is None
    assert "demorou demais" in caplog.records[-1].getMessage()

def test_ai_failure_notification_does_not_popup_on_page_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                    "message": "A IA não conseguiu criar o roteiro inicial.",
                    "error": "O modelo de IA demorou demais para responder.",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            }
        )
    }

    pages._notify_ai_action_failure_once(project_id, summary)
    pages._notify_ai_action_failure_once(project_id, summary)

    assert popups == []

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
                            "message": "A IA está criando o roteiro inicial com base na ideia.",
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
            "content": "A IA está criando o roteiro inicial com base na ideia.",
            "event_id": "create_initial_script:2",
            "event_action": "create_initial_script",
        }
    ]

def test_ai_action_sync_skips_initial_script_events_after_project_progress(
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
        "counts": {"scripts": 1, "frames": 2},
        "production_settings": SimpleNamespace(
            metadata_json={
                "ai_action": {
                    "events": [
                        {
                            "id": "create_initial_script:1",
                            "action": "create_initial_script",
                            "status": "queued",
                            "message": "A IA vai iniciar a criacao do roteiro inicial.",
                        }
                    ]
                }
            }
        ),
    }

    pages._sync_ai_action_events_to_chat(project_id, summary)

    assert storage.get("project_assistant_messages") in (None, {})

def test_ai_action_completion_sound_is_played_once(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    storage: dict[str, Any] = {}
    sounds: list[str] = []
    monkeypatch.setattr(
        pages,
        "nicegui_app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
    )
    monkeypatch.setattr(
        page_runtime,
        "play_completion_sound",
        lambda: sounds.append("played"),
    )
    summary = {
        "production_settings": SimpleNamespace(
            metadata_json={
                "ai_action": {
                    "action": "create_initial_script",
                    "status": "completed",
                    "message": "Roteiro inicial criado.",
                    "updated_at": "2026-08-09T12:00:00+00:00",
                }
            }
        )
    }

    pages._sync_ai_action_events_to_chat(project_id, summary)
    pages._sync_ai_action_events_to_chat(project_id, summary)

    assert sounds == ["played"]

def test_assistant_draft_persists_by_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    storage: dict[str, Any] = {}
    monkeypatch.setattr(
        assistant_state,
        "nicegui_app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
    )

    draft = assistant_state.load_assistant_draft(project_id)
    draft["message"] = "Melhore a emocao da cena final"
    assistant_state.save_assistant_draft(project_id, draft["message"])

    assert assistant_state.load_assistant_draft(project_id)["message"] == (
        "Melhore a emocao da cena final"
    )

    assistant_state.clear_assistant_draft(project_id)

    assert assistant_state.load_assistant_draft(project_id)["message"] == ""

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

async def test_retry_initial_script_opens_loading_dialog_and_watches_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    status_updates: list[dict[str, Any]] = []
    background_calls: list[UUID] = []
    created_tasks: list[Any] = []
    timers: list[dict[str, Any]] = []
    notifications: list[str] = []

    class FakeDialog:
        opened = False

        def open(self) -> None:
            self.opened = True

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_set_project_ai_action_status(
        session: object,
        requested_project_id: Any,
        **kwargs: Any,
    ) -> None:
        status_updates.append(
            {
                "session": session,
                "project_id": requested_project_id,
                **kwargs,
            }
        )

    async def fake_generate_initial_script_in_background(requested_project_id: UUID) -> None:
        background_calls.append(requested_project_id)

    def fake_timer(interval: float, callback: object, once: bool = False) -> None:
        timers.append({"interval": interval, "callback": callback, "once": once})

    def fake_schedule_initial_script_generation(requested_project_id: UUID) -> object:
        async def _run() -> None:
            background_calls.append(requested_project_id)

        task = _run()
        created_tasks.append(task)
        return task

    dialog = FakeDialog()
    monkeypatch.setattr(pages, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(
        pages,
        "_set_project_ai_action_status",
        fake_set_project_ai_action_status,
    )
    monkeypatch.setattr(
        pages,
        "_generate_initial_script_in_background",
        fake_generate_initial_script_in_background,
    )
    monkeypatch.setattr(
        pages,
        "schedule_initial_script_generation",
        fake_schedule_initial_script_generation,
    )
    monkeypatch.setattr(pages.ui, "timer", fake_timer)
    monkeypatch.setattr(
        pages.ui,
        "notify",
        lambda message, **kwargs: notifications.append(str(message)),
    )

    await pages._retry_initial_script_from_ui(project_id, dialog)

    assert dialog.opened is True
    assert status_updates
    assert status_updates[0]["project_id"] == project_id
    assert status_updates[0]["status"] == "queued"
    assert created_tasks
    await created_tasks[0]
    assert background_calls == [project_id]
    assert timers and timers[0]["interval"] == 5.0
    assert notifications == ["Retomando a criação do roteiro."]

def test_script_loading_stops_when_script_and_scenes_exist() -> None:
    assert (
        script_area.script_generation_in_progress(
            script=object(),
            ai_status="running",
            should_resume_stale_script=False,
        )
        is False
    )

def test_script_loading_stops_when_only_scenes_are_missing() -> None:
    assert (
        script_area.script_generation_in_progress(
            script=object(),
            ai_status="running",
            should_resume_stale_script=False,
        )
        is False
    )

def test_script_loading_stops_when_scene_plan_is_deferred_to_storyboard() -> None:
    assert (
        script_area.script_generation_in_progress(
            script=object(),
            ai_status="completed",
            should_resume_stale_script=False,
        )
        is False
    )

def test_legacy_assistant_greeting_is_removed_from_chat_history() -> None:
    assert (
        pages._is_legacy_assistant_greeting(
            "assistant",
            "Estou acompanhando está etapa. Posso revisar, propor variações.",
        )
        is True
    )
    assert pages._is_legacy_assistant_greeting("assistant", "Resposta real do agente.") is False

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

def test_visual_card_detail_includes_gender_for_character_profile() -> None:
    # INC-03: gênero virou campo obrigatório do perfil; "Sky" (neutro) e
    # personagens com o mesmo primeiro nome precisam de cards distinguisháveis.
    detail = pages._visual_card_detail(
        "character",
        {
            "gender": "pessoa de gênero não especificado",
            "apparent_age": "pessoa adulta",
            "eyes": "olhos castanhos",
            "hair": "cabelo preto curto",
            "base_outfit": "jaqueta cinza",
        },
    )

    assert detail.startswith("pessoa de gênero não especificado")
    assert "pessoa adulta, olhos castanhos" in detail

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
        "location",
        {
            "description": "Cenario afetivo de payoff narrativo.",
            "material": "papel",
        },
    )

    assert detail == "Cenario afetivo de payoff narrativo."

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

def test_storyboard_section_unlocks_before_scenes_and_shots_are_prepared() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "scripts": 1,
        "scenes": 0,
        "shots": 0,
        "characters": 2,
        "locations": 1,
        "visual_refs": 7,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    allowed, reason = pages._workspace_section_access("storyboard", counts)

    assert pages._step_ready("scenes", counts) is False
    assert allowed is True
    assert reason == ""

def test_production_steps_do_not_include_story_bible() -> None:
    step_keys = [step.key for step in pages.PRODUCTION_STEPS]

    assert "script" in step_keys
    assert "scenes" in step_keys
    assert "bible" not in step_keys

def test_workspace_tabs_start_with_script() -> None:
    tab_keys = [key for _, key in pages.WORKSPACE_TABS]

    assert tab_keys == ["script", "visual", "storyboard"]

