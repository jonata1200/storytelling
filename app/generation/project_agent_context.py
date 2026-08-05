from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.dubbing.models import DubbingJob
from app.finalization.models import Export
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.projects.versioning import INACTIVE_DERIVED_STATUSES
from app.quality.models import ContinuityIssue, QualityCheck
from app.storyboards.models import Animatic, StoryboardFrame, Timeline
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryIdea
from app.video_generation.models import VideoClip
from app.visual_bible.models import Character, Location, Prop, VisualReference


async def _latest(session: AsyncSession, model: type[Any], project_id: UUID) -> Any | None:
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


async def _active_scene_count_for_script(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(Scene)
        .join(Artifact, Artifact.id == Scene.artifact_id)
        .where(
            Scene.project_id == project_id,
            Scene.script_id == script_id,
            Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
        )
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
            "timelines": await _count(session, Timeline, project_id),
            "exports": await _count(session, Export, project_id),
            "dubbing_jobs": await _count(session, DubbingJob, project_id),
            "quality_checks": await _count(session, QualityCheck, project_id),
            "qa_issues": await _count(session, ContinuityIssue, project_id),
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
