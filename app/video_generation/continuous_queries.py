from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling.models import Scene, Script, Shot
from app.visual_bible.models import Character, Location


async def _latest_script(session: AsyncSession, project_id: UUID) -> Script | None:
    result = await session.execute(
        select(Script).where(Script.project_id == project_id).order_by(Script.updated_at.desc())
    )
    return result.scalars().first()


async def _project_scenes_and_shots(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[list[Scene], dict[UUID, list[Shot]]]:
    scene_result = await session.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.scene_number)
    )
    scenes = list(scene_result.scalars())
    if not scenes:
        return [], {}
    scene_ids = [scene.id for scene in scenes]
    shot_result = await session.execute(
        select(Shot).where(Shot.scene_id.in_(scene_ids)).order_by(Shot.shot_number)
    )
    shots_by_scene: dict[UUID, list[Shot]] = {scene.id: [] for scene in scenes}
    for shot in shot_result.scalars():
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)
    return scenes, shots_by_scene


async def _project_visual_context(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, list[dict[str, str]]]:
    from app.video_generation.continuous import continuous_video_visual_context

    characters = list(
        (
            await session.execute(
                select(Character).where(Character.project_id == project_id).order_by(Character.name)
            )
        ).scalars()
    )
    locations = list(
        (
            await session.execute(
                select(Location).where(Location.project_id == project_id).order_by(Location.name)
            )
        ).scalars()
    )
    return continuous_video_visual_context(characters, locations)

