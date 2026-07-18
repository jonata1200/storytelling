from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling.service import (
    GenerationOutputError,
    coerce_duration_minutes,
    normalize_script_payload,
    normalize_story_idea_payload,
)
from app.ui import pages
from app.ui.pages import DEFAULT_STORY_DURATION_MINUTES, _compact_project_title


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
