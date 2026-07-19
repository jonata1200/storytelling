from datetime import datetime, timedelta
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
    normalize_story_idea_payload,
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
    tmp_path,
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
    tmp_path,
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


def test_visual_library_cards_ready_requires_all_card_types() -> None:
    assert pages._visual_library_cards_ready(
        {"characters": [object()], "locations": [object()], "props": [object()]}
    )
    assert not pages._visual_library_cards_ready(
        {"characters": [object()], "locations": [], "props": [object()]}
    )


def test_visual_batch_requests_include_only_missing_initial_images() -> None:
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


def test_assistant_flow_actions_start_at_assets_stage() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "bibles": 1,
        "scripts": 1,
        "scenes": 1,
        "shots": 1,
        "characters": 0,
        "frames": 0,
        "animatics": 0,
        "clips": 0,
        "exports": 0,
        "qa_issues": 0,
    }

    assert pages._assistant_flow_actions("script", counts) is None

    assets_actions = pages._assistant_flow_actions("assets", counts)

    assert assets_actions is not None
    assert assets_actions["continue_label"] == "Criar ativos"
    assert assets_actions["continue_target"] == "assets"
    assert "revisar" in assets_actions["review_user_message"]


def test_assistant_flow_actions_advance_when_stage_is_ready() -> None:
    counts = {
        "briefings": 1,
        "ideas": 1,
        "bibles": 1,
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

    assets_actions = pages._assistant_flow_actions("assets", counts)
    storyboard_actions = pages._assistant_flow_actions("storyboard", counts)
    video_actions = pages._assistant_flow_actions("video", counts)

    assert assets_actions is not None
    assert storyboard_actions is not None
    assert video_actions is not None
    assert assets_actions["continue_target"] == "storyboard"
    assert storyboard_actions["continue_target"] == "video"
    assert video_actions["continue_label"] == "Preparar video"


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
    assert payload["word_count"] == 8
    assert payload["content"] == "Cena 1: Uma carta chega tarde demais."


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

    assert "Cena: 1" in payload["content"]
    assert "Titulo: A chegada" in payload["content"]
    assert "Acao: Clara encontra a carta na porta." in payload["content"]


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

    assert "ROTEIRO DE PRODUCAO - A mensagem atrasada" in content
    assert "CENA 1 - GANCHO INICIAL" in content
    assert "Indicacao para video" in content


@pytest.mark.asyncio
async def test_developing_story_idea_starts_initial_script_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_project_from_form(
        form: dict[str, Any],
        *,
        generate_initial_script: bool = False,
        source_idea: dict[str, Any] | None = None,
    ) -> None:
        captured["form"] = form
        captured["generate_initial_script"] = generate_initial_script
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

    assert captured["generate_initial_script"] is True
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
