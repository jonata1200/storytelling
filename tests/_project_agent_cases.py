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
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMRequest


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
    assert classify_project_chat_action("gere o storyboard da cena 1", "storyboard") == (
        "generate_storyboard"
    )
    assert classify_project_chat_action("gerar os clipes de video", "storyboard") == (
        "generate_video"
    )
    assert classify_project_chat_action("gerar dublagem em inglês", "video") == (
        "generate_dubbing"
    )
    assert classify_project_chat_action("melhore o gancho do roteiro", "script") == (
        "revise_script"
    )
    assert classify_project_chat_action("edite o roteiro para ficar mais emocional", "script") == (
        "revise_script"
    )
    assert classify_project_chat_action("corrija a cena 2 do roteiro", "script") == (
        "revise_script"
    )
    assert classify_project_chat_action("gere novamente o roteiro completo", "script") == (
        "generate_script"
    )
    assert classify_project_chat_action("reescreva somente a cena 3", "script") == (
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
    assert classify_project_chat_action(
        "pode aprovar os prompts pendentes para geração dos storyboards",
        "storyboard",
    ) == "approve_storyboard_prompt"
    assert classify_project_chat_action("aprove os prompts de vídeo", "video") == (
        "generate_video"
    )


@pytest.mark.asyncio
async def test_mock_director_agent_uses_section_and_project_context() -> None:
    result = await MockLLMProvider().generate_structured(
        LLMRequest(
            task="director_agent_chat",
            prompt="Ajude com o storyboard",
            variables={
                "section": "storyboard",
                "message": "Crie uma segunda versão",
                "project_context": {"summary": "1 roteiro e 8 quadros"},
            },
        )
    )

    assert "storyboard" in result.content["message"]
    assert "1 roteiro e 8 quadros" in result.content["message"]


def test_project_chat_extracts_storyboard_scene_number() -> None:
    assert project_agent._requested_storyboard_scene_number("gere storyboard da cena 1") == 1
    assert project_agent._requested_storyboard_scene_number("crie frames da cena 02") == 2
    assert project_agent._requested_storyboard_scene_number("gere storyboard completo") is None


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
        assert kwargs["mark_downstream_stale"] is False
        return SimpleNamespace(id=script_id)

    async def fake_mark_scene_plan_stale(*args: Any, **kwargs: Any) -> None:
        calls.append("mark_scene_plan_stale")
        assert args[1] == project_id
        assert args[2] == script_id

    async def fake_script_blockers(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_script_agent_edit_blockers", fake_script_blockers)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)
    monkeypatch.setattr(project_agent, "revise_script", fake_revise_script)
    monkeypatch.setattr(project_agent, "mark_scene_plan_stale", fake_mark_scene_plan_stale)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "melhore o gancho do roteiro",
        [],
    )

    assert result == ProjectChatResult(
        "Roteiro revisado.",
        "revise_script",
        True,
    )
    assert calls == [
        "ensure_script",
        "revise",
        "mark_scene_plan_stale",
    ]


@pytest.mark.asyncio
async def test_project_chat_can_revise_specific_script_scenes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert args[2] == script_id
        assert "cena 3" in args[3]
        assert kwargs["mark_downstream_stale"] is False
        return SimpleNamespace(id=script_id)

    async def fake_mark_scene_plan_stale(*args: Any, **kwargs: Any) -> None:
        calls.append("mark_scene_plan_stale")
        assert args[2] == script_id

    async def fake_script_blockers(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_script_agent_edit_blockers", fake_script_blockers)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)
    monkeypatch.setattr(project_agent, "revise_script", fake_revise_script)
    monkeypatch.setattr(project_agent, "mark_scene_plan_stale", fake_mark_scene_plan_stale)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "reescreva somente a cena 3 com mais tensão",
        [],
    )

    assert result == ProjectChatResult("Cena revisada.", "revise_script", True)
    assert calls == [
        "ensure_script",
        "revise",
        "mark_scene_plan_stale",
    ]


@pytest.mark.asyncio
async def test_project_chat_can_force_full_script_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    captured_force: list[bool] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"counts": {"scripts": 1, "scenes": 4, "shots": 12}}

    async def fake_ensure_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
        force: bool = False,
    ) -> tuple[SimpleNamespace, str, bool]:
        assert requested_project_id == project_id
        captured_force.append(force)
        return (
            SimpleNamespace(id=uuid4()),
            "Roteiro completo gerado novamente.",
            True,
        )

    async def fake_script_blockers(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_script_agent_edit_blockers", fake_script_blockers)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "gere novamente o roteiro completo",
        [],
    )

    assert result == ProjectChatResult(
        "Roteiro completo gerado novamente.",
        "generate_script",
        True,
    )
    assert captured_force == [True]


