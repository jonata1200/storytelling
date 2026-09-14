"""Teste do comportamento de generate_script em projetos com título travado.

Para projetos vindos do laboratório de ideias (title_locked=True), o roteiro
deve usar o título da ideia como `script.title`, mesmo que a IA devolva um
título próprio. Para projetos da dashboard (title_locked=False), o roteiro
usa o título que a IA inventar.
"""

# ruff: noqa: F401, I001

from typing import Any
from uuid import uuid4

import pytest

from app.projects import service as project_service
from app.storytelling import service as storytelling_service
from app.storytelling.models import StoryIdea


def _make_fake_session() -> Any:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, item: Any) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def refresh(self, _item: Any) -> None:
            pass

        async def get(self, model: Any, requested_id: Any) -> Any:
            assert model is StoryIdea
            return idea

    return FakeSession()


def _setup_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm_title: str,
    idea_title: str,
    is_locked: bool,
    project_id: Any,
    idea_id: Any,
) -> Any:
    global idea
    idea = type(  # noqa: F841
        "Idea",
        (),
        {
            "id": idea_id,
            "project_id": project_id,
            "artifact_id": uuid4(),
            "title": idea_title,
            "payload": {"title": idea_title},
        },
    )()

    project_obj = type(  # noqa: F841
        "Project",
        (),
        {"id": project_id, "deleted_at": None},
    )()

    class FakeProjectRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_project(self, requested_project_id: Any) -> Any:
            assert requested_project_id == project_id
            return project_obj

    briefing = type("Briefing", (), {"desired_duration_minutes": 5, "language": "pt-BR"})()

    async def fake_latest_briefing(session: Any, requested_project_id: Any) -> Any:
        return briefing

    async def fake_provider_for_task(session: Any, requested_project_id: Any, task: str) -> tuple[Any, str]:
        return (object(), "fake-model")

    async def fake_run_structured_generation(*_args: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return (
            type(
                "R",
                (),
                {
                    "content": {
                        "title": llm_title,
                        "language": "pt-BR",
                        "target_duration_seconds": 300,
                        "word_count": 650,
                        "content": (
                        "FADE IN:\n\n"
                        "CENA 01 - INT. CASA - DIA\n\n"
                        "O PERSONAGEM caminha pela sala ensolarada, olhando pela janela.\n\n"
                        "PERSONAGEM\n(sussurrando)\nO tempo está se esgotando.\n\n"
                        "Ele pega a fotografia empoeirada e a limpa com um pano.\n\n"
                        "PERSONAGEM\nCada gesto remove uma camada.\n\n"
                        "A imagem revela um astronauta perdido na lua.\n\n"
                        "FADE OUT.\n"
                    ),
                    }
                },
            )(),
            type("E", (), {})(),
        )

    async def fake_locked(_session: Any, _pid: Any) -> bool:
        return is_locked

    monkeypatch.setattr(storytelling_service, "ProjectRepository", FakeProjectRepository)
    monkeypatch.setattr(storytelling_service, "get_latest_briefing", fake_latest_briefing)
    monkeypatch.setattr(
        storytelling_service, "llm_provider_for_task", fake_provider_for_task
    )
    monkeypatch.setattr(
        storytelling_service, "run_structured_generation", fake_run_structured_generation
    )
    monkeypatch.setattr(storytelling_service, "_idea_script_contract", lambda *_a, **_k: {})
    monkeypatch.setattr(
        storytelling_service,
        "expected_script_scene_count",
        lambda *_a, **_k: 5,
    )
    monkeypatch.setattr(
        storytelling_service,
        "_script_scene_count_guidance",
        lambda *_a, **_k: "",
    )
    monkeypatch.setattr(
        storytelling_service,
        "coerce_script_duration_minutes",
        lambda x: float(x) if x is not None else 5.0,
    )
    monkeypatch.setattr(project_service, "_project_title_is_locked", fake_locked)

    class FakeScript:
        def __init__(self, **kwargs: Any) -> None:
            self.id = uuid4()
            self.__dict__.update(kwargs)

    monkeypatch.setattr(storytelling_service, "Script", FakeScript)

    # Capturar o título passado ao Script via session.add.
    captured: dict[str, Any] = {}

    class FakeArtifact:
        id = uuid4()

    async def fake_create_artifact(*_args: Any, **_kwargs: Any) -> FakeArtifact:
        return FakeArtifact()

    async def fake_add_dependency(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_create_artifact_version(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(storytelling_service, "_create_artifact", fake_create_artifact)
    monkeypatch.setattr(storytelling_service, "_add_dependency", fake_add_dependency)
    monkeypatch.setattr(
        storytelling_service, "create_artifact_version", fake_create_artifact_version
    )
    monkeypatch.setattr(
        storytelling_service, "_advance_project_status_when_reachable", lambda *a, **k: None
    )

    return captured


@pytest.mark.asyncio
async def test_generate_script_uses_idea_title_when_project_is_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projeto com title_locked=True: o script.title gravado é o título da
    ideia, mesmo que o LLM devolva um título próprio."""

    project_id = uuid4()
    idea_id = uuid4()
    idea_title = "O Peso do Oxigênio"
    llm_title = "O Último Sopro"

    fake_session = _make_fake_session()
    _setup_mocks(
        monkeypatch,
        llm_title=llm_title,
        idea_title=idea_title,
        is_locked=True,
        project_id=project_id,
        idea_id=idea_id,
    )

    script = await storytelling_service.generate_script(
        fake_session, project_id, idea_id  # type: ignore[arg-type]
    )

    assert script is not None
    assert script.title == idea_title, (
        f"projeto com title_locked=True deve usar o título da ideia "
        f"('{idea_title}'), mas o roteiro gravou '{script.title}' "
        f"(o LLM devolveu '{llm_title}')."
    )


@pytest.mark.asyncio
async def test_generate_script_uses_llm_title_when_project_is_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projeto com title_locked=False: o script.title gravado é o título que
    a IA devolveu (comportamento atual — dashboard)."""

    project_id = uuid4()
    idea_id = uuid4()
    idea_title = "Nova história"
    llm_title = "O Eco do Silêncio Lunar"

    fake_session = _make_fake_session()
    _setup_mocks(
        monkeypatch,
        llm_title=llm_title,
        idea_title=idea_title,
        is_locked=False,
        project_id=project_id,
        idea_id=idea_id,
    )

    script = await storytelling_service.generate_script(
        fake_session, project_id, idea_id  # type: ignore[arg-type]
    )

    assert script is not None
    assert script.title == llm_title, (
        f"projeto com title_locked=False deve usar o título da IA "
        f"('{llm_title}'), mas o roteiro gravou '{script.title}'."
    )