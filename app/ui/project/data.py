from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import ArtifactStatus
from app.costs.models import CostEntry
from app.database.session import AsyncSessionLocal
from app.finalization.models import Export, SubtitleTrack
from app.generation.model_settings import ensure_default_model_settings
from app.generation.models import ProjectModelSetting
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact, Project
from app.projects.repository import ProjectRepository
from app.projects.service import list_projects
from app.projects.versioning import INACTIVE_DERIVED_STATUSES
from app.quality.models import ContinuityIssue, QualityCheck
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline, TimelineItem
from app.storyboards.service import list_storyboard_prompt_previews
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryIdea
from app.video_generation.models import GenerationJob, VideoClip
from app.video_generation.planning import _video_effective_prompt, _video_prompt_override
from app.visual_bible.models import Character, Location, Prop, VisualReference


async def scalar_count(
    session: AsyncSession, model: type[Any], project_id: UUID | None = None
) -> int:
    statement = select(func.count()).select_from(model)
    if project_id is not None and hasattr(model, "project_id"):
        statement = statement.where(model.project_id == project_id)
    value = await session.scalar(statement)
    return int(value or 0)


async def latest(session: AsyncSession, model: type[Any], project_id: UUID) -> Any | None:
    result = await session.execute(
        select(model).where(model.project_id == project_id).order_by(model.created_at.desc())
    )
    return result.scalars().first()


