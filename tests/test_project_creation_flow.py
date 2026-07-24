import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling import service as storytelling_service
from app.storytelling.models import StoryIdea
from app.storytelling.service import (
    GenerationOutputError,
    _bounded_required_str,
    _fallback_script_content_from_bible,
    _fallback_script_content_from_idea,
    _shot_narration_text,
    _story_idea_db_text,
    coerce_duration_minutes,
    expected_script_scene_count,
    normalize_scene_plan_payload,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    normalize_story_bible_payload,
    normalize_story_idea_payload,
    scene_plan_payload_from_script_content,
    screenplay_validation_errors,
    story_bible_validation_errors,
    story_idea_validation_errors,
)
from app.ui import pages
from app.ui.pages import DEFAULT_STORY_DURATION_MINUTES, _asset_url, _compact_project_title


def test_settings_tab_key_keeps_data_tab_after_destructive_actions() -> None:
    assert pages._settings_tab_key("data") == "data"
    assert pages._settings_tab_key("Dados") == "data"
    assert pages._settings_tab_key("ia") == "ai"
    assert pages._settings_tab_key(None) == "profile"


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
    assert created_tasks == [
        {"task": "task", "name": f"retry initial script {project_id}"}
    ]
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
    front = SimpleNamespace(
        project_id=project_id,
        target_kind="character",
        target_id=target_id,
        view_type="front_portrait",
        created_at=now + timedelta(seconds=1),
    )

    references = pages._visual_references_for(
        {"visual_refs": [back, front]},
        "character",
        target_id,
    )

    assert references == [front, back]


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
            [
                "left_profile",
                "right_profile",
                "back_view",
                "full_body",
                "expression_sheet",
                "pose_sheet",
                "scale_reference",
            ],
        ),
        ("location", location_id, ["establishing", "floor_plan", "camera_points"]),
        ("prop", prop_id, ["front", "side", "top", "scale_reference"]),
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
        "visual_refs": 10,
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
        "visual_refs": 23,
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


def test_idea_lab_duration_and_count_options_match_generation_controls() -> None:
    assert pages.STORY_DURATION_OPTIONS == [5, 10, 15, 20, 25]
    assert pages.IDEA_COUNT_OPTIONS == list(range(1, 11))
    assert "Documentário" not in pages.IDEA_GENRES
    assert "Histórias familiares emocionantes" not in pages.IDEA_GENRES


def test_story_idea_payload_is_normalized_for_pipeline() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A ultima mensagem",
            "premise": "Uma filha recebe uma mensagem atrasada do pai.",
        }
    )

    assert payload["title"] == "A ultima mensagem"
    assert payload["hook"] == "Uma filha recebe uma mensagem atrasada do pai."
    assert payload["duration_minutes"] == 5
    assert payload["retention_potential"] == 75
    assert payload["production_complexity"] == 35
    assert DEFAULT_STORY_DURATION_MINUTES == 5.0


def test_story_idea_payload_preserves_selected_duration() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "O relogio parado",
            "premise": "Uma familia revive o mesmo minuto ate dizer a verdade.",
            "duration_minutes": 7,
        }
    )

    assert payload["duration_minutes"] == 7
    assert coerce_duration_minutes("20") == 20.0
    assert coerce_duration_minutes("30") == 25.0


def test_story_idea_payload_coerces_non_integer_scores() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A promessa",
            "premise": "Uma promessa esquecida volta no pior dia possivel.",
            "retention_potential": "alto",
            "cliche_risk": "15%",
            "production_complexity": "8/10",
        }
    )

    assert payload["retention_potential"] == 80
    assert payload["cliche_risk"] == 15
    assert payload["production_complexity"] == 80


def test_story_idea_payload_defaults_unknown_scores() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "premise": "Uma carta chega tarde demais.",
            "retention_potential": "muito promissor",
            "cliche_risk": None,
            "production_complexity": "simples",
        }
    )

    assert payload["retention_potential"] == 75
    assert payload["cliche_risk"] == 25
    assert payload["production_complexity"] == 35


