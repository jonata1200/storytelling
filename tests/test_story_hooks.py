# ruff: noqa: F401
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling import service as storytelling_service
from app.storytelling.models import StoryIdea
from app.storytelling.normalization import normalize_story_hooks_payload
from app.storytelling.normalization_common import GenerationOutputError
from app.ui.workspace import script_area


def _valid_hooks(count: int = 5) -> dict:
    return {
        "hooks": [
            {
                "title": f"Gancho de abertura {index}",
                "description": (
                    f"Descrição do gancho {index}: a cena abre com uma imagem forte "
                    "e coloca a protagonista em risco imediato."
                ),
            }
            for index in range(1, count + 1)
        ]
    }


def test_normalize_story_hooks_accepts_five_valid_hooks() -> None:
    hooks = normalize_story_hooks_payload(_valid_hooks(5))

    assert len(hooks) == 5
    assert all(hook["title"] and hook["description"] for hook in hooks)
    assert hooks[0]["title"] == "Gancho de abertura 1"


def test_normalize_story_hooks_rejects_less_than_five() -> None:
    with pytest.raises(GenerationOutputError, match="pelo menos 5"):
        normalize_story_hooks_payload(_valid_hooks(4))


def test_normalize_story_hooks_rejects_missing_fields() -> None:
    with pytest.raises(GenerationOutputError):
        normalize_story_hooks_payload(
            {"hooks": [{"title": "Sem descrição"}] * 5}
        )


def test_normalize_story_hooks_dedupes_repeated_titles() -> None:
    payload = _valid_hooks(5)
    payload["hooks"].append({"title": "Gancho de abertura 1", "description": "repetida"})
    payload["hooks"].append({"title": "Gancho de abertura 2", "description": "repetida"})

    hooks = normalize_story_hooks_payload(payload)

    assert len(hooks) == 5


def test_normalize_story_hooks_truncates_long_fields() -> None:
    hooks = normalize_story_hooks_payload(
        {
            "hooks": [
                {
                    "title": f"Título longo {index}" + "T" * 300,
                    "description": "D" * 900,
                }
                for index in range(1, 6)
            ]
        }
    )

    assert len(hooks) == 5
    assert len(hooks[0]["title"]) == 120
    assert len(hooks[0]["description"]) == 500