async def latest_many(
    session: AsyncSession,
    model: type[Any],
    project_id: UUID,
    limit: int = 6,
) -> list[Any]:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def active_many(
    session: AsyncSession,
    model: type[Any],
    project_id: UUID,
    limit: int = 6,
) -> list[Any]:
    statement = (
        select(model)
        .join(Artifact, model.artifact_id == Artifact.id)
        .where(
            model.project_id == project_id,
            Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
        )
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(statement)
    return list(result.scalars())


async def active_count(session: AsyncSession, model: type[Any], project_id: UUID) -> int:
    statement = (
        select(func.count())
        .select_from(model)
        .join(Artifact, model.artifact_id == Artifact.id)
        .where(
            model.project_id == project_id,
            Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
        )
    )
    value = await session.scalar(statement)
    return int(value or 0)


async def project_cards() -> list[Project]:
    try:
        async with AsyncSessionLocal() as session:
            return await list_projects(session)
    except Exception:
        return []


async def dashboard_metrics() -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            project_count = await scalar_count(session, Project)
            artifact_count = await scalar_count(session, Artifact)
            job_count = await scalar_count(session, GenerationJob)
            open_issues = await session.scalar(
                select(func.count())
                .select_from(ContinuityIssue)
                .where(ContinuityIssue.accepted.is_(False))
            )
            exports = await scalar_count(session, Export)
    except Exception as exc:
        return {"Banco": "indisponivel", "Detalhe": type(exc).__name__}
    return {
        "Projetos": str(project_count),
        "Artefatos": str(artifact_count),
        "Jobs": str(job_count),
        "Alertas QA": str(open_issues or 0),
        "Exports": str(exports),
    }


async def project_summary(project_id: UUID) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        project = await ProjectRepository(session).get_project(project_id)
        if project is None:
            return None
        await ensure_default_model_settings(session, project_id)
        production_settings = await get_or_create_production_settings(session, project_id)
        model_result = await session.execute(
            select(ProjectModelSetting)
            .where(ProjectModelSetting.project_id == project_id)
            .order_by(ProjectModelSetting.task)
        )
        cost_total = await session.scalar(
            select(func.coalesce(func.sum(CostEntry.total_cost), Decimal("0.000000"))).where(
                CostEntry.project_id == project_id
            )
        )
        latest_quality = await latest(session, QualityCheck, project_id)
        latest_export = await latest(session, Export, project_id)
        latest_timeline = await latest(session, Timeline, project_id)
        timeline_items: list[TimelineItem] = []
        if latest_timeline is not None:
            item_result = await session.execute(
                select(TimelineItem)
                .where(TimelineItem.timeline_id == latest_timeline.id)
                .order_by(TimelineItem.order_index)
                .limit(12)
            )
            timeline_items = list(item_result.scalars())
        script = await latest(session, Script, project_id)
        visual_refs = await active_many(session, VisualReference, project_id, 100)
        if script is not None:
            frame_result = await session.execute(
                select(StoryboardFrame)
                .join(Shot, StoryboardFrame.shot_id == Shot.id)
                .join(Scene, Shot.scene_id == Scene.id)
                .join(Artifact, StoryboardFrame.artifact_id == Artifact.id)
                .where(
                    StoryboardFrame.project_id == project_id,
                    Scene.script_id == script.id,
                    Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
                )
                .order_by(StoryboardFrame.frame_number)
            )
            frames = list(frame_result.scalars())
        else:
            frames = []
        storyboard_prompt_previews = (
            await list_storyboard_prompt_previews(session, project_id, script.id)
            if script is not None
            else []
        )
        clips = await latest_many(session, VideoClip, project_id, 100)
        generated_clip_frame_result = await session.execute(
            select(VideoClip.storyboard_frame_id).where(VideoClip.project_id == project_id)
        )
        generated_clip_frame_ids = set(generated_clip_frame_result.scalars())
        video_prompt_previews: list[dict[str, Any]] = []
        if frames:
            frame_shot_ids = [frame.shot_id for frame in frames if frame.shot_id is not None]
            shot_context: dict[UUID, tuple[Shot, Scene]] = {}
            if frame_shot_ids:
                shot_context_result = await session.execute(
                    select(Shot, Scene)
                    .join(Scene, Shot.scene_id == Scene.id)
                    .where(Shot.id.in_(frame_shot_ids))
                )
                shot_context = {shot.id: (shot, scene) for shot, scene in shot_context_result.all()}
            production_metadata = production_settings.metadata_json or {}
            for frame in frames:
                shot, scene = shot_context.get(frame.shot_id, (None, None))
                video_prompt_previews.append(
                    {
                        "frame_id": frame.id,
                        "shot_id": frame.shot_id,
                        "frame_number": frame.frame_number,
                        "scene_number": getattr(scene, "scene_number", None),
                        "shot_number": getattr(shot, "shot_number", None),
                        "duration_seconds": frame.duration_seconds,
                        "prompt": _video_effective_prompt(
                            production_metadata,
                            frame,
                            shot,
                            scene,
                        ),
                        "custom_prompt": _video_prompt_override(
                            production_metadata,
                            frame.id,
                        )
                        is not None,
                        "generated": frame.id in generated_clip_frame_ids,
                    }
                )
        visual_asset_ids = {
            reference.asset_id for reference in visual_refs if reference.asset_id is not None
        }
        frame_asset_ids = {frame.asset_id for frame in frames if frame.asset_id is not None}
        asset_ids = visual_asset_ids | frame_asset_ids
        if asset_ids:
            asset_result = await session.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.id.in_(asset_ids),
                )
            )
            assets = list(asset_result.scalars())
        else:
            assets = []
        return {
            "project": project,
            "production_settings": production_settings,
            "counts": {
                "briefings": await scalar_count(session, Briefing, project_id),
                "ideas": await scalar_count(session, StoryIdea, project_id),
                "scripts": await scalar_count(session, Script, project_id),
                "scenes": await active_count(session, Scene, project_id),
                "shots": await active_count(session, Shot, project_id),
                "characters": await active_count(session, Character, project_id),
                "locations": await active_count(session, Location, project_id),
                "props": await active_count(session, Prop, project_id),
                "visual_refs": await active_count(session, VisualReference, project_id),
                "frames": await active_count(session, StoryboardFrame, project_id),
                "animatics": await scalar_count(session, Animatic, project_id),
                "clips": await scalar_count(session, VideoClip, project_id),
                "audio": await scalar_count(session, AudioTrack, project_id),
                "subtitles": await scalar_count(session, SubtitleTrack, project_id),
                "exports": await scalar_count(session, Export, project_id),
                "qa_issues": await scalar_count(session, ContinuityIssue, project_id),
                "stale_artifacts": int(
                    await session.scalar(
                        select(func.count())
                        .select_from(Artifact)
                        .where(
                            Artifact.project_id == project_id,
                            Artifact.status == ArtifactStatus.STALE,
                        )
                    )
                    or 0
                ),
            },
            "cost_total": str(cost_total or Decimal("0.000000")),
            "quality": latest_quality,
            "export": latest_export,
            "model_settings": list(model_result.scalars()),
            "script": script,
            "scenes": await active_many(session, Scene, project_id, 12),
            "shots": await active_many(session, Shot, project_id, 20),
            "characters": await active_many(session, Character, project_id, 100),
            "locations": await active_many(session, Location, project_id, 100),
            "props": await active_many(session, Prop, project_id, 100),
            "visual_refs": visual_refs,
            "assets": assets,
            "frames": frames,
            "storyboard_prompt_previews": storyboard_prompt_previews,
            "video_prompt_previews": video_prompt_previews,
            "clips": clips,
            "timeline": latest_timeline,
            "timeline_items": timeline_items,
        }