def test_story_idea_validation_requires_narrative_engine_fields() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "genre": "Drama",
            "primary_emotion": "Saudade",
            "hook": "Uma carta antiga aparece em uma mesa vazia.",
            "premise": "Uma filha precisa decidir se abre a ultima carta da mae.",
            "protagonist": "Lia, uma professora que evita despedidas",
            "retention_potential": 82,
            "cliche_risk": 18,
            "production_complexity": 30,
        }
    )

    errors = story_idea_validation_errors(payload)

    assert "campo obrigatorio vazio: conflict" in errors
    assert "campo obrigatorio vazio: twist" in errors
    assert "campo obrigatorio vazio: payoff" in errors
    assert "campo obrigatorio vazio: resolution" in errors


def test_story_idea_validation_accepts_complete_payload() -> None:
    payload = normalize_story_idea_payload(
        {
            "title": "A carta",
            "genre": "Drama",
            "primary_emotion": "Saudade",
            "hook": "Uma carta antiga aparece em uma mesa vazia.",
            "premise": "Uma filha precisa decidir se abre a ultima carta da mae.",
            "protagonist": "Lia, uma professora que evita despedidas",
            "conflict": "Abrir a carta pode destruir a imagem que ela guarda da mae.",
            "obstacles": ["culpa", "silencio familiar"],
            "stakes": "Perder a ultima chance de entender a propria historia.",
            "twist": "A carta foi escrita pela filha quando crianca.",
            "climax": "Lia le a carta diante da familia reunida.",
            "payoff": "Ela entende que a despedida era tambem uma permissao para viver.",
            "resolution": "Lia guarda a carta em um album aberto.",
            "retention_potential": 82,
            "cliche_risk": 18,
            "production_complexity": 30,
        }
    )

    assert story_idea_validation_errors(payload) == []


def test_story_bible_payload_is_normalized_to_structured_model() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "O ultimo almoco",
            "logline": "Uma avo prepara uma receita antes de revelar um segredo.",
            "characters": [
                {
                    "eyes": "olhos castanhos atentos",
                    "hair": "coque baixo branco",
                    "role": "protagonista",
                    "base_outfit": {
                        "peca_principal": "vestido azul",
                        "textura": "algodao gasto",
                    },
                },
                "palette_caracteristicas_visuais_para_o_personagem",
                "arc_aceita_dividir_o_legado",
            ],
        },
        {"protagonist": "Dona Lourdes"},
        cast(
            Any,
            SimpleNamespace(
                theme="memoria familiar",
                genre="drama",
                audience="adultos",
                primary_emotion="saudade",
            ),
        ),
    )

    assert payload["theme"] == "memoria familiar"
    assert payload["export_profile"] == {
        "aspect_ratio": "9:16",
        "resolution": "1080x1920",
        "language": "pt-BR",
    }
    assert len(payload["characters"]) == 1
    assert payload["characters"][0]["name"] == "Dona Lourdes"
    assert payload["characters"][0]["base_outfit"]["main_piece"] == "vestido azul"
    assert payload["locations"][0]["name"] == "Local principal"
    assert payload["props"][0]["name"] == "Objeto de revelacao"
    assert "script_contract" in payload
    assert "visual_contract" in payload
    assert payload["quality_report"]["completeness_score"] < 80


