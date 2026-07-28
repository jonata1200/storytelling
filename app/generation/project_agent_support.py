import sys
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.project_agent_context import _count, _latest
from app.generation.project_agent_types import ProgressCallback, ProjectChatResult, _emit_progress
from app.storytelling.models import Briefing, StoryIdea
from app.storytelling.service import generate_story_ideas
from app.visual_bible.models import Character, Location, Prop
from app.visual_bible.service import generate_visual_bible


def _facade_attr(name: str, fallback: object) -> Any:
    facade = sys.modules.get("app.generation.project_agent")
    return getattr(facade, name, fallback) if facade is not None else fallback


async def _ensure_ideas_pipeline(
    session: AsyncSession,
    project_id: UUID,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    latest = _facade_attr("_latest", _latest)
    count = _facade_attr("_count", _count)
    story_ideas = _facade_attr("generate_story_ideas", generate_story_ideas)
    briefing = await latest(session, Briefing, project_id)
    if briefing is None:
        return ProjectChatResult(
            "Este projeto ainda não tem briefing para orientar as ideias.",
            "generate_ideas",
        )

    existing_ideas = await count(session, StoryIdea, project_id)
    if existing_ideas > 0:
        return ProjectChatResult(
            "O projeto ja tem ideias registradas. Posso ajudar a escolher ou ajustar uma delas.",
            "generate_ideas",
            False,
        )

    await _emit_progress(progress, "Vou criar ideias narrativas a partir do briefing.")
    ideas = await story_ideas(session, project_id)
    if not ideas:
        return ProjectChatResult(
            "Não consegui gerar ideias para este projeto.",
            "generate_ideas",
            failed=True,
        )
    return ProjectChatResult(f"Criei {len(ideas)} ideia(s) para o projeto.", "generate_ideas", True)


async def _project_has_visual_bible(session: AsyncSession, project_id: UUID) -> bool:
    count = _facade_attr("_count", _count)
    return any(
        [
            await count(session, Character, project_id),
            await count(session, Location, project_id),
            await count(session, Prop, project_id),
        ]
    )


async def _refresh_visual_bible_after_script_regeneration(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    progress: ProgressCallback | None = None,
) -> bool:
    if not await _project_has_visual_bible(session, project_id):
        return False
    await _emit_progress(
        progress,
        "Vou atualizar automaticamente personagens, locais e objetos a partir do novo roteiro.",
    )
    visual_bible = _facade_attr("generate_visual_bible", generate_visual_bible)
    visual = await visual_bible(session, project_id, script_id)
    if visual is None:
        await _emit_progress(
            progress,
            "Não consegui atualizar automaticamente a biblioteca visual.",
        )
        return False
    await _emit_progress(
        progress,
        "Biblioteca visual atualizada para o roteiro atual.",
    )
    return True
