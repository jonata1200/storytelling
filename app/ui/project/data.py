from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import ArtifactStatus, GenerationJobType
from app.costs.service import project_cost_summary
from app.database.session import AsyncSessionLocal
from app.generation.model_settings import ensure_default_model_settings
from app.generation.models import ProjectModelSetting
from app.observability.service import project_execution_summary
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact, Project
from app.projects.repository import ProjectRepository
from app.projects.service import list_projects
from app.projects.versioning import INACTIVE_DERIVED_STATUSES
from app.storyboards.models import Animatic, StoryboardFrame, Timeline, TimelineItem
from app.storyboards.service import list_storyboard_prompt_previews
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryIdea
from app.video_generation.models import ContinuousVideoSegment, GenerationJob, VideoClip
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


def project_counts_statement(project_id: UUID) -> Any:
    """Todas as contagens do workspace em uma única query agregada (UNION ALL)."""

    def _plain(label: str, model: type[Any]) -> Any:
        return (
            select(literal(label).label("label"), func.count().label("value"))
            .select_from(model)
            .where(model.project_id == project_id)
        )

    def _active(label: str, model: type[Any]) -> Any:
        return (
            select(literal(label).label("label"), func.count().label("value"))
            .select_from(model)
            .join(Artifact, model.artifact_id == Artifact.id)
            .where(
                model.project_id == project_id,
                Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
            )
        )

    return union_all(
        _plain("briefings", Briefing),
        _plain("ideas", StoryIdea),
        _plain("scripts", Script),
        _active("scenes", Scene),
        _active("shots", Shot),
        _active("characters", Character),
        _active("locations", Location),
        _active("props", Prop),
        _active("visual_refs", VisualReference),
        _active("frames", StoryboardFrame),
        _plain("animatics", Animatic),
        _plain("clips", VideoClip),
        _plain("continuous_video_segments", ContinuousVideoSegment),
        select(
            literal("continuous_video_approved_segments").label("label"),
            func.count().label("value"),
        )
        .select_from(ContinuousVideoSegment)
        .where(
            ContinuousVideoSegment.project_id == project_id,
            ContinuousVideoSegment.review_status == "approved",
        ),
        select(literal("stale_artifacts").label("label"), func.count().label("value"))
        .select_from(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.status == ArtifactStatus.STALE,
        ),
    )


async def project_counts(session: AsyncSession, project_id: UUID) -> dict[str, int]:
    result = await session.execute(project_counts_statement(project_id))
    return {str(label): int(value) for label, value in result.all()}


async def project_cards() -> list[Project]:
    try:
        async with AsyncSessionLocal() as session:
            return await list_projects(session)
    except Exception:
        return []


def dashboard_metrics_statement() -> Any:
    """Métricas do dashboard em uma única query agregada (UNION ALL)."""
    return union_all(
        select(literal("Projetos").label("metric"), func.count()).select_from(Project),
        select(literal("Artefatos").label("metric"), func.count()).select_from(Artifact),
        select(literal("Jobs").label("metric"), func.count()).select_from(GenerationJob),
    )


async def dashboard_metrics() -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            metrics = await session.execute(dashboard_metrics_statement())
            values = {str(row[0]): str(int(row[1])) for row in metrics.all()}
    except Exception as exc:
        return {"Banco": "indisponível", "Detalhe": type(exc).__name__}
    return values


async def project_summary(project_id: UUID, section: str = "script") -> dict[str, Any] | None:
    active_section = (
        section
        if section in {"script", "assets", "storyboard", "video"}
        else "script"
    )
    load_script_details = active_section == "script"
    load_assets = active_section == "assets"
    load_storyboard = active_section == "storyboard"
    load_video = active_section == "video"
    load_frames = load_storyboard or load_video

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
        cost_summary = await project_cost_summary(session, project_id)
        latest_timeline = await latest(session, Timeline, project_id) if load_video else None
        execution_summary = await project_execution_summary(session, project_id)
        video_jobs = []
        continuous_video_segments = []
        if load_video:
            video_jobs_result = await session.execute(
                select(GenerationJob)
                .where(
                    GenerationJob.project_id == project_id,
                    GenerationJob.job_type == GenerationJobType.VIDEO,
                )
                .order_by(GenerationJob.created_at.desc())
                .limit(20)
            )
            video_jobs = list(video_jobs_result.scalars())
            continuous_video_segments_result = await session.execute(
                select(ContinuousVideoSegment)
                .where(ContinuousVideoSegment.project_id == project_id)
                .order_by(ContinuousVideoSegment.segment_number)
            )
            continuous_video_segments = list(continuous_video_segments_result.scalars())
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
        visual_refs = (
            await active_many(session, VisualReference, project_id, 100) if load_assets else []
        )
        if script is not None and load_frames:
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
            await list_storyboard_prompt_previews(
                session,
                project_id,
                script.id,
                generate_missing=False,
            )
            if script is not None and load_storyboard
            else []
        )
        clips = await latest_many(session, VideoClip, project_id, 100) if load_video else []
        if load_video:
            generated_clip_frame_result = await session.execute(
                select(VideoClip.storyboard_frame_id).where(VideoClip.project_id == project_id)
            )
            generated_clip_frame_ids = set(generated_clip_frame_result.scalars())
        else:
            generated_clip_frame_ids = set()
        video_prompt_previews: list[dict[str, Any]] = []
        if frames and load_video:
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
        continuous_asset_ids = {
            asset_id
            for segment in continuous_video_segments
            for asset_id in (
                segment.asset_id,
                segment.generated_video_asset_id,
                segment.source_video_asset_id,
                segment.source_frame_asset_id,
                segment.final_frame_asset_id,
            )
            if asset_id is not None
        }
        asset_ids = visual_asset_ids | frame_asset_ids | continuous_asset_ids
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
            "counts": await project_counts(session, project_id),
            "cost_total": str(cost_summary.total_cost or Decimal("0.000000")),
            "cost_summary": cost_summary,
            "model_settings": list(model_result.scalars()),
            "script": script,
            "scenes": await active_many(session, Scene, project_id, 12)
            if load_script_details
            else [],
            "shots": await active_many(session, Shot, project_id, 20)
            if load_script_details
            else [],
            "characters": await active_many(session, Character, project_id, 100)
            if load_assets
            else [],
            "locations": await active_many(session, Location, project_id, 100)
            if load_assets
            else [],
            "props": await active_many(session, Prop, project_id, 100) if load_assets else [],
            "visual_refs": visual_refs,
            "assets": assets,
            "frames": frames,
            "storyboard_prompt_previews": storyboard_prompt_previews,
            "video_prompt_previews": video_prompt_previews,
            "continuous_video_segments": continuous_video_segments,
            "video_jobs": video_jobs,
            "clips": clips,
            "timeline": latest_timeline,
            "timeline_items": timeline_items,
            "execution_summary": execution_summary,
        }