def test_complete_story_bible_payload_has_contracts_and_passes_validation() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "A carta azul",
            "logline": "Uma filha recebe uma mensagem atrasada do pai.",
            "theme": "perdao",
            "genre": "drama",
            "story_engine": {
                "dramatic_question": "Clara conseguira contar a verdade?",
                "central_conflict": "A carta muda a memoria da familia.",
                "emotional_promise": "A verdade dolorosa permite reconciliacao.",
                "inciting_incident": "Clara encontra a carta azul na sala.",
                "midpoint_turn": "Ela percebe que culpou a pessoa errada.",
                "climax": "Clara le a carta diante da familia.",
                "ending_image": "A porta da casa fica aberta ao amanhecer.",
            },
            "characters": [
                {
                    "name": "Clara",
                    "role": "protagonista",
                    "desire": "entender por que o pai partiu",
                    "fear": "descobrir que foi abandonada",
                    "arc": "troca culpa por coragem",
                    "base_outfit": {
                        "main_piece": "camisa azul",
                        "color": "azul frio",
                        "fabric": "algodao",
                        "texture": "tecido gasto",
                        "wear_marks": "punhos amassados",
                    },
                }
            ],
            "locations": [
                {
                    "name": "Casa da familia",
                    "description": "sala pequena com fotos antigas",
                    "lighting": "luz fria de fim de tarde",
                }
            ],
            "props": [
                {
                    "name": "Carta azul",
                    "narrative_importance": "revela o segredo familiar",
                }
            ],
            "continuity_rules": ["a carta sempre aparece com a mesma dobra"],
        }
    )

    assert payload["story_engine"]["midpoint_turn"] == "Ela percebe que culpou a pessoa errada."
    assert payload["script_contract"]["title"] == "A carta azul"
    assert payload["visual_contract"]["characters"][0]["name"] == "Clara"
    assert payload["quality_report"]["completeness_score"] >= 80
    assert story_bible_validation_errors(payload) == []


def test_story_bible_validation_reports_missing_production_fields() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "A carta",
            "logline": "Uma carta muda uma familia.",
        }
    )

    errors = story_bible_validation_errors(payload)

    assert "characters[].name/role/desire/arc/base_outfit" in errors
    assert "story_engine.inciting_incident" in errors


def test_story_bible_payload_accepts_named_location_and_prop_maps() -> None:
    payload = normalize_story_bible_payload(
        {
            "title": "A carta",
            "logline": "Uma carta muda uma familia.",
            "locais": {"sala_de_estar": {"lighting": "luz quente"}},
            "objetos": {"carta_azul": {"material": "papel envelhecido"}},
        }
    )

    assert payload["locations"][0]["name"] == "Sala De Estar"
    assert payload["locations"][0]["lighting"] == "luz quente"
    assert payload["props"][0]["name"] == "Carta Azul"
    assert payload["props"][0]["material"] == "papel envelhecido"


def test_story_idea_payload_requires_title() -> None:
    with pytest.raises(GenerationOutputError, match="title"):
        normalize_story_idea_payload({"premise": "sem titulo"})


