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
    assert classify_project_chat_action(
        "Agora que o roteiro foi criado pode partir para a criacao dos personagens, "
        "locais e objetos da historia",
        "assets",
    ) == "generate_assets"
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
    assert classify_project_chat_action("crie a Story Bible", "script") == (
        "generate_script"
    )
    assert classify_project_chat_action("gere ideias novas", "script") == "generate_ideas"
    assert classify_project_chat_action("exportar a timeline final", "video") == (
        "generate_finalization"
    )
    assert classify_project_chat_action("rode o controle de qualidade", "video") == (
        "run_quality"
    )
    assert classify_project_chat_action("aprove o prompt da Clara para gerar imagem", "assets") == (
        "approve_visual_prompt"
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
async def test_project_chat_uses_project_state_for_progression_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {
            "found": True,
            "counts": {
                "scripts": 1,
                "scenes": 5,
                "shots": 20,
                "characters": 0,
                "locations": 0,
                "props": 0,
                "frames": 0,
                "clips": 0,
            },
        }

    async def fake_assets(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("assets")
        assert requested_project_id == project_id
        return ProjectChatResult("assets ok", "generate_assets", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_visual_pipeline", fake_assets)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "pode avançar para a próxima etapa",
        [],
    )

    assert result.action == "generate_assets"
    assert calls == ["assets"]


@pytest.mark.asyncio
async def test_visual_pipeline_creates_prompts_without_auto_generating_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    progress_messages: list[str] = []

    async def fake_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id), "script ok", False

    async def fake_count(session: AsyncSession, model: type[Any], requested_project_id: Any) -> int:
        assert requested_project_id == project_id
        return 0

    async def fake_visual_bible(
        session: AsyncSession,
        requested_project_id: Any,
        requested_script_id: Any,
    ) -> tuple[list[SimpleNamespace], list[SimpleNamespace], list[SimpleNamespace]]:
        assert requested_project_id == project_id
        assert requested_script_id == script_id
        return (
            [SimpleNamespace(id=uuid4())],
            [SimpleNamespace(id=uuid4())],
            [SimpleNamespace(id=uuid4())],
        )

    async def fail_auto_approval(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("visual pipeline should not auto-generate images")

    async def collect_progress(message: str) -> None:
        progress_messages.append(message)

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "_count", fake_count)
    monkeypatch.setattr(project_agent, "generate_visual_bible", fake_visual_bible)
    monkeypatch.setattr(
        project_agent,
        "approve_visual_target_and_generate_views",
        fail_auto_approval,
    )

    result = await project_agent._ensure_visual_pipeline(
        cast(AsyncSession, object()),
        project_id,
        progress=collect_progress,
    )

    assert result.action == "generate_assets"
    assert result.changed is True
    assert "Revise e aprove os prompts" in result.message
    assert any("Prompts visuais criados" in message for message in progress_messages)


@pytest.mark.asyncio
async def test_storyboard_pipeline_requires_complete_visual_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()

    async def fake_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id), "script ok", False

    async def fake_visual_report(
        session: AsyncSession,
        requested_project_id: Any,
    ) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {
            "complete": False,
            "missing_categories": [],
            "missing_views": 3,
        }

    async def fail_storyboard_generation(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("storyboard não deve ser gerado antes das imagens visuais")

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(project_agent, "generate_storyboard_frames", fail_storyboard_generation)

    result = await project_agent._ensure_storyboard_pipeline(
        cast(AsyncSession, object()),
        project_id,
    )

    assert result.action == "generate_storyboard"
    assert result.changed is False
    assert "Biblioteca Visual" in result.message
    assert "referência" in result.message


@pytest.mark.asyncio
async def test_video_pipeline_stops_when_visual_references_block_storyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    async def fake_storyboard(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        assert requested_project_id == project_id
        return ProjectChatResult(
            "Conclua a Biblioteca Visual antes do storyboard. "
            "Ainda falta gerar 2 referência(s) visual(is).",
            "generate_storyboard",
            False,
        )

    async def fail_latest_many(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("video nao deve consultar frames quando o storyboard esta bloqueado")

    monkeypatch.setattr(project_agent, "_ensure_storyboard_pipeline", fake_storyboard)
    monkeypatch.setattr(project_agent, "_latest_many", fail_latest_many)

    result = await project_agent._ensure_video_pipeline(
        cast(AsyncSession, object()),
        project_id,
    )

    assert result.action == "generate_video"
    assert result.changed is False
    assert "Biblioteca Visual" in result.message


@pytest.mark.asyncio
async def test_project_chat_routes_script_finalization_and_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        calls.append("script")
        assert requested_project_id == project_id
        return SimpleNamespace(id=uuid4()), "script ok", True

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
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "_ensure_finalization_pipeline", fake_finalization)
    monkeypatch.setattr(project_agent, "_ensure_quality_pipeline", fake_quality)

    script = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "script", "crie o roteiro", []
    )
    finalization = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "video", "exportar timeline final", []
    )
    quality = await handle_project_chat(
        cast(AsyncSession, object()), project_id, "video", "rode o controle de qualidade", []
    )

    assert script.action == "generate_script"
    assert finalization.action == "generate_finalization"
    assert quality.action == "run_quality"
    assert calls == ["script", "finalization", "quality"]


