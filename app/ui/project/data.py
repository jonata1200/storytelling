from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import ArtifactStatus
from app.costs.service import project_cost_summary
from app.database.session import AsyncSessionLocal
from app.generation.model_settings import ensure_default_model_settings
from app.generation.models import ProjectModelSetting
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact, Project
from app.projects.repository import ProjectRepository
from app.projects.service import list_projects
from app.projects.versioning import INACTIVE_DERIVED_STATUSES
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryIdea
from app.video_generation.models import ContinuousVideoSegment, GenerationJob, VideoClip
from app.visual_bible.models import Character, Location, VisualReference

logger = logging.getLogger(__name__)


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
        _active("visual_refs", VisualReference),
        _plain("clips", VideoClip),
        _plain("continuous_video_segments", ContinuousVideoSegment),
        select(
            literal("continuous_video_done_segments").label("label"),
            func.count().label("value"),
        )
        .select_from(ContinuousVideoSegment)
        .where(
            ContinuousVideoSegment.project_id == project_id,
            ContinuousVideoSegment.review_status == "done",
        ),
        select(
            literal("continuous_video_generated_segments").label("label"),
            func.count().label("value"),
        )
        .select_from(ContinuousVideoSegment)
        .where(
            ContinuousVideoSegment.project_id == project_id,
            or_(
                ContinuousVideoSegment.generated_video_asset_id.isnot(None),
                ContinuousVideoSegment.asset_id.isnot(None),
                ContinuousVideoSegment.review_status == "done",
            ),
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
        if section in {"script", "video"}
        else "script"
    )
    load_script_details = active_section == "script"
    load_video = active_section == "video"

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
        continuous_video_segments = []
        if load_video:
            continuous_video_segments_result = await session.execute(
                select(ContinuousVideoSegment)
                .where(ContinuousVideoSegment.project_id == project_id)
                .order_by(ContinuousVideoSegment.segment_number)
            )
            continuous_video_segments = list(continuous_video_segments_result.scalars())
        script = await latest(session, Script, project_id)
        visual_refs: list[Any] = []
        clips = await latest_many(session, VideoClip, project_id, 100) if load_video else []
        visual_asset_ids = {
            reference.asset_id for reference in visual_refs if reference.asset_id is not None
        }
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
        asset_ids = visual_asset_ids | continuous_asset_ids
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
        characters_list: list[Any] = []
        locations_list: list[Any] = []
        all_visual_approved = False
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
            "characters": characters_list,
            "locations": locations_list,
            "visual_refs": visual_refs,
            "assets": assets,
            "all_visual_prompts_approved": all_visual_approved,
            "continuous_video_segments": continuous_video_segments,
            "clips": clips,
        }