def test_script_payload_accepts_common_ai_field_names() -> None:
    payload = normalize_script_payload(
        {
            "titulo": "ignorado",
            "roteiro": "Cena 1: Uma carta chega tarde demais.",
            "word_count": "8",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert payload["title"] == "A carta azul"
    assert payload["language"] == "pt-BR"
    assert payload["target_duration_seconds"] == 420
    assert payload["word_count"] > 8
    assert "FADE IN:" in payload["content"]
    assert "CENA 01" in payload["content"]
    assert "INT. CENA 1 - DIA" in payload["content"]
    assert "Cena 1: Uma carta chega tarde demais." in payload["content"]


def test_script_payload_preserves_briefing_duration_over_model_output() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "target_duration_seconds": 999,
            "content": "Cena 1: Uma carta chega tarde demais.",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert payload["target_duration_seconds"] == 420


def test_script_payload_adds_scene_markers_to_screenplay_without_cena_labels() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "content": """
TITULO: A carta azul

FADE IN:

INT. SALA - DIA

Clara encontra uma carta azul sobre a mesa e percebe que a mensagem chegou tarde.

EXT. QUINTAL - NOITE

Clara encara a janela acesa e decide contar a verdade antes do amanhecer.

FADE OUT.
""",
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=420,
    )

    assert "CENA 01\nINT. SALA - DIA" in payload["content"]
    assert "CENA 02\nEXT. QUINTAL - NOITE" in payload["content"]


def test_script_payload_normalizes_inline_scene_heading_from_model_response() -> None:
    payload = normalize_script_payload(
        {
            "title": "O Relampago de Papel",
            "content": """
FADE IN:

CENA 1 - INT. QUARTO DE IAN - NOITE

Chuva forte. IAN desenha um cavalo no caderno.

IAN
(sussurrando)
Não acredito...

CENA 2 - EXT. ESCOLA - DIA

Ian tenta brincar com colegas, mas o passaro de fogo assusta as criancas.

FADE OUT.
""",
        },
        default_title="O Relampago de Papel",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert "CENA 01\nINT. QUARTO DE IAN - NOITE" in payload["content"]
    assert "CENA 02\nEXT. ESCOLA - DIA" in payload["content"]
    assert "INT. CENA 1 - DIA" not in payload["content"]
    assert "FADE IN: CENA 1" not in payload["content"]


def test_screenplay_validator_rejects_technical_planning_document() -> None:
    errors = screenplay_validation_errors(
        """
ROTEIRO DE PRODUCAO

CENA 1 - GANCHO
Objetivo: apresentar conflito.
Acao: Clara abre a carta.
Indicacao para video: push-in lento.
"""
    )

    assert "faltou FADE IN" in errors
    assert "faltou slugline INT./EXT." in errors
    assert "conteudo contem rotulos tecnicos" in errors


def test_screenplay_validator_rejects_scene_and_slugline_on_same_line() -> None:
    errors = screenplay_validation_errors(
        """
FADE IN:

CENA 01
INT. SALA - DIA

Clara encontra a carta.

CENA 2 - EXT. QUINTAL - NOITE

Clara encara a janela acesa.

FADE OUT.
"""
    )

    assert "cenas e sluglines precisam ficar em linhas separadas" in errors


def test_story_idea_db_text_truncates_long_protagonist_for_varchar_column() -> None:
    payload = {
        "protagonist": (
            "Tadeu, 38 anos, mergulhador de resgate, ex-fuzileiro naval, solteiro, "
            "com pesadelos recorrentes de um naufragio que nao conseguiu evitar. "
            "Seu desejo e provar que e capaz de salvar vidas sob pressao extrema, "
            "mesmo quando a plataforma inteira esta prestes a explodir e todos duvidam dele."
        )
    }

    protagonist = _story_idea_db_text(payload, "protagonist", "story_idea")

    assert len(protagonist) <= 220
    assert protagonist.endswith("...")


def test_script_payload_preserves_embedded_production_plan_separately() -> None:
    payload = normalize_script_payload(
        {
            "title": "A carta azul",
            "content": """
TITULO: A carta azul

FADE IN:

CENA 01
INT. SALA - DIA

Clara encontra uma carta azul sobre a mesa e percebe que a mensagem chegou tarde.

FADE OUT.
""",
            "production_plan": {
                "scenes": [
                    {
                        "scene_number": 1,
                        "title": "A chegada",
                        "summary": "Clara encontra a carta.",
                        "duration_seconds": 60,
                        "shots": [
                            {
                                "shot_number": 1,
                                "duration_seconds": 60,
                                "narration_text": "Clara encontra a carta.",
                                "dialogue_text": "",
                                "action": "Clara pega a carta sobre a mesa.",
                                "emotion": "descoberta",
                                "visual_composition": "Plano vertical com carta e rosto.",
                                "camera_movement": "push-in lento",
                                "generation_type": "IMAGE_TO_VIDEO",
                            }
                        ],
                    }
                ]
            },
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=60,
    )

    assert payload["production_plan"]["scenes"][0]["shots"][0]["duration_seconds"] == 15
    assert "production_plan" not in payload["content"]


def test_scene_plan_payload_normalizes_shots_to_seedance_duration_range() -> None:
    payload = normalize_scene_plan_payload(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "Cena longa",
                    "summary": "Clara entende a carta.",
                    "duration_seconds": 60,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 60,
                            "narration_text": "Clara abre a carta.",
                            "dialogue_text": "",
                            "action": "Clara abre a carta diante da janela.",
                            "emotion": "descoberta",
                            "visual_composition": "Plano vertical com carta e rosto.",
                            "camera_movement": "push-in lento",
                            "generation_type": "IMAGE_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        60,
    )

    shots = [shot for scene in payload["scenes"] for shot in scene["shots"]]
    assert sum(shot["duration_seconds"] for shot in shots) == 60
    assert all(4 <= shot["duration_seconds"] <= 15 for shot in shots)
    assert payload["scenes"][0]["duration_seconds"] == 60


def test_scene_plan_payload_uses_script_scene_markers_when_ai_returns_one_scene() -> None:
    script = """CENA 1
INT. SALA DE ESTAR - FINAL DE TARDE
DURACAO: 60s
OBJETIVO: Apresentar a chegada inesperada.

CENA 2
EXT. QUINTAL - NOITE
DURACAO: 60s
OBJETIVO: Revelar o segredo.
"""
    payload = normalize_scene_plan_payload_from_script(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "Cena unica",
                    "summary": "Resumo geral.",
                    "duration_seconds": 120,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": 120,
                            "narration_text": "Resumo geral.",
                            "dialogue_text": "",
                            "action": "Resumo geral.",
                            "emotion": "tensao",
                            "visual_composition": "Plano vertical.",
                            "camera_movement": "push-in",
                            "generation_type": "IMAGE_TO_VIDEO",
                        }
                    ],
                }
            ]
        },
        120,
        script,
    )

    assert [scene["title"] for scene in payload["scenes"]] == [
        "INT. SALA DE ESTAR - FINAL DE TARDE",
        "EXT. QUINTAL - NOITE",
    ]


