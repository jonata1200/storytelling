from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.generation.director_agent import ask_director_agent
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.storyboards.models import Animatic, StoryboardFrame
from app.storyboards.service import generate_animatic_bundle, generate_storyboard_frames
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryBible, StoryIdea
from app.storytelling.service import (
    generate_scenes_and_shots,
    generate_script,
    generate_story_bible,
    generate_story_ideas,
    revise_script,
)
from app.video_generation.models import VideoClip
from app.video_generation.service import generate_video_clips
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import (
    generate_visual_bible,
    generate_visual_references,
    initial_view_for,
)

ProjectChatAction = Literal[
    "chat",
    "generate_script",
    "revise_script",
    "generate_assets",
    "generate_storyboard",
    "generate_video",
]

REVISION_TERMS = (
    "ajuste",
    "ajustar",
    "altere",
    "alterar",
    "melhore",
    "melhorar",
    "mude",
    "mudar",
    "modifique",
    "modificar",
    "refaça",
    "refazer",
    "reescreva",
    "reescrever",
    "revise",
    "revisar",
)


@dataclass(frozen=True)
class ProjectChatResult:
    message: str
    action: ProjectChatAction
    changed: bool = False


async def _latest(
    session: AsyncSession, model: type[Any], project_id: UUID
) -> Any | None:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _latest_many(
    session: AsyncSession,
    model: type[Any],
    project_id: UUID,
    limit: int = 5,
) -> list[Any]:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _count(session: AsyncSession, model: type[Any], project_id: UUID) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(model.project_id == project_id)
    )
    return int(value or 0)


def _compact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact_payload(item) for key, item in list(value.items())[:24]}
    if isinstance(value, list):
        return [_compact_payload(item) for item in value[:8]]
    return value


