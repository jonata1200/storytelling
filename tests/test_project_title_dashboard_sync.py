"""Testes do sync de título projeto → roteiro no fluxo da dashboard.

Quando o usuário cria um projeto pela rota /dashboard, o título inicial é
um placeholder ("Nova história"). Depois que a IA gera o roteiro, o título
do projeto deve ser sincronizado com o título do roteiro — a menos que o
projeto esteja com title_locked=True (criado via ideia do laboratório,
onde o nome é fixado pelo usuário/IA da ideia).

Escopo: somente o caminho da dashboard. Projetos do laboratório de ideias
mantêm o lock atual e não são renomeados pelo roteiro.
"""

# ruff: noqa: F401, I001

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.ui import pages
from app.ui.project import workflows


@pytest.mark.asyncio
async def test_dashboard_project_title_is_synced_from_generated_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projeto da dashboard (title_locked=False) → após generate_script
    retornar um título da IA, o nome do projeto passa a ser esse título.
    """
    project_id = uuid4()
    captured_titles: list[str] = []
    script_title = "O Trem das Seis"

    async def fake_sync_project_title(
        session: Any,
        requested_project_id: Any,
        title: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        captured_titles.append(title)

    # `script.title` precisa ser o que o LLM devolveu no payload.
    fake_script = SimpleNamespace(
        id=uuid4(),
        title=script_title,
        content="FADE IN:\n...",
    )

    async def fake_generate_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return fake_script

    async def fake_create_story_idea_from_payload(
        *args: Any, **kwargs: Any
    ) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), title="Nova história")

    monkeypatch.setattr(workflows, "sync_project_title", fake_sync_project_title)
    monkeypatch.setattr(workflows, "generate_script", fake_generate_script)
    monkeypatch.setattr(
        workflows, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )

    source_idea = {
        "title": "Nova história",
        "premise": "Uma fotografia muda cada vez que é limpa",
        "genre": "drama emocional",
        "primary_emotion": "curiosidade",
        "protagonist": "Personagem principal",
        "hook": "...",
        "duration_minutes": 5.0,
    }

    # _generate_initial_script usa a sessão para o sync (sync_project_title é
    # chamado de dentro do mesmo session). Aceitamos qualquer session fake
    # porque o fake_sync_project_title não toca nela.
    session = SimpleNamespace()
    await workflows._generate_initial_script(  # type: ignore[arg-type]
        session, project_id, source_idea
    )

    assert script_title in captured_titles, (
        "o sync do título do roteiro para o projeto deve ser chamado após "
        "generate_script (sync_project_title não recebeu o título da IA)."
    )


@pytest.mark.asyncio
async def test_lab_idea_project_title_is_not_overwritten_by_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projeto criado via /ideas (title_locked=True) → o service
    sync_project_title respeita o lock e NÃO sobrescreve o título.
    """
    from app.projects import service as project_service

    project_id = uuid4()

    class FakeProject:
        id = project_id
        title = "O Trem das Seis"  # título fixado pelo laboratório
        description = ""
        deleted_at = None
        current_version = 0

    project = FakeProject()

    async def fake_get(*args: Any, **kwargs: Any) -> FakeProject:
        return project

    session = SimpleNamespace(
        get=fake_get,
        add=lambda _obj: None,
        commit=lambda: None,
        refresh=lambda _obj: None,
    )

    async def fake_locked(_session: Any, _pid: Any) -> bool:
        return True  # projeto travado

    monkeypatch.setattr(project_service, "_project_title_is_locked", fake_locked)

    result = await project_service.sync_project_title(  # type: ignore[arg-type]
        session, project_id, "Qualquer outro nome"
    )

    # sync_project_title retorna o project mas NÃO altera o título.
    assert result is project
    assert project.title == "O Trem das Seis", (
        "o título do projeto do laboratório não pode ser sobrescrito pelo "
        "título do roteiro (title_locked=True)."
    )


@pytest.mark.asyncio
async def test_dashboard_creation_uses_placeholder_title_until_script_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirma o comportamento B1: o projeto nasce com placeholder
    'Nova história' e só é renomeado depois que o roteiro fica pronto."""
    captured: dict[str, Any] = {}

    async def fake_create_project_from_form(
        form: dict[str, Any],
        *,
        generate_initial_script: bool = False,
        generate_initial_idea: bool = False,
        source_idea: dict[str, Any] | None = None,
    ) -> None:
        captured["form"] = form
        captured["source_idea"] = source_idea

    monkeypatch.setattr(pages, "_create_project_from_form", fake_create_project_from_form)
    monkeypatch.setattr(pages, "get_settings", lambda: SimpleNamespace())

    await pages._create_project_from_chat_prompt(
        "Uma fotografia muda cada vez que é limpa"
    )

    # O título do projeto E da source_idea continuam como placeholder.
    assert captured["form"]["title"] == "Nova história"
    assert captured["source_idea"]["title"] == "Nova história"
    # generate_initial_script=False garante que a IA não é chamada antes do
    # redirect (decisão B1).
    assert captured.get("generate_initial_script", False) is False