@pytest.mark.asyncio
async def test_generate_story_hooks_returns_hooks_from_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    project = SimpleNamespace(id=project_id)
    idea = SimpleNamespace(
        id=idea_id,
        project_id=project_id,
        artifact_id=uuid4(),
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
        artifact_id=uuid4(),
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

    async def fake_latest_briefing(session: object, requested_project_id: object) -> object:
        assert requested_project_id == project_id
        return briefing

    async def fake_provider_for_task(
        session: object, requested_project_id: object, task: str
    ) -> tuple[object, str]:
        assert requested_project_id == project_id
        assert task == "generate_story_hooks"
        return object(), "unstable-model"

    async def fake_run_structured_generation(*args: object, **kwargs: object) -> tuple[Any, Any]:
        variables = cast(dict, args[4])
        assert kwargs.get("model") == "unstable-model"
        assert "narrative_contract" in variables
        return SimpleNamespace(content=_valid_hooks(6)), object()

    monkeypatch.setattr(storytelling_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(storytelling_service, "get_latest_briefing", fake_latest_briefing)
    monkeypatch.setattr(storytelling_service, "llm_provider_for_task", fake_provider_for_task)
    monkeypatch.setattr(
        storytelling_service,
        "run_structured_generation",
        fake_run_structured_generation,
    )

    hooks = await storytelling_service.generate_story_hooks(
        cast(AsyncSession, FakeSession()),
        project_id,
        idea_id,
    )

    assert hooks is not None
    assert len(hooks) == 6
    assert all(hook["title"] and hook["description"] for hook in hooks)


@pytest.mark.asyncio
async def test_generate_story_hooks_returns_none_when_idea_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    project = SimpleNamespace(id=project_id)

    class FakeProjectRepository:
        def __init__(self, session: object) -> None:
            pass

        async def get_project(self, requested_project_id: object) -> object:
            return project

    class FakeSession:
        async def get(self, model: object, requested_id: object) -> object:
            return None

    async def fake_latest_briefing(session: object, requested_project_id: object) -> object:
        return SimpleNamespace()

    monkeypatch.setattr(storytelling_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(storytelling_service, "get_latest_briefing", fake_latest_briefing)

    hooks = await storytelling_service.generate_story_hooks(
        cast(AsyncSession, FakeSession()),
        project_id,
        idea_id,
    )

    assert hooks is None


@pytest.mark.asyncio
async def test_generate_script_embeds_chosen_hook_in_prompt_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    idea_id = uuid4()
    artifact_id = uuid4()
    story_hook = {
        "title": "A luz que ninguém vê",
        "description": "Lia acende o farol para um barco que a cidade jura não existir.",
    }
    captured: dict[str, Any] = {}
    project = SimpleNamespace(id=project_id)
    idea = SimpleNamespace(
        id=idea_id,
        project_id=project_id,
        artifact_id=uuid4(),
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
        artifact_id=uuid4(),
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
            return project

    added_scripts: list[Any] = []

    class FakeSession:
        async def get(self, model: object, requested_id: object) -> object:
            assert model is StoryIdea
            assert requested_id == idea_id
            return idea

        def add(self, item: object) -> None:
            added_scripts.append(item)

        async def flush(self) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def refresh(self, item: object) -> None:
            pass

    async def fake_latest_briefing(session: object, requested_project_id: object) -> object:
        return briefing

    async def fake_provider_for_task(
        session: object, requested_project_id: object, task: str
    ) -> tuple[object, str]:
        assert task == "generate_script"
        return object(), "unstable-model"

    async def fake_run_structured_generation(*args: object, **kwargs: object) -> tuple[Any, Any]:
        captured["variables"] = dict(cast(dict, args[4]))
        return (
            SimpleNamespace(
                content={
                    "title": "O farol apagado",
                    "language": "pt-BR",
                    "target_duration_seconds": 300,
                    "word_count": 40,
                    "content": (
                        "FADE IN:\n\nCENA 01\nINT. FAROL - NOITE\n\n"
                        "Lia acende a luz para o barco vazio."
                    ),
                }
            ),
            object(),
        )

    async def fake_create_artifact(
        session: object,
        requested_project_id: object,
        artifact_type: object,
        title: str,
        payload: dict,
    ) -> object:
        captured["artifact_payload"] = payload
        return SimpleNamespace(id=artifact_id)

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

    # Garante que o projeto NÃO está com title_locked — o teste valida que o
    # título devolvido pelo LLM é preservado (projeto da dashboard).
    async def fake_not_locked(_session: Any, _pid: Any) -> bool:
        return False

    from app.projects import service as project_service_in_hook

    monkeypatch.setattr(project_service_in_hook, "_project_title_is_locked", fake_not_locked)
    monkeypatch.setattr(
        storytelling_service,
        "_advance_project_status_when_reachable",
        lambda *args: None,
    )

    script = await storytelling_service.generate_script(
        cast(AsyncSession, FakeSession()),
        project_id,
        idea_id,
        story_hook=story_hook,
    )

    assert script is not None
    contract = captured["variables"]["narrative_contract"]
    assert contract["story_hook"] == story_hook
    assert captured["variables"]["story_hook"] == story_hook
    assert captured["artifact_payload"]["story_hook"] == story_hook
    assert added_scripts and added_scripts[0].story_hook == story_hook
    assert script.story_hook == story_hook


@pytest.mark.asyncio
async def test_enqueue_script_generation_includes_story_hook_in_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    story_hook = {"title": "A luz que ninguém vê", "description": "Abertura em risco."}
    captured: dict[str, Any] = {}
    reloads: list[bool] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_enqueue(
        session: object,
        requested_project_id: object,
        step: str,
        payload: dict[str, Any],
    ) -> object:
        assert requested_project_id == project_id
        assert step == "script"
        captured.update(payload)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(script_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(script_area, "enqueue_project_step", fake_enqueue)
    monkeypatch.setattr(
        script_area.ui,
        "notify",
        lambda message, **kwargs: None,
    )
    monkeypatch.setattr(script_area.ui.navigate, "reload", lambda: reloads.append(True))

    await script_area._enqueue_script_generation(project_id, 5.0, story_hook, object())

    assert captured == {"target_duration_minutes": 5.0, "story_hook": story_hook}
    assert reloads == [True]


@pytest.mark.asyncio
async def test_prepare_script_with_story_hooks_opens_hooks_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    hooks = _valid_hooks(5)["hooks"]
    opened_dialogs: list[tuple[str, str]] = []
    opened_hooks: dict[str, Any] = {}

    class FakeLoadingDialog:
        def __init__(self) -> None:
            self.opened = False

        def open(self) -> None:
            self.opened = True

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_latest(session: object, model: object, requested_project_id: object) -> object:
        assert requested_project_id == project_id
        return SimpleNamespace(id=uuid4())

    async def fake_generate_story_hooks(
        session: object, requested_project_id: object, idea_id: object
    ) -> list[dict[Any, Any]]:
        assert requested_project_id == project_id
        return hooks  # type: ignore[no-any-return]

    def fake_factory(title: str, message: str) -> FakeLoadingDialog:
        opened_dialogs.append((title, message))
        return FakeLoadingDialog()

    def fake_open_hooks_dialog(
        requested_project_id: object,
        duration: float,
        received_hooks: list[dict],
    ) -> None:
        opened_hooks["project_id"] = requested_project_id
        opened_hooks["duration"] = duration
        opened_hooks["hooks"] = received_hooks

    monkeypatch.setattr(script_area, "block_if_missing_api_keys_for_step", lambda _step: False)
    monkeypatch.setattr(script_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(script_area, "_latest", fake_latest)
    monkeypatch.setattr(script_area, "generate_story_hooks", fake_generate_story_hooks)
    monkeypatch.setattr(script_area, "_open_story_hooks_dialog", fake_open_hooks_dialog)

    await script_area._prepare_script_with_story_hooks(
        project_id,
        5,
        object(),
        fake_factory,
    )

    assert opened_dialogs and opened_dialogs[0][0] == "Criando ganchos para a história"
    assert opened_hooks["project_id"] == project_id
    assert opened_hooks["duration"] == 5.0
    assert opened_hooks["hooks"] == hooks


@pytest.mark.asyncio
async def test_prepare_script_with_story_hooks_falls_back_when_idea_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    captured: dict[str, Any] = {}
    generated_hooks_calls: list[bool] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_latest(session: object, model: object, requested_project_id: object) -> object:
        return None

    async def fake_generate_story_hooks(*args: object, **kwargs: object) -> list[dict]:
        generated_hooks_calls.append(True)
        return []

    async def fake_enqueue_project_step(
        session: object,
        requested_project_id: object,
        step: str,
    ) -> None:
        captured["project_id"] = requested_project_id
        captured["step"] = step

    def fake_factory(title: str, message: str) -> Any:
        return SimpleNamespace(open=lambda: None)

    monkeypatch.setattr(script_area, "block_if_missing_api_keys_for_step", lambda _step: False)
    monkeypatch.setattr(script_area, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(script_area, "_latest", fake_latest)
    monkeypatch.setattr(script_area, "generate_story_hooks", fake_generate_story_hooks)
    monkeypatch.setattr(
        script_area,
        "enqueue_project_step",
        fake_enqueue_project_step,
    )
    monkeypatch.setattr(script_area.ui, "notify", lambda *args, **kwargs: None)
    monkeypatch.setattr(script_area.ui.navigate, "reload", lambda: None)

    await script_area._prepare_script_with_story_hooks(
        project_id,
        5,
        object(),
        fake_factory,
    )

    assert generated_hooks_calls == []
    assert captured == {
        "project_id": project_id,
        "step": "ideas",
    }