@pytest.mark.asyncio
async def test_project_chat_routes_visual_prompt_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_approve_visual_prompt(
        session: AsyncSession,
        requested_project_id: Any,
        message: str,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append(message)
        assert requested_project_id == project_id
        return ProjectChatResult("aprovado", "approve_visual_prompt", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(
        project_agent,
        "_approve_visual_prompt_from_chat",
        fake_approve_visual_prompt,
    )

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "assets",
        "aprove o prompt da Clara para gerar imagem",
        [],
    )

    assert result == ProjectChatResult("aprovado", "approve_visual_prompt", True)
    assert calls == ["aprove o prompt da Clara para gerar imagem"]


@pytest.mark.asyncio
async def test_visual_prompt_approval_matches_target_name_and_generates_initial_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    target_id = uuid4()
    target = project_agent.VisualChatTarget("character", target_id, "Clara")
    captured: dict[str, Any] = {}

    async def fake_targets(
        session: AsyncSession,
        requested_project_id: Any,
        target_kind: str | None = None,
    ) -> list[Any]:
        assert requested_project_id == project_id
        assert target_kind == "character"
        return [target]

    async def fake_views(
        session: AsyncSession,
        requested_project_id: Any,
        requested_target: Any,
    ) -> set[str]:
        assert requested_project_id == project_id
        assert requested_target == target
        return set()

    async def fake_approve(*args: Any, **kwargs: Any) -> list[object]:
        captured["args"] = args
        return [object()]

    monkeypatch.setattr(project_agent, "_visual_chat_targets", fake_targets)
    monkeypatch.setattr(project_agent, "_visual_reference_views_for_target", fake_views)
    monkeypatch.setattr(project_agent, "approve_visual_target_and_generate_views", fake_approve)

    result = await project_agent._approve_visual_prompt_from_chat(
        cast(AsyncSession, object()),
        project_id,
        "aprove o prompt do personagem Clara para criar imagem",
    )

    assert result == ProjectChatResult(
        "Aprovei 1 ativo(s) visual(is) e criei 1 imagem(ns).",
        "approve_visual_prompt",
        True,
    )
    assert captured["args"][1:] == (project_id, "character", target_id, ["front_portrait"])


@pytest.mark.asyncio
async def test_visual_prompt_approval_asks_for_target_when_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    targets = [
        project_agent.VisualChatTarget("character", uuid4(), "Clara"),
        project_agent.VisualChatTarget("character", uuid4(), "Marta"),
    ]

    async def fake_targets(*args: Any, **kwargs: Any) -> list[Any]:
        return targets

    monkeypatch.setattr(project_agent, "_visual_chat_targets", fake_targets)

    result = await project_agent._approve_visual_prompt_from_chat(
        cast(AsyncSession, object()),
        project_id,
        "aprove o prompt do personagem",
    )

    assert result.action == "approve_visual_prompt"
    assert result.changed is False
    assert "Clara, Marta" in result.message


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
