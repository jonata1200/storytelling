"""Testes do sync de título do roteiro para o projeto no worker de jobs.

O fluxo "Gerar roteiro" da workspace enfileira um job (ProjectStep.SCRIPT
ou ProjectStep.INITIAL_SCRIPT) que é executado pelo worker. Os workers
_run_initial_script e _run_script em app/jobs/runner.py chamam
generate_script sem sincronizar o título do roteiro de volta para o
projeto. Isso é o bug que faz o nome do roteiro não aparecer no nome do
projeto na dashboard.
"""

# ruff: noqa: F401, I001

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.jobs import runner as jobs_runner


@pytest.mark.asyncio
async def test_run_script_worker_syncs_project_title_from_generated_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O worker _run_script deve chamar sync_project_title com o título do
    roteiro retornado por generate_script, para que o nome do projeto
    fique igual ao nome que a IA deu ao roteiro."""

    project_id = uuid4()
    captured_titles: list[str] = []
    script_title = "O Eco do Silêncio Lunar"

    fake_script = SimpleNamespace(
        id=uuid4(),
        title=script_title,
        content="FADE IN:\n...",
    )

    async def fake_generate_script(
        session: Any,
        pid: Any,
        idea_id: Any,
        *args: Any,
        **kwargs: Any,
    ) -> SimpleNamespace:
        return fake_script

    async def fake_sync_project_title(
        session: Any,
        pid: Any,
        title: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        captured_titles.append(title)

    class FakeIdea:
        id = uuid4()
        title = "Nova história"

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def fake_latest(session: Any, model: Any, pid: Any) -> FakeIdea:
        return FakeIdea()

    async def fake_apply_target_duration(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(jobs_runner, "generate_script", fake_generate_script)
    monkeypatch.setattr(jobs_runner, "sync_project_title", fake_sync_project_title)
    monkeypatch.setattr(jobs_runner, "_latest", fake_latest)
    monkeypatch.setattr(
        jobs_runner, "_apply_target_duration_to_briefing", fake_apply_target_duration
    )

    result = await jobs_runner._run_script(  # type: ignore[arg-type]
        FakeSession(), project_id, {"target_duration_minutes": 5}
    )

    assert script_title in captured_titles, (
        "o worker _run_script deve chamar sync_project_title com o título do "
        "roteiro retornado por generate_script."
    )
    assert result["script_id"] == str(fake_script.id)


@pytest.mark.asyncio
async def test_run_initial_script_worker_syncs_project_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O worker _run_initial_script (quando source_idea está presente)
    também precisa sincronizar o título do roteiro."""

    project_id = uuid4()
    captured_titles: list[str] = []
    script_title = "O Astronauta Perdido"

    fake_script = SimpleNamespace(
        id=uuid4(),
        title=script_title,
        content="FADE IN:\n...",
    )

    async def fake_generate_script(
        session: Any,
        pid: Any,
        idea_id: Any,
        *args: Any,
        **kwargs: Any,
    ) -> SimpleNamespace:
        return fake_script

    async def fake_create_story_idea_from_payload(
        session: Any, pid: Any, payload: Any
    ) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), title="Nova história")

    async def fake_sync_project_title(
        session: Any,
        pid: Any,
        title: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        captured_titles.append(title)

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def fake_apply_target_duration(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(jobs_runner, "generate_script", fake_generate_script)
    monkeypatch.setattr(
        jobs_runner, "create_story_idea_from_payload", fake_create_story_idea_from_payload
    )
    monkeypatch.setattr(jobs_runner, "sync_project_title", fake_sync_project_title)
    monkeypatch.setattr(
        jobs_runner, "_apply_target_duration_to_briefing", fake_apply_target_duration
    )

    source_idea = {"title": "Nova história", "premise": "..."}

    result = await jobs_runner._run_initial_script(  # type: ignore[arg-type]
        FakeSession(), project_id, {"source_idea": source_idea}
    )

    assert script_title in captured_titles
    assert result["script_id"] == str(fake_script.id)