@pytest.mark.asyncio
async def test_project_chat_blocks_script_regeneration_after_visual_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"counts": {"scripts": 1, "characters": 1}}

    async def fake_count(session: AsyncSession, model: type[Any], requested_project_id: Any) -> int:
        assert requested_project_id == project_id
        return 1 if model is project_agent.Character else 0

    async def fail_ensure_script(*args: Any, **kwargs: Any) -> tuple[None, str, bool]:
        raise AssertionError("script should not be regenerated after visual stage")

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_count", fake_count)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fail_ensure_script)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "gere novamente o roteiro completo",
        [],
    )

    assert result.action == "generate_script"
    assert result.changed is False
    assert result.failed is True
    assert "Não posso alterar o roteiro pelo agente" in result.message


@pytest.mark.asyncio
async def test_project_chat_allows_script_revision_after_visual_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"counts": {"scripts": 1, "visual_refs": 1}}

    async def fake_count(session: AsyncSession, model: type[Any], requested_project_id: Any) -> int:
        assert requested_project_id == project_id
        return 1 if model is project_agent.VisualReference else 0

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
        assert "diálogos" in args[3]
        return SimpleNamespace(id=script_id)

    async def fake_mark_scene_plan_stale(*args: Any, **kwargs: Any) -> None:
        calls.append("mark_scene_plan_stale")
        assert args[1] == project_id
        assert args[2] == script_id

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_count", fake_count)
    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_ensure_script)
    monkeypatch.setattr(project_agent, "revise_script", fake_revise_script)
    monkeypatch.setattr(project_agent, "mark_scene_plan_stale", fake_mark_scene_plan_stale)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "script",
        "melhore os diálogos do roteiro",
        [],
    )

    assert result.action == "revise_script"
    assert result.failed is False
    assert result.changed is True
    assert "Roteiro revisado" in result.message
    assert calls == ["ensure_script", "revise", "mark_scene_plan_stale"]


