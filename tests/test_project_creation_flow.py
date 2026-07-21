from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling.service import (
    GenerationOutputError,
    _bounded_required_str,
    _fallback_script_content_from_bible,
    _shot_narration_text,
    coerce_duration_minutes,
    normalize_scene_plan_payload,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    normalize_story_bible_payload,
    normalize_story_idea_payload,
    screenplay_validation_errors,
    story_bible_validation_errors,
    story_idea_validation_errors,
)
from app.ui import pages
from app.ui.pages import DEFAULT_STORY_DURATION_MINUTES, _asset_url, _compact_project_title


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


def test_story_bible_section_unlocks_when_bible_exists() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "bibles": 1,
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

    allowed, reason = pages._workspace_section_access("bible", counts)

    assert allowed is True
    assert reason == ""


def test_story_bible_section_is_first_available_even_before_generation() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "bibles": 0,
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

    assert allowed is True
    assert reason == ""
    assert pages._first_available_workspace_section(counts) == "bible"


def test_production_steps_show_script_before_story_bible() -> None:
    step_keys = [step.key for step in pages.PRODUCTION_STEPS]

    assert step_keys.index("script") < step_keys.index("bible")


def test_workspace_tabs_show_story_bible_before_script() -> None:
    tab_keys = [key for _, key in pages.WORKSPACE_TABS]

    assert tab_keys[:2] == ["bible", "script"]


def test_story_bible_items_present_named_sections() -> None:
    items = pages._story_bible_items(
        [
            {
                "name": "Dona Celia",
                "role": "protagonista",
                "arc": "aceita dividir o legado",
            },
            "regra de continuidade visual",
        ]
    )

    assert items[0]["name"] == "Dona Celia"
    assert "protagonista" in items[0]["detail"]
    assert items[1] == {"name": "regra de continuidade visual", "detail": ""}


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
    assert coerce_duration_minutes("20") == 8.0


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


@pytest.mark.asyncio
async def test_developing_story_idea_starts_initial_story_bible_pipeline(
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
            openrouter_image_model="mock-image",
            openrouter_video_model="mock-video",
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

    assert captured["generate_initial_script"] is False
    assert captured["generate_initial_story_bible"] is True
    assert captured["source_idea"] is idea
    assert captured["form"]["duration"] == 7
    assert "7 minutos" in captured["form"]["objective"]
    assert "adequar para 7 minutos" in captured["form"]["constraints"]
    assert captured["form"]["source_idea_payload"] == idea
    assert "Obstaculos: culpa antiga, silencio familiar" in captured["form"]["one_line_idea"]
    assert "Virada: O segredo protegeu a protagonista." in captured["form"]["one_line_idea"]


@pytest.mark.asyncio
async def test_initial_script_pipeline_uses_selected_idea_and_creates_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    bible_id = uuid4()
    script_id = uuid4()
    selected_idea = {"title": "A carta azul", "premise": "Uma carta chega no dia certo."}
    calls: list[str] = []

    async def fake_create_story_idea_from_payload(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("idea")
        assert args[1] == project_id
        assert args[2] is selected_idea
        return SimpleNamespace(id=idea_id)

    async def fake_generate_story_bible(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("bible")
        assert args[1] == project_id
        assert args[2] == idea_id
        return SimpleNamespace(id=bible_id)

    async def fake_generate_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("script")
        assert args[1] == project_id
        assert args[2] == bible_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("scenes")
        assert args[1] == project_id
        assert args[2] == script_id
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(
        pages, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )
    monkeypatch.setattr(pages, "generate_story_bible", fake_generate_story_bible)
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)
    monkeypatch.setattr(pages, "generate_scenes_and_shots", fake_generate_scenes_and_shots)

    script = await pages._generate_initial_script(
        cast(AsyncSession, object()), project_id, selected_idea
    )

    assert script.id == script_id
    assert calls == ["idea", "bible", "script", "scenes"]


@pytest.mark.asyncio
async def test_initial_story_bible_pipeline_uses_selected_idea_without_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    bible_id = uuid4()
    selected_idea = {"title": "A carta azul", "premise": "Uma carta chega no dia certo."}
    calls: list[str] = []

    async def fake_create_story_idea_from_payload(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("idea")
        assert args[1] == project_id
        assert args[2] is selected_idea
        return SimpleNamespace(id=idea_id)

    async def fake_generate_story_bible(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("bible")
        assert args[1] == project_id
        assert args[2] == idea_id
        return SimpleNamespace(id=bible_id)

    async def fake_generate_script(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("script generation should not run")

    monkeypatch.setattr(
        pages, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )
    monkeypatch.setattr(pages, "generate_story_bible", fake_generate_story_bible)
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)

    story_bible = await pages._generate_initial_story_bible(
        cast(AsyncSession, object()), project_id, selected_idea
    )

    assert story_bible.id == bible_id
    assert calls == ["idea", "bible"]


@pytest.mark.asyncio
async def test_project_chat_can_trigger_script_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    bible_id = uuid4()
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

    async def fake_generate_story_bible(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("bible")
        assert args[2] == idea_id
        return SimpleNamespace(id=bible_id)

    async def fake_generate_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("script")
        assert args[2] == bible_id
        return SimpleNamespace(id=script_id)

    async def fake_generate_scenes_and_shots(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("scenes")
        assert args[2] == script_id
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(pages, "_latest", fake_latest)
    monkeypatch.setattr(pages, "generate_story_ideas", fake_generate_story_ideas)
    monkeypatch.setattr(pages, "generate_story_bible", fake_generate_story_bible)
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)
    monkeypatch.setattr(pages, "generate_scenes_and_shots", fake_generate_scenes_and_shots)

    message, should_reload = await pages._develop_script_for_existing_project(
        cast(AsyncSession, object()), project_id
    )

    assert message == "Roteiro criado e dividido em cenas e planos."
    assert should_reload is True
    assert calls == ["ideas", "bible", "script", "scenes"]
