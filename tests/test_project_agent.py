from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation import project_agent
from app.generation.project_agent import (
    ProjectChatResult,
    classify_project_chat_action,
    handle_project_chat,
)


def test_project_chat_action_classifier_routes_creation_requests() -> None:
    assert classify_project_chat_action("crie os personagens principais", "script") == (
        "generate_assets"
    )
    assert classify_project_chat_action("gere o storyboard completo", "script") == (
        "generate_storyboard"
    )
    assert classify_project_chat_action("gerar os clipes de video", "storyboard") == (
        "generate_video"
    )
    assert classify_project_chat_action("melhore o gancho do roteiro", "script") == (
        "revise_script"
    )
    assert classify_project_chat_action("ajuste o ritmo e a camera", "video") == (
        "generate_video"
    )
    assert classify_project_chat_action("faca o video final", "video") == (
        "generate_video"
    )
    assert classify_project_chat_action("mude os enquadramentos", "storyboard") == (
        "generate_storyboard"
    )
    assert classify_project_chat_action("crie a Story Bible", "bible") == (
        "generate_story_bible"
    )
    assert classify_project_chat_action("gere ideias novas", "bible") == "generate_ideas"
    assert classify_project_chat_action("exportar a timeline final", "video") == (
        "generate_finalization"
    )
    assert classify_project_chat_action("rode o controle de qualidade", "video") == (
        "run_quality"
    )


@pytest.mark.asyncio
async def test_project_chat_can_revise_script(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"project": {"title": "Teste"}}

    async def fake_ensure_script(
        session: AsyncSession, requested_project_id: Any, progress: Any = None
    ) -> tuple[SimpleNamespace, str, bool]:
        calls.append("ensure_script")
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id), "pronto", False

    async def fake_revise_script(*args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append("revise")
        assert args[1] == project_id
        assert args[2] == script_id
        assert "melhore" in args[3]
        return SimpleNamespace(id=script_id)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)
    monkeypatch.setattr(project_agent, "revise_script", fake_revise_script)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "melhore o gancho do roteiro",
        [],
    )

    assert result == ProjectChatResult(
        "Roteiro revisado e nova versao salva no projeto.",
        "revise_script",
        True,
    )
    assert calls == ["ensure_script", "revise"]


@pytest.mark.asyncio
async def test_project_chat_routes_assets_storyboard_and_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_assets(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("assets")
        assert requested_project_id == project_id
        assert force is False
        return ProjectChatResult("assets ok", "generate_assets", True)

    async def fake_storyboard(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("storyboard")
        assert requested_project_id == project_id
        assert force is False
        return ProjectChatResult("storyboard ok", "generate_storyboard", True)

    async def fake_video(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("video")
        assert requested_project_id == project_id
        assert force is False
        return ProjectChatResult("video ok", "generate_video", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_visual_pipeline", fake_assets)
    monkeypatch.setattr(project_agent, "_ensure_storyboard_pipeline", fake_storyboard)
    monkeypatch.setattr(project_agent, "_ensure_video_pipeline", fake_video)

    assets = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "script", "crie os personagens", []
    )
    storyboard = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "script", "gere storyboard", []
    )
    video = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "storyboard", "gerar video", []
    )

    assert assets.action == "generate_assets"
    assert storyboard.action == "generate_storyboard"
    assert video.action == "generate_video"
    assert calls == ["assets", "storyboard", "video"]


@pytest.mark.asyncio
async def test_project_chat_routes_story_bible_finalization_and_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_story_bible(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> SimpleNamespace:
        calls.append("bible")
        assert requested_project_id == project_id
        return SimpleNamespace(message="bible ok", changed=True)

    async def fake_finalization(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("finalization")
        assert requested_project_id == project_id
        return ProjectChatResult("final ok", "generate_finalization", True)

    async def fake_quality(
        session: AsyncSession,
        requested_project_id: Any,
    ) -> ProjectChatResult:
        calls.append("quality")
        assert requested_project_id == project_id
        return ProjectChatResult("quality ok", "run_quality", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_story_bible_pipeline", fake_story_bible)
    monkeypatch.setattr(project_agent, "_ensure_finalization_pipeline", fake_finalization)
    monkeypatch.setattr(project_agent, "_ensure_quality_pipeline", fake_quality)

    bible = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "bible", "crie a Story Bible", []
    )
    finalization = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "video", "exportar timeline final", []
    )
    quality = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "video", "rode o controle de qualidade", []
    )

    assert bible.action == "generate_story_bible"
    assert finalization.action == "generate_finalization"
    assert quality.action == "run_quality"
    assert calls == ["bible", "finalization", "quality"]


@pytest.mark.asyncio
async def test_project_chat_forces_regeneration_for_visual_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    captured_force: list[bool] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_assets(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        captured_force.append(force)
        return ProjectChatResult("assets revisados", "generate_assets", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_visual_pipeline", fake_assets)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "assets",
        "refaça os personagens com um visual mais dramático",
        [],
    )

    assert result.action == "generate_assets"
    assert captured_force == [True]


@pytest.mark.asyncio
async def test_project_chat_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    progress_messages: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_ensure_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        if progress is not None:
            await progress("Vou escrever o roteiro.")
        return SimpleNamespace(id=uuid4()), "Roteiro criado.", True

    async def collect_progress(message: str) -> None:
        progress_messages.append(message)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "gere o roteiro",
        [],
        progress=collect_progress,
    )

    assert result == ProjectChatResult("Roteiro criado.", "generate_script", True)
    assert progress_messages == ["Criando roteiro.", "Vou escrever o roteiro."]