def test_scene_plan_payload_can_be_derived_from_structured_script_without_llm() -> None:
    script = """TITULO: O Relampago de Papel

FADE IN:

CENA 01
INT. QUARTO DE IAN - NOITE

Ian desenha um cavalo no caderno enquanto a chuva bate na janela.

CENA 02
EXT. ESCOLA - DIA

Ian tenta brincar com colegas, mas o passaro de fogo assusta as criancas.

FADE OUT.
"""

    payload = scene_plan_payload_from_script_content(script, 120)

    assert payload is not None
    assert [scene["title"] for scene in payload["scenes"]] == [
        "INT. QUARTO DE IAN - NOITE",
        "EXT. ESCOLA - DIA",
    ]
    assert sum(scene["duration_seconds"] for scene in payload["scenes"]) == 120
    assert all(
        4 <= shot["duration_seconds"] <= 15
        for scene in payload["scenes"]
        for shot in scene["shots"]
    )


def test_script_payload_builds_content_from_scene_list_when_content_is_empty() -> None:
    payload = normalize_script_payload(
        {
            "content": "",
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "A chegada",
                    "action": "Clara encontra a carta na porta.",
                    "video_direction": "Dolly in lento ate a mao dela.",
                }
            ],
        },
        default_title="A carta azul",
        language="pt-BR",
        target_duration_seconds=300,
    )

    assert "FADE IN:" in payload["content"]
    assert "CENA 01" in payload["content"]
    assert "INT. A CHEGADA - DIA" in payload["content"]
    assert "Clara encontra a carta na porta." in payload["content"]
    assert "Titulo:" not in payload["content"]
    assert "Acao:" not in payload["content"]
    assert "Dolly in lento" not in payload["content"]


def test_fallback_script_content_from_bible_is_usable_when_model_returns_empty_script() -> None:
    content = _fallback_script_content_from_bible(
        {
            "logline": "Uma filha recebe uma mensagem atrasada do pai.",
            "characters": [{"name": "Clara", "role": "filha"}],
            "locations": [{"name": "Casa da familia"}],
        },
        "A mensagem atrasada",
        300,
    )

    assert "TITULO: A mensagem atrasada" in content
    assert "FADE IN:" in content
    assert "CENA 01" in content
    assert "INT. CASA DA FAMILIA - FIM DE TARDE" in content
    assert "Indicacao para video" not in content
    assert "Objetivo dramatico" not in content