async def build_project_context(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return {"project_id": str(project_id), "found": False}

    briefing = await _latest(session, Briefing, project_id)
    idea = await _latest(session, StoryIdea, project_id)
    bible = await _latest(session, StoryBible, project_id)
    script = await _latest(session, Script, project_id)
    stale_count = await session.scalar(
        select(func.count())
        .select_from(Artifact)
        .where(Artifact.project_id == project_id, Artifact.status == ArtifactStatus.STALE)
    )
    return {
        "found": True,
        "project": {
            "id": str(project.id),
            "title": project.title,
            "description": project.description,
            "status": project.status,
        },
        "briefing": (
            {
                "theme": briefing.theme,
                "audience": briefing.audience,
                "genre": briefing.genre,
                "primary_emotion": briefing.primary_emotion,
                "duration_minutes": float(briefing.desired_duration_minutes),
                "objective": briefing.content_objective,
                "constraints": briefing.constraints,
            }
            if briefing is not None
            else None
        ),
        "idea": _compact_payload(idea.payload) if idea is not None else None,
        "story_bible": _compact_payload(bible.payload) if bible is not None else None,
        "script": (
            {
                "title": script.title,
                "target_duration_seconds": script.target_duration_seconds,
                "word_count": script.word_count,
                "content_preview": script.content[:1200],
            }
            if script is not None
            else None
        ),
        "counts": {
            "ideas": await _count(session, StoryIdea, project_id),
            "bibles": await _count(session, StoryBible, project_id),
            "scripts": await _count(session, Script, project_id),
            "scenes": await _count(session, Scene, project_id),
            "shots": await _count(session, Shot, project_id),
            "characters": await _count(session, Character, project_id),
            "locations": await _count(session, Location, project_id),
            "props": await _count(session, Prop, project_id),
            "visual_refs": await _count(session, VisualReference, project_id),
            "frames": await _count(session, StoryboardFrame, project_id),
            "animatics": await _count(session, Animatic, project_id),
            "clips": await _count(session, VideoClip, project_id),
            "stale_artifacts": int(stale_count or 0),
        },
        "recent": {
            "scenes": [
                {"number": scene.scene_number, "title": scene.title, "summary": scene.summary}
                for scene in await _latest_many(session, Scene, project_id, 6)
            ],
            "characters": [
                {"name": character.name, "role": character.role}
                for character in await _latest_many(session, Character, project_id, 6)
            ],
            "frames": [
                {
                    "number": frame.frame_number,
                    "duration_seconds": frame.duration_seconds,
                    "prompt": frame.prompt,
                }
                for frame in await _latest_many(session, StoryboardFrame, project_id, 6)
            ],
        },
    }


def classify_project_chat_action(message: str, active: str) -> ProjectChatAction:
    normalized = message.lower()
    generation_terms = (
        "crie",
        "criar",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "faca",
        "fazer",
        "faça",
        "monte",
        "montar",
        "produza",
        "produzir",
    )
    script_terms = ("roteiro", "historia", "história", "cena", "cenas", "dialogo", "diálogo")
    asset_terms = (
        "personagem",
        "personagens",
        "visual",
        "locais",
        "local",
        "objeto",
        "objetos",
        "props",
        "referencia",
        "referência",
    )
    storyboard_terms = (
        "storyboard",
        "quadro",
        "quadros",
        "frame",
        "frames",
        "enquadramento",
        "animatic",
    )
    video_terms = ("video", "vídeo", "clipe", "clipes", "montagem")

    wants_generation = any(term in normalized for term in generation_terms)
    wants_revision = _requests_regeneration(message)

    if (wants_generation or wants_revision) and any(term in normalized for term in video_terms):
        return "generate_video"
    if (wants_generation or wants_revision) and any(
        term in normalized for term in storyboard_terms
    ):
        return "generate_storyboard"
    if (wants_generation or wants_revision) and any(term in normalized for term in asset_terms):
        return "generate_assets"
    if wants_revision and (active == "script" or any(term in normalized for term in script_terms)):
        return "revise_script"
    if wants_revision:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
    if wants_generation and (
        active == "script" or any(term in normalized for term in script_terms)
    ):
        return "generate_script"
    if wants_generation:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
        return "generate_script"
    return "chat"


def _requests_regeneration(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in REVISION_TERMS)


async def _ensure_script_pipeline(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[Script | None, str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return None, "Este projeto ainda nao tem briefing para orientar o roteiro.", False

    script = await _latest(session, Script, project_id)
    if script is not None:
        scene_count = await _count(session, Scene, project_id)
        if scene_count == 0:
            scenes = await generate_scenes_and_shots(session, project_id, script.id)
            if scenes is None:
                return script, "O roteiro existe, mas nao consegui criar cenas e planos.", True
            return script, "O roteiro ja existia; criei cenas e planos para ele.", True
        return script, "O projeto ja tem roteiro e cenas.", False

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return None, "Nao consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    bible = await _latest(session, StoryBible, project_id)
    if bible is None:
        bible = await generate_story_bible(session, project_id, idea.id)
        if bible is None:
            return None, "Nao consegui gerar a Story Bible antes do roteiro.", False

    script = await generate_script(session, project_id, bible.id)
    if script is None:
        return None, "Nao consegui gerar o roteiro para este projeto.", False
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return script, "Roteiro criado, mas as cenas e planos nao foram gerados.", True
    return script, "Roteiro criado e dividido em cenas e planos.", True


async def _ensure_visual_pipeline(
    session: AsyncSession, project_id: UUID, force: bool = False
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id)
    if script is None:
        return ProjectChatResult(message, "generate_assets", changed)

    bible = await _latest(session, StoryBible, project_id)
    if bible is None:
        return ProjectChatResult(
            "Nao encontrei a Story Bible para criar personagens.",
            "generate_assets",
        )

    existing_characters = await _count(session, Character, project_id)
    existing_locations = await _count(session, Location, project_id)
    existing_props = await _count(session, Prop, project_id)
    needs_visual = (
        force
        or existing_characters == 0
        or existing_locations == 0
        or existing_props == 0
    )
    changed = changed or needs_visual
    if needs_visual:
        visual = await generate_visual_bible(session, project_id, bible.id)
        if visual is None:
            return ProjectChatResult(
                "Nao consegui criar personagens e referencias visuais.",
                "generate_assets",
            )

    characters = await _latest_many(session, Character, project_id, 6)
    locations = await _latest_many(session, Location, project_id, 4)
    props = await _latest_many(session, Prop, project_id, 4)
    if await _count(session, VisualReference, project_id) == 0:
        for character in characters:
            await generate_visual_references(
                session,
                project_id,
                "character",
                character.id,
                [initial_view_for("character")],
            )
        for location in locations:
            await generate_visual_references(
                session,
                project_id,
                "location",
                location.id,
                [initial_view_for("location")],
            )
        for prop in props:
            await generate_visual_references(
                session,
                project_id,
                "prop",
                prop.id,
                [initial_view_for("prop")],
            )
        changed = True
    return ProjectChatResult(
        "Personagens, locais, objetos e referencias visuais estao prontos.",
        "generate_assets",
        changed,
    )


async def _ensure_storyboard_pipeline(
    session: AsyncSession, project_id: UUID, force: bool = False
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id)
    if script is None:
        return ProjectChatResult(message, "generate_storyboard", changed)

    frames = await _count(session, StoryboardFrame, project_id)
    if force or frames == 0:
        generated_frames = await generate_storyboard_frames(session, project_id, script.id)
        if generated_frames is None:
            return ProjectChatResult(
                "Nao consegui gerar o storyboard.",
                "generate_storyboard",
                changed,
            )
        changed = True

    animatics = await _count(session, Animatic, project_id)
    if force or animatics == 0:
        bundle = await generate_animatic_bundle(session, project_id, script.id)
        if bundle is None:
            return ProjectChatResult(
                "Storyboard criado, mas o animatic nao foi gerado.",
                "generate_storyboard",
                True,
            )
        changed = True

    return ProjectChatResult(
        "Storyboard e animatic criados para o roteiro atual.",
        "generate_storyboard",
        changed,
    )


async def _ensure_video_pipeline(
    session: AsyncSession, project_id: UUID, force: bool = False
) -> ProjectChatResult:
    storyboard_result = await _ensure_storyboard_pipeline(session, project_id, force=force)
    changed = storyboard_result.changed
    frames = await _latest_many(session, StoryboardFrame, project_id, 100)
    if not frames:
        return ProjectChatResult(
            "Nao ha frames de storyboard para gerar video.",
            "generate_video",
            changed,
        )

    clips = await _count(session, VideoClip, project_id)
    if force or clips == 0:
        generated = await generate_video_clips(
            session,
            project_id,
            frame_ids=[frame.id for frame in frames],
            variants_per_frame=2 if force else 1,
        )
        if generated is None:
            return ProjectChatResult(
                "Nao consegui gerar os clipes de video.",
                "generate_video",
                changed,
            )
        changed = True
    return ProjectChatResult(
        "Clipes de video gerados para o storyboard atual.",
        "generate_video",
        changed,
    )


async def handle_project_chat(
    session: AsyncSession,
    project_id: UUID,
    active: str,
    message: str,
    history: list[dict[str, str]],
) -> ProjectChatResult:
    action = classify_project_chat_action(message, active)
    force = _requests_regeneration(message)
    project_context = await build_project_context(session, project_id)

    if action == "generate_script":
        _script, result_message, changed = await _ensure_script_pipeline(session, project_id)
        return ProjectChatResult(result_message, action, changed)
    if action == "revise_script":
        script, result_message, changed = await _ensure_script_pipeline(session, project_id)
        if script is None:
            return ProjectChatResult(result_message, action, changed)
        revised = await revise_script(session, project_id, script.id, message, project_context)
        if revised is None:
            return ProjectChatResult("Nao consegui aplicar a revisao no roteiro.", action, changed)
        return ProjectChatResult("Roteiro revisado e nova versao salva no projeto.", action, True)
    if action == "generate_assets":
        return await _ensure_visual_pipeline(session, project_id, force=force)
    if action == "generate_storyboard":
        return await _ensure_storyboard_pipeline(session, project_id, force=force)
    if action == "generate_video":
        return await _ensure_video_pipeline(session, project_id, force=force)

    response = await ask_director_agent(
        session,
        project_id,
        active,
        message,
        project_context,
        history,
    )
    return ProjectChatResult(response, "chat", False)
