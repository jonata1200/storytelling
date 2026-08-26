# ruff: noqa: F401
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
    _fallback_script_content_from_idea,
    _shot_narration_text,
    _story_idea_db_text,
    coerce_duration_minutes,
    expected_script_scene_count,
    normalize_scene_plan_payload,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    normalize_story_idea_payload,
    scene_plan_payload_from_script_content,
    screenplay_validation_errors,
    story_idea_validation_errors,
)
from app.ui import pages
from app.ui.pages import DEFAULT_STORY_DURATION_MINUTES, _asset_url, _compact_project_title
from app.ui.workspace import script_area, storyboard_video_area


@pytest.mark.asyncio
async def test_developing_story_idea_waits_for_script_duration_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_project_from_form(
        form: dict[str, Any],
        *,
        generate_initial_script: bool = False,
        generate_initial_idea: bool = False,
        generate_initial_story_bible: bool = False,
        source_idea: dict[str, Any] | None = None,
    ) -> None:
        captured["form"] = form
        captured["generate_initial_script"] = generate_initial_script
        captured["generate_initial_idea"] = generate_initial_idea
        captured["generate_initial_story_bible"] = generate_initial_story_bible
        captured["source_idea"] = source_idea

    monkeypatch.setattr(pages, "_create_project_from_form", fake_create_project_from_form)
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(
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
    assert captured["generate_initial_idea"] is False
    assert captured["generate_initial_story_bible"] is False
    assert captured["source_idea"] is idea
    assert captured["form"]["duration"] == DEFAULT_STORY_DURATION_MINUTES
    assert "duração definida no roteiro" in captured["form"]["objective"]
    assert "aguardar duração definida no roteiro" in captured["form"]["constraints"]
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
        raise RuntimeError("Provider retornou conteúdo que não é JSON válido")

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

    with pytest.raises(RuntimeError, match="Provider retornou"):
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

    monkeypatch.setattr(
        pages, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)

    script = await pages._generate_initial_script(
        cast(AsyncSession, object()), project_id, selected_idea
    )

    assert script.id == script_id
    assert calls == ["idea", "script"]


@pytest.mark.asyncio
async def test_dashboard_project_queues_missing_idea_without_skipping_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    duration_dialog = object()
    queued: list[tuple[object, object, object]] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_latest(*args: object, **kwargs: object) -> None:
        return None

    async def fake_enqueue(
        session: object,
        requested_project_id: object,
        step: object,
    ) -> None:
        queued.append((requested_project_id, step, session))

    def unexpected_loading_dialog(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("o dashboard não deve aguardar ideia ou ganchos na interface")

    monkeypatch.setattr(script_area, "block_if_missing_api_keys_for_step", lambda _step: False)
    monkeypatch.setattr(script_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(script_area, "_latest", fake_latest)
    monkeypatch.setattr(script_area, "enqueue_project_step", fake_enqueue)
    monkeypatch.setattr(script_area.ui.navigate, "reload", lambda: None)
    monkeypatch.setattr(script_area.ui, "notify", lambda *args, **kwargs: None)

    await script_area._prepare_script_with_story_hooks(
        project_id,
        5,
        duration_dialog,
        unexpected_loading_dialog,
    )

    assert len(queued) == 1
    assert queued[0][0:2] == (project_id, "ideas")


@pytest.mark.asyncio
async def test_dashboard_creation_schedules_idea_before_hook_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_project_from_form(
        form: dict[str, Any],
        *,
        generate_initial_script: bool = False,
        generate_initial_idea: bool = False,
        source_idea: dict[str, Any] | None = None,
    ) -> None:
        captured.update(
            generate_initial_script=generate_initial_script,
            generate_initial_idea=generate_initial_idea,
            source_idea=source_idea,
        )

    monkeypatch.setattr(pages, "_create_project_from_form", fake_create_project_from_form)
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(
        ),
    )

    await pages._create_project_from_chat_prompt("Uma fotografia muda cada vez que é limpa")

    assert captured == {
        "generate_initial_script": False,
        "generate_initial_idea": True,
        "source_idea": None,
    }


def test_initial_story_bible_pipeline_was_removed() -> None:
    assert not hasattr(pages, "_generate_initial_story_bible")


def test_script_revision_size_targets_shrink_generic_reduction_request() -> None:
    duration, words, guidance = storytelling_service._script_revision_size_targets(
        "poderia reduzir o tamanho desse roteiro, esta muito grande e extensa",
        300,
        900,
    )

    assert duration == 196
    assert words == 588
    assert "redução" in guidance
    assert "mais curta" in guidance


def test_script_revision_size_targets_use_explicit_duration() -> None:
    duration, words, guidance = storytelling_service._script_revision_size_targets(
        "reduza para 2 minutos",
        300,
        900,
    )

    assert duration == 120
    assert words == 360
    assert "120s" in guidance


def test_script_revision_size_targets_round_odd_explicit_seconds_for_video_clips() -> None:
    duration, words, guidance = storytelling_service._script_revision_size_targets(
        "reduza para 195 segundos",
        300,
        900,
    )

    assert duration == 196
    assert words == 588
    assert "196s" in guidance


def test_video_package_total_duration_rounds_odd_values() -> None:
    assert storytelling_service._video_package_total_duration_seconds(195) == 196
    assert storytelling_service._video_package_total_duration_seconds(196) == 196


def test_script_duration_choice_allows_one_to_twenty_minutes() -> None:
    assert storytelling_service.coerce_script_duration_minutes("1") == 1.0
    assert storytelling_service.coerce_script_duration_minutes("20") == 20.0
    assert storytelling_service.coerce_script_duration_minutes("0") == 1.0
    assert storytelling_service.coerce_script_duration_minutes("21") == 20.0


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

    monkeypatch.setattr(pages, "_latest", fake_latest)
    monkeypatch.setattr(pages, "generate_story_ideas", fake_generate_story_ideas)
    monkeypatch.setattr(pages, "generate_script", fake_generate_script)

    message, should_reload = await pages._develop_script_for_existing_project(
        cast(AsyncSession, object()), project_id
    )

    assert message == "Roteiro criado."
    assert should_reload is True
    assert calls == ["ideas", "script"]