@pytest.mark.asyncio
async def test_forced_script_pipeline_does_not_refresh_existing_visual_bible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    old_script_artifact_id = uuid4()
    idea_id = uuid4()
    new_script_id = uuid4()
    calls: list[str] = []
    progress_messages: list[str] = []

    async def fake_latest(
        session: AsyncSession, model: type[Any], requested_project_id: Any
    ) -> SimpleNamespace | None:
        assert requested_project_id == project_id
        if model is project_agent.Briefing:
            return SimpleNamespace(id=uuid4())
        if model is project_agent.Script:
            return SimpleNamespace(id=uuid4(), artifact_id=old_script_artifact_id)
        if model is project_agent.StoryIdea:
            return SimpleNamespace(id=idea_id)
        return None

    async def fake_mark_dependents_stale(
        session: AsyncSession, changed_artifact_ids: set[Any]
    ) -> set[Any]:
        calls.append("stale")
        assert changed_artifact_ids == {old_script_artifact_id}
        return set()

    async def fake_generate_script(
        session: AsyncSession,
        requested_project_id: Any,
        requested_idea_id: Any,
    ) -> SimpleNamespace:
        calls.append("script")
        assert requested_project_id == project_id
        assert requested_idea_id == idea_id
        return SimpleNamespace(id=new_script_id)

    async def collect_progress(message: str) -> None:
        progress_messages.append(message)

    monkeypatch.setattr(project_agent, "_latest", fake_latest)
    monkeypatch.setattr(project_agent, "mark_dependents_stale", fake_mark_dependents_stale)
    monkeypatch.setattr(project_agent, "generate_script", fake_generate_script)

    script, message, changed = await project_agent._ensure_script_pipeline(
        cast(AsyncSession, object()),
        project_id,
        progress=collect_progress,
        force=True,
    )

    assert script is not None
    assert script.id == new_script_id
    assert changed is True
    assert message == (
        "Roteiro completo gerado novamente. Cenas e planos serão recriados "
        "quando você abrir ou solicitar o Storyboard."
    )
    assert calls == ["stale", "script"]
    assert not any("Biblioteca visual atualizada" in item for item in progress_messages)


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
        reset_existing: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("assets")
        assert requested_project_id == project_id
        assert force is False
        assert reset_existing is False
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
async def test_project_chat_routes_storyboard_scene_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    requested_scene_numbers: list[int | None] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {
            "found": True,
            "counts": {
                "scripts": 1,
                "scenes": 3,
                "shots": 9,
                "characters": 2,
                "locations": 2,
                "props": 2,
                "frames": 0,
                "clips": 0,
            },
        }

    async def fake_storyboard(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
        scene_number: int | None = None,
    ) -> ProjectChatResult:
        assert requested_project_id == project_id
        assert force is False
        requested_scene_numbers.append(scene_number)
        return ProjectChatResult("storyboard parcial ok", "generate_storyboard", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_storyboard_pipeline", fake_storyboard)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "storyboard",
        "gere o storyboard da cena 1",
        [],
    )

    assert result.action == "generate_storyboard"
    assert requested_scene_numbers == [1]


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
        reset_existing: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("assets")
        assert requested_project_id == project_id
        assert reset_existing is False
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
async def test_storyboard_pipeline_requires_prompt_approval(
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

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_frames_need_generation(*args: Any, **kwargs: Any) -> bool:
        return True

    async def fake_prompts_need_approval(*args: Any, **kwargs: Any) -> bool:
        return True

    async def fake_scene_plan(*args: Any, **kwargs: Any) -> bool:
        return False

    async def fail_storyboard_generation(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("storyboard não deve ser gerado antes da aprovação")

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(project_agent, "_ensure_storyboard_scene_plan", fake_scene_plan)
    monkeypatch.setattr(
        project_agent,
        "storyboard_frames_need_generation",
        fake_frames_need_generation,
    )
    monkeypatch.setattr(
        project_agent,
        "storyboard_prompts_need_approval",
        fake_prompts_need_approval,
    )
    monkeypatch.setattr(project_agent, "generate_storyboard_frames", fail_storyboard_generation)

    result = await project_agent._ensure_storyboard_pipeline(
        cast(AsyncSession, object()),
        project_id,
    )

    assert result.action == "generate_storyboard"
    assert result.changed is False
    assert "prompts de storyboard" in result.message
    assert "aprovados" in result.message


@pytest.mark.asyncio
async def test_storyboard_pipeline_force_regenerates_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    requested_force_values: list[bool] = []

    async def fake_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id), "script ok", False

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_prompts_need_approval(*args: Any, **kwargs: Any) -> bool:
        return False

    async def fake_scene_plan(*args: Any, **kwargs: Any) -> bool:
        return False

    async def fake_generate_storyboard_frames(
        session: AsyncSession,
        requested_project_id: Any,
        requested_script_id: Any,
        scene_number: int | None = None,
        force: bool = False,
        progress_callback: Any = None,
    ) -> list[SimpleNamespace]:
        assert requested_project_id == project_id
        assert requested_script_id == script_id
        requested_force_values.append(force)
        return [SimpleNamespace(id=uuid4())]

    async def fake_count(*args: Any, **kwargs: Any) -> int:
        return 1

    async def fake_animatic_bundle(*args: Any, **kwargs: Any) -> object:
        return object()

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(
        project_agent,
        "storyboard_prompts_need_approval",
        fake_prompts_need_approval,
    )
    monkeypatch.setattr(project_agent, "_ensure_storyboard_scene_plan", fake_scene_plan)
    monkeypatch.setattr(
        project_agent,
        "generate_storyboard_frames",
        fake_generate_storyboard_frames,
    )
    monkeypatch.setattr(project_agent, "generate_animatic_bundle", fake_animatic_bundle)
    monkeypatch.setattr(project_agent, "_count", fake_count)

    result = await project_agent._ensure_storyboard_pipeline(
        cast(AsyncSession, object()),
        project_id,
        force=True,
    )

    assert result.action == "generate_storyboard"
    assert requested_force_values == [True]


@pytest.mark.asyncio
async def test_storyboard_pipeline_reports_frame_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    progress_events: list[Any] = []

    async def fake_script(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
    ) -> tuple[SimpleNamespace, str, bool]:
        assert requested_project_id == project_id
        return SimpleNamespace(id=script_id), "script ok", False

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_prompts_need_approval(*args: Any, **kwargs: Any) -> bool:
        return False

    async def fake_frames_need_generation(*args: Any, **kwargs: Any) -> bool:
        return True

    async def fake_scene_plan(*args: Any, **kwargs: Any) -> bool:
        return False

    async def fake_generate_storyboard_frames(
        *args: Any,
        progress_callback: Any = None,
        **kwargs: Any,
    ) -> list[SimpleNamespace]:
        assert progress_callback is not None
        await progress_callback(1, 4, "Agora: gerando Cena 01 - Plano 01 - Quadro 001.")
        await progress_callback(4, 4, "Agora: finalizando Cena 01 - Plano 04 - Quadro 004.")
        return [SimpleNamespace(id=uuid4())]

    async def fake_animatic_bundle(*args: Any, **kwargs: Any) -> object:
        return object()

    async def fake_count(*args: Any, **kwargs: Any) -> int:
        return 1

    async def collect_progress(event: Any) -> None:
        progress_events.append(event)

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(project_agent, "_ensure_storyboard_scene_plan", fake_scene_plan)
    monkeypatch.setattr(
        project_agent,
        "storyboard_prompts_need_approval",
        fake_prompts_need_approval,
    )
    monkeypatch.setattr(
        project_agent,
        "storyboard_frames_need_generation",
        fake_frames_need_generation,
    )
    monkeypatch.setattr(
        project_agent,
        "generate_storyboard_frames",
        fake_generate_storyboard_frames,
    )
    monkeypatch.setattr(project_agent, "_count", fake_count)
    monkeypatch.setattr(project_agent, "generate_animatic_bundle", fake_animatic_bundle)

    result = await project_agent._ensure_storyboard_pipeline(
        cast(AsyncSession, object()),
        project_id,
        progress=collect_progress,
    )

    assert result.action == "generate_storyboard"
    assert any(isinstance(event, dict) and event["completed"] == 4 for event in progress_events)
    assert any(
        isinstance(event, dict) and event["detail"].startswith("Agora: gerando")
        for event in progress_events
    )


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
        raise AssertionError("video não deve consultar frames quando o storyboard está bloqueado")

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
async def test_video_pipeline_enqueues_pending_frames_after_prompt_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    frame_ids = [uuid4(), uuid4()]
    calls: list[str] = []
    captured_payload: dict[str, Any] = {}

    async def fake_storyboard(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        calls.append("storyboard")
        assert requested_project_id == project_id
        return ProjectChatResult("storyboard pronto", "generate_storyboard", False)

    async def fake_latest_many(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("frames")
        return [SimpleNamespace(id=frame_id) for frame_id in frame_ids]

    async def fake_pending_frame_ids(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append("pending")
        return frame_ids

    async def fake_enqueue(
        session: AsyncSession,
        requested_project_id: Any,
        step: str,
        payload: dict[str, Any],
    ) -> SimpleNamespace:
        calls.append("enqueue")
        assert requested_project_id == project_id
        assert step == "video"
        captured_payload.update(payload)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(project_agent, "_ensure_storyboard_pipeline", fake_storyboard)
    monkeypatch.setattr(project_agent, "_latest_many", fake_latest_many)
    monkeypatch.setattr(project_agent, "_pending_video_frame_ids", fake_pending_frame_ids)
    monkeypatch.setattr(project_agent, "enqueue_project_step", fake_enqueue)

    result = await project_agent._ensure_video_pipeline(
        cast(AsyncSession, object()),
        project_id,
    )

    assert result == ProjectChatResult(
        "2 prompt(s) de vídeo aprovado(s) e enviado(s) para geração.",
        "generate_video",
        True,
    )
    assert captured_payload["frame_ids"] == [str(frame_id) for frame_id in frame_ids]
    assert isinstance(captured_payload["request_id"], str)
    assert captured_payload["request_id"]
    assert calls == ["storyboard", "frames", "pending", "enqueue"]


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
        force: bool = False,
    ) -> tuple[SimpleNamespace, str, bool]:
        calls.append("script")
        assert requested_project_id == project_id
        assert force is False
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
async def test_project_chat_routes_storyboard_prompt_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    calls: list[str] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        assert requested_project_id == project_id
        return {"counts": {"scripts": 1, "shots": 4, "frames": 0}}

    async def fake_approve_storyboard(
        session: AsyncSession,
        requested_project_id: Any,
        progress: Any = None,
        scene_number: int | None = None,
        generate_after_approval: bool = True,
    ) -> ProjectChatResult:
        calls.append("approve_storyboard")
        assert requested_project_id == project_id
        assert scene_number is None
        assert generate_after_approval is True
        return ProjectChatResult("storyboard aprovado", "approve_storyboard_prompt", True)

    async def fail_visual_approval(*args: Any, **kwargs: Any) -> ProjectChatResult:
        raise AssertionError("pedido de storyboard nao deve aprovar ativo visual")

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(
        project_agent,
        "_approve_storyboard_prompts_from_chat",
        fake_approve_storyboard,
    )
    monkeypatch.setattr(
        project_agent,
        "_approve_visual_prompt_from_chat",
        fail_visual_approval,
    )

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "storyboard",
        "pode aprovar os prompts pendentes para geração dos storyboards",
        [],
    )

    assert result == ProjectChatResult(
        "storyboard aprovado",
        "approve_storyboard_prompt",
        True,
    )
    assert calls == ["approve_storyboard"]


@pytest.mark.asyncio
async def test_storyboard_prompt_approval_from_chat_generates_without_explicit_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_latest(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(id=script_id)

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_approve_prompts(*args: Any, **kwargs: Any) -> int:
        calls.append("approve")
        return 38

    async def fake_frames_need_generation(*args: Any, **kwargs: Any) -> bool:
        calls.append("frames_need_generation")
        return len(calls) == 2

    async def fake_prompts_need_approval(*args: Any, **kwargs: Any) -> bool:
        calls.append("prompts_need_approval")
        return False

    async def fake_generate_frames(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("generate_frames")
        return [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    async def fake_animatic(*args: Any, **kwargs: Any) -> object:
        calls.append("animatic")
        return object()

    monkeypatch.setattr(project_agent, "_latest", fake_latest)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(project_agent, "approve_storyboard_prompts", fake_approve_prompts)
    monkeypatch.setattr(
        project_agent,
        "storyboard_frames_need_generation",
        fake_frames_need_generation,
    )
    monkeypatch.setattr(
        project_agent,
        "storyboard_prompts_need_approval",
        fake_prompts_need_approval,
    )
    monkeypatch.setattr(project_agent, "generate_storyboard_frames", fake_generate_frames)
    monkeypatch.setattr(project_agent, "generate_animatic_bundle", fake_animatic)

    result = await project_agent._approve_storyboard_prompts_from_chat(
        cast(AsyncSession, object()),
        project_id,
    )

    assert result.message == "Aprovei 38 prompt(s) de storyboard e gerei 2 quadro(s)."
    assert calls == [
        "approve",
        "frames_need_generation",
        "prompts_need_approval",
        "generate_frames",
        "frames_need_generation",
        "animatic",
    ]


@pytest.mark.asyncio
async def test_storyboard_prompt_approval_from_chat_can_generate_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    script_id = uuid4()
    calls: list[str] = []

    async def fake_latest(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(id=script_id)

    async def fake_visual_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"complete": True, "missing_categories": [], "missing_views": 0}

    async def fake_approve_prompts(*args: Any, **kwargs: Any) -> int:
        calls.append("approve")
        return 2

    async def fake_frames_need_generation(*args: Any, **kwargs: Any) -> bool:
        calls.append("frames_need_generation")
        return len(calls) == 2

    async def fake_prompts_need_approval(*args: Any, **kwargs: Any) -> bool:
        calls.append("prompts_need_approval")
        return False

    async def fake_generate_frames(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        calls.append("generate_frames")
        return [SimpleNamespace(id=uuid4())]

    async def fake_animatic(*args: Any, **kwargs: Any) -> object:
        calls.append("animatic")
        return object()

    monkeypatch.setattr(project_agent, "_latest", fake_latest)
    monkeypatch.setattr(project_agent, "visual_reference_completion_report", fake_visual_report)
    monkeypatch.setattr(project_agent, "approve_storyboard_prompts", fake_approve_prompts)
    monkeypatch.setattr(
        project_agent,
        "storyboard_frames_need_generation",
        fake_frames_need_generation,
    )
    monkeypatch.setattr(
        project_agent,
        "storyboard_prompts_need_approval",
        fake_prompts_need_approval,
    )
    monkeypatch.setattr(project_agent, "generate_storyboard_frames", fake_generate_frames)
    monkeypatch.setattr(project_agent, "generate_animatic_bundle", fake_animatic)

    result = await project_agent._approve_storyboard_prompts_from_chat(
        cast(AsyncSession, object()),
        project_id,
        generate_after_approval=True,
    )

    assert result.message == "Aprovei 2 prompt(s) de storyboard e gerei 1 quadro(s)."
    assert calls == [
        "approve",
        "frames_need_generation",
        "prompts_need_approval",
        "generate_frames",
        "frames_need_generation",
        "animatic",
    ]


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
        "aprove o prompt do personagem Clara e crie a imagem",
    )

    assert result == ProjectChatResult(
        "Aprovei 1 ativo(s) visual(is) e criei 1 imagem(ns).",
        "approve_visual_prompt",
        True,
    )
    assert captured["args"][1:] == (
        project_id,
        "character",
        target_id,
        ["front_portrait"],
    )


@pytest.mark.asyncio
async def test_visual_prompt_approval_from_chat_generates_without_explicit_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    target_id = uuid4()
    target = project_agent.VisualChatTarget("character", target_id, "Clara")
    calls: list[str] = []

    async def fake_targets(*args: Any, **kwargs: Any) -> list[Any]:
        return [target]

    async def fake_views(*args: Any, **kwargs: Any) -> set[str]:
        return set()

    async def fake_approve_and_generate(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append("approve_and_generate")
        return [object()]

    monkeypatch.setattr(project_agent, "_visual_chat_targets", fake_targets)
    monkeypatch.setattr(project_agent, "_visual_reference_views_for_target", fake_views)
    monkeypatch.setattr(
        project_agent,
        "approve_visual_target_and_generate_views",
        fake_approve_and_generate,
    )

    result = await project_agent._approve_visual_prompt_from_chat(
        cast(AsyncSession, object()),
        project_id,
        "aprove o prompt do personagem Clara",
    )

    assert result == ProjectChatResult(
        "Aprovei 1 ativo(s) visual(is) e criei 1 imagem(ns).",
        "approve_visual_prompt",
        True,
    )
    assert calls == ["approve_and_generate"]


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
        reset_existing: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        captured_force.append(force)
        assert reset_existing is False
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
async def test_project_chat_can_reset_visual_bible_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    captured_reset: list[bool] = []

    async def fake_context(session: AsyncSession, requested_project_id: Any) -> dict[str, Any]:
        return {"project_id": str(requested_project_id)}

    async def fake_assets(
        session: AsyncSession,
        requested_project_id: Any,
        force: bool = False,
        reset_existing: bool = False,
        progress: Any = None,
    ) -> ProjectChatResult:
        captured_reset.append(reset_existing)
        assert force is True
        return ProjectChatResult("biblioteca visual recriada", "generate_assets", True)

    monkeypatch.setattr(project_agent, "build_project_context", fake_context)
    monkeypatch.setattr(project_agent, "_ensure_visual_pipeline", fake_assets)

    result = await handle_project_chat(
        cast(AsyncSession, object()),
        project_id,
        "assets",
        "regenerar prompts da biblioteca visual",
        [],
    )

    assert result.action == "generate_assets"
    assert captured_reset == [True]


@pytest.mark.asyncio
async def test_visual_pipeline_reports_blocked_reset_for_advanced_project(
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

    async def fake_reset(*args: Any, **kwargs: Any) -> dict[str, int]:
        raise ValueError("Não posso apagar e recriar a Biblioteca Visual")

    async def fail_visual_bible(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("visual bible should not be generated when reset is blocked")

    monkeypatch.setattr(project_agent, "_ensure_script_pipeline", fake_script)
    monkeypatch.setattr(project_agent, "reset_visual_bible", fake_reset)
    monkeypatch.setattr(project_agent, "generate_visual_bible", fail_visual_bible)

    result = await project_agent._ensure_visual_pipeline(
        cast(AsyncSession, object()),
        project_id,
        force=True,
        reset_existing=True,
    )

    assert result.action == "generate_assets"
    assert result.failed is True
    assert "Não posso apagar" in result.message


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
        force: bool = False,
    ) -> tuple[SimpleNamespace, str, bool]:
        if progress is not None:
            await progress("Vou escrever o roteiro.")
        assert force is False
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