def test_fallback_script_content_from_idea_scales_scene_count_with_duration() -> None:
    content = _fallback_script_content_from_idea(
        {
            "title": "A promessa longa",
            "premise": "Uma familia precisa sustentar uma verdade dificil.",
            "protagonist": "Clara",
        },
        "A promessa longa",
        900,
    )

    assert expected_script_scene_count(300) == 5
    assert expected_script_scene_count(900) == 12
    assert content.count("CENA ") == 12
    assert "CENA 12" in content


@pytest.mark.asyncio
async def test_developing_story_idea_starts_initial_script_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_project_from_form(
        form: dict[str, Any],
        *,
        generate_initial_script: bool = False,
        generate_initial_story_bible: bool = False,
        source_idea: dict[str, Any] | None = None,
    ) -> None:
        captured["form"] = form
        captured["generate_initial_script"] = generate_initial_script
        captured["generate_initial_story_bible"] = generate_initial_story_bible
        captured["source_idea"] = source_idea

    monkeypatch.setattr(pages, "_create_project_from_form", fake_create_project_from_form)
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_image_model="google/gemini-2.5-flash-image",
            openrouter_video_model="google/veo-3.1",
        ),
    )
    idea = {
        "title": "O minuto perdido",
        "theme": "uma familia que esquece um segredo",
        "genre": "Drama",
        "primary_emotion": "Esperanca",
        "premise": "Uma familia revive o mesmo minuto ate dizer a verdade.",
        "obstacles": ["culpa antiga", "silencio familiar"],
        "twist": "O segredo protegeu a protagonista.",
        "duration_minutes": 7,
    }

    await pages._create_project_from_idea(idea)

    assert captured["generate_initial_script"] is True
    assert captured["generate_initial_story_bible"] is False
    assert captured["source_idea"] is idea
    assert captured["form"]["duration"] == 7
    assert "7 minutos" in captured["form"]["objective"]
    assert "adequar para 7 minutos" in captured["form"]["constraints"]
    assert captured["form"]["source_idea_payload"] == idea
    assert "Obstáculos: culpa antiga, silencio familiar" in captured["form"]["one_line_idea"]
    assert "Virada: O segredo protegeu a protagonista." in captured["form"]["one_line_idea"]


