from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.production.models import ProjectProductionSettings

WORKFLOW_MODES = {
    "keyframes_i2v": "Keyframes Images to Video",
    "elements_sequential": "Elements to Video Sequential",
    "elements_parallel": "Elements to Video Parallel",
}

CONTENT_TYPES = {
    "short_drama": "Short drama",
    "ad": "Anuncio",
    "motion_comic": "Motion comic",
    "explainer": "Explicativo",
}

ASPECT_RATIOS = ["9:16", "16:9", "1:1", "3:4", "4:3"]
RESOLUTIONS = ["720x1280", "1080x1920", "1920x1080", "3840x2160"]


async def get_or_create_production_settings(
    session: AsyncSession,
    project_id: UUID,
    parent_project_id: UUID | None = None,
    episode_number: int = 1,
) -> ProjectProductionSettings:
    result = await session.execute(
        select(ProjectProductionSettings).where(
            ProjectProductionSettings.project_id == project_id
        )
    )
    settings = result.scalars().first()
    if settings is not None:
        return settings

    settings = ProjectProductionSettings(
        project_id=project_id,
        parent_project_id=parent_project_id,
        episode_number=episode_number,
    )
    session.add(settings)
    await session.flush()
    return settings


async def update_production_settings(
    session: AsyncSession,
    project_id: UUID,
    payload: dict,
) -> ProjectProductionSettings:
    settings = await get_or_create_production_settings(session, project_id)
    for key, value in payload.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    await session.commit()
    await session.refresh(settings)
    return settings


def workflow_mode_label(mode: str) -> str:
    return WORKFLOW_MODES.get(mode, mode)
