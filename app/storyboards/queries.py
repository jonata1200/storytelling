from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.projects.versioning import INACTIVE_DERIVED_STATUSES
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot


def storyboard_coverage_errors(
    shot_rows: list[tuple[Shot, Scene]], frames: list[StoryboardFrame]
) -> list[str]:
    errors: list[str] = []
    expected_shot_ids = [shot.id for shot, _scene in shot_rows]
    frame_by_shot = {frame.shot_id: frame for frame in frames}
    missing = [shot_id for shot_id in expected_shot_ids if shot_id not in frame_by_shot]
    if missing:
        errors.append(f"{len(missing)} plano(s) sem frame de storyboard")
    if len(frame_by_shot) != len(frames):
        errors.append("frames duplicados para o mesmo plano")
    expected_duration = sum(shot.duration_seconds for shot, _scene in shot_rows)
    actual_duration = sum(frame.duration_seconds for frame in frames)
    if expected_duration != actual_duration:
        errors.append(
            f"duracao dos frames ({actual_duration}s) difere dos planos ({expected_duration}s)"
        )
    expected_order = expected_shot_ids
    actual_order = [frame.shot_id for frame in sorted(frames, key=lambda item: item.frame_number)]
    if actual_order != expected_order:
        errors.append("ordem dos frames nao segue cena/plano")
    for frame in frames:
        if frame.asset_id is None:
            errors.append(f"frame {frame.frame_number} sem asset")
        if len(str(frame.prompt or "").split()) < 10:
            errors.append(f"frame {frame.frame_number} com prompt generico")
    return errors


async def list_storyboard_frames(
    session: AsyncSession, project_id: UUID, script_id: UUID | None = None
) -> list[StoryboardFrame]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return []
    frame_artifact = aliased(Artifact)
    statement = (
        select(StoryboardFrame)
        .join(frame_artifact, StoryboardFrame.artifact_id == frame_artifact.id)
        .where(StoryboardFrame.project_id == project_id)
        .where(frame_artifact.status.notin_(INACTIVE_DERIVED_STATUSES))
        .order_by(StoryboardFrame.frame_number)
    )
    if script_id is not None:
        scene_artifact = aliased(Artifact)
        shot_artifact = aliased(Artifact)
        statement = (
            select(StoryboardFrame)
            .join(Shot, StoryboardFrame.shot_id == Shot.id)
            .join(Scene, Shot.scene_id == Scene.id)
            .join(frame_artifact, StoryboardFrame.artifact_id == frame_artifact.id)
            .join(shot_artifact, Shot.artifact_id == shot_artifact.id)
            .join(scene_artifact, Scene.artifact_id == scene_artifact.id)
            .where(
                StoryboardFrame.project_id == project_id,
                Scene.script_id == script_id,
                frame_artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
                shot_artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
                scene_artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
            )
            .order_by(StoryboardFrame.frame_number)
        )
    result = await session.execute(statement)
    return list(result.scalars())