@pytest.mark.asyncio
async def test_generate_script_does_not_save_mock_when_provider_fails_before_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    briefing_artifact_id = uuid4()
    idea_artifact_id = uuid4()
    project = SimpleNamespace(id=project_id)
    idea = SimpleNamespace(
        id=idea_id,
        project_id=project_id,
        artifact_id=idea_artifact_id,
        title="O farol apagado",
        hook="Uma faroleira acende a luz para um barco que não existe.",
        premise="Uma jovem mantém um farol ligado contra a vontade da cidade.",
        protagonist="Lia, uma faroleira teimosa",
        payload={
            "title": "O farol apagado",
            "hook": "Uma faroleira acende a luz para um barco que não existe.",
            "premise": "Uma jovem mantém um farol ligado contra a vontade da cidade.",
            "protagonist": "Lia, uma faroleira teimosa",
            "conflict": "A cidade quer desligar o farol.",
            "payoff": "A luz salva quem ainda está no mar.",
        },
    )
    briefing = SimpleNamespace(
        artifact_id=briefing_artifact_id,
        desired_duration_minutes=5,
        language="pt-BR",
        theme="luto e recomeço",
        genre="Drama",
        primary_emotion="Esperança",
        audience="público geral",
        constraints="produção simples",
        visual_style="cinemático realista",
    )

    class FakeProjectRepository:
        def __init__(self, session: object) -> None:
            pass

        async def get_project(self, requested_project_id: object) -> object:
            assert requested_project_id == project_id
            return project

    class FakeSession:
        async def get(self, model: object, requested_id: object) -> object:
            assert model is StoryIdea
            assert requested_id == idea_id
            return idea

        def add(self, item: object) -> None:
            pass

        async def flush(self) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def refresh(self, item: object) -> None:
            pass

    async def fake_latest_briefing(session: object, requested_project_id: object) -> object:
        assert requested_project_id == project_id
        return briefing

    async def fake_provider_for_task(
        session: object, requested_project_id: object, task: str
    ) -> tuple[object, str]:
        assert requested_project_id == project_id
        assert task == "generate_script"
        return object(), "unstable-model"

    async def fake_run_structured_generation(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("OpenRouter retornou conteúdo que não é JSON válido")

    async def fake_create_artifact(*args: object, **kwargs: object) -> object:
        raise AssertionError("roteiro mock/local não deve ser salvo como geração real")

    async def fake_add_dependency(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(storytelling_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(storytelling_service, "get_latest_briefing", fake_latest_briefing)
    monkeypatch.setattr(storytelling_service, "llm_provider_for_task", fake_provider_for_task)
    monkeypatch.setattr(
        storytelling_service,
        "run_structured_generation",
        fake_run_structured_generation,
    )
    monkeypatch.setattr(storytelling_service, "_create_artifact", fake_create_artifact)
    monkeypatch.setattr(storytelling_service, "_add_dependency", fake_add_dependency)
    monkeypatch.setattr(storytelling_service, "advance_project_status", lambda *args: None)

    with pytest.raises(RuntimeError, match="OpenRouter retornou"):
        await storytelling_service.generate_script(
            cast(AsyncSession, FakeSession()),
            project_id,
            idea_id,
        )


@pytest.mark.asyncio
async def test_initial_script_pipeline_uses_selected_idea_and_creates_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    script_id = uuid4()
    selected_idea = {"title": "A carta azul", "premise": "Uma carta chega no dia certo."}
    calls: list[str] = []

    async def fake_create_story_idea_from_payload(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("idea")
        assert args[1] == project_id
        assert args[2] is selected_idea
        return SimpleNamespace(id=idea_id)

    async def fake_generate_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("script")
        assert args[1] == project_id
        assert args[2] == idea_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("scenes")
        assert args[1] == project_id
        assert args[2] == script_id
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(
        pages, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)
    monkeypatch.setattr(pages, "generate_scenes_and_shots", fake_generate_scenes_and_shots)

    script = await pages._generate_initial_script(
        cast(AsyncSession, object()), project_id, selected_idea
    )

    assert script.id == script_id
    assert calls == ["idea", "script", "scenes"]


def test_initial_story_bible_pipeline_was_removed() -> None:
    assert not hasattr(pages, "_generate_initial_story_bible")


@pytest.mark.asyncio
async def test_project_chat_can_trigger_script_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_latest(
        session: AsyncSession, model: type[Any], requested_project_id: Any
    ) -> SimpleNamespace | None:
        assert requested_project_id == project_id
        if model is pages.Briefing:
            return SimpleNamespace(id=uuid4())
        return None

    async def fake_generate_story_ideas(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("ideas")
        return [SimpleNamespace(id=idea_id)]

    async def fake_generate_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("script")
        assert args[2] == idea_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("scenes")
        assert args[2] == script_id
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(pages, "_latest", fake_latest)
    monkeypatch.setattr(pages, "generate_story_ideas", fake_generate_story_ideas)
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)
    monkeypatch.setattr(pages, "generate_scenes_and_shots", fake_generate_scenes_and_shots)

    message, should_reload = await pages._develop_script_for_existing_project(
        cast(AsyncSession, object()), project_id
    )

    assert message == "Roteiro criado e dividido em cenas e planos."
    assert should_reload is True
    assert calls == ["ideas", "script", "scenes"]
