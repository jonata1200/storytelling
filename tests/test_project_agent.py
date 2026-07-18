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


@pytest.mark.asyncio
async def test_project_chat_can_revise_script(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"project": {"title": "Teste"}}

    async def fake_ensure_script(
        session: AsyncSession, requested_project_id: Any
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
        session: AsyncSession, requested_project_id: Any, force: bool = False
    ) -> ProjectChatResult:
        calls.append("assets")
        assert requested_project_id == project_id
        assert force is False
        return ProjectChatResult("assets ok", "generate_assets", True)

    async def fake_storyboard(
        session: AsyncSession, requested_project_id: Any, force: bool = False
    ) -> ProjectChatResult:
        calls.append("storyboard")
        assert requested_project_id == project_id
        assert force is False
        return ProjectChatResult("storyboard ok", "generate_storyboard", True)

    async def fake_video(
        session: AsyncSession, requested_project_id: Any, force: bool = False
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
async def test_project_chat_forces_regeneration_for_visual_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    captured_force: list[bool] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_assets(
        session: AsyncSession, requested_project_id: Any, force: bool = False
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
