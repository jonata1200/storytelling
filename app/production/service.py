from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.production.models import ProjectProductionSettings
from app.projects.repository import ProjectRepository

WORKFLOW_MODES = {
    "continuous_fast": "Video continuo economico",
}
# Modos legados ainda gravados em projetos antigos: aceitos na leitura/salvamento
# para nao quebrar a atualizacao de production settings, mas nao mais selecionaveis.
_LEGACY_WORKFLOW_MODES = {
    "keyframes_i2v",
    "elements_sequential",
    "elements_parallel",
}

CONTENT_TYPES = {
    "short_drama": "Short drama",
    "ad": "Anuncio",
    "motion_comic": "Motion comic",
    "explainer": "Explicativo",
}

ASPECT_RATIOS = ["9:16", "16:9"]
IMAGE_RESOLUTION_BY_ASPECT_RATIO = {
    "9:16": "720x1280",
    "16:9": "1280x720",
}
VIDEO_RESOLUTIONS = ["720p"]
AUDIO_MODES = {"dialogue_only"}


def normalize_video_resolution(value: object) -> str:
    """Valida a resolução de vídeo solicitada.

    A aplicação suporta somente ``720p`` no momento. Valores não suportados são
    rejeitados explicitamente em vez de descartados silenciosamente.
    """
    normalized = str(value or "").strip()
    if normalized and normalized not in VIDEO_RESOLUTIONS:
        allowed = ", ".join(VIDEO_RESOLUTIONS)
        raise ValueError(f"Resolução de vídeo não suportada: {normalized}. Use: {allowed}")
    return VIDEO_RESOLUTIONS[0]


def normalize_image_aspect_ratio(value: object) -> str:
    aspect_ratio = str(value or "").strip()
    return aspect_ratio if aspect_ratio in IMAGE_RESOLUTION_BY_ASPECT_RATIO else "9:16"


def _validated_production_payload(payload: dict) -> dict:
    validators = {
        "content_type": set(CONTENT_TYPES),
        "aspect_ratio": set(ASPECT_RATIOS),
        "workflow_mode": set(WORKFLOW_MODES) | _LEGACY_WORKFLOW_MODES,
        "audio_mode": AUDIO_MODES,
    }
    validated = dict(payload)
    if "aspect_ratio" in validated:
        validated["aspect_ratio"] = normalize_image_aspect_ratio(validated["aspect_ratio"])
    if "video_resolution" in validated:
        validated["video_resolution"] = normalize_video_resolution(validated["video_resolution"])
    for key, allowed_values in validators.items():
        if key in validated and validated[key] not in allowed_values:
            allowed = ", ".join(sorted(allowed_values))
            raise ValueError(f"Valor inválido para {key}: {validated[key]}. Use: {allowed}")
    if "motion_intensity" in validated:
        try:
            intensity = int(float(validated["motion_intensity"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("motion_intensity deve ser um numero inteiro entre 1 e 10") from exc
        if intensity < 1 or intensity > 10:
            raise ValueError("motion_intensity deve ficar entre 1 e 10")
        validated["motion_intensity"] = intensity
    if "episode_number" in validated:
        try:
            episode_number = int(float(validated["episode_number"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "episode_number deve ser um numero inteiro maior ou igual a 1"
            ) from exc
        if episode_number < 1:
            raise ValueError("episode_number deve ser maior ou igual a 1")
        validated["episode_number"] = episode_number
    if "metadata_json" in validated and not isinstance(validated["metadata_json"], dict):
        raise ValueError("metadata_json deve ser um objeto")
    return validated


async def get_or_create_production_settings(
    session: AsyncSession,
    project_id: UUID,
    parent_project_id: UUID | None = None,
    episode_number: int = 1,
) -> ProjectProductionSettings:
    result = await session.execute(
        select(ProjectProductionSettings).where(ProjectProductionSettings.project_id == project_id)
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
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        result = await session.execute(
            select(ProjectProductionSettings).where(
                ProjectProductionSettings.project_id == project_id
            )
        )
        settings = result.scalars().first()
        if settings is None:
            raise
    return settings


async def update_production_settings(
    session: AsyncSession,
    project_id: UUID,
    payload: dict,
) -> ProjectProductionSettings:
    if await ProjectRepository(session).get_project(project_id) is None:
        raise ValueError("Project not found")
    settings = await get_or_create_production_settings(session, project_id)
    for key, value in _validated_production_payload(payload).items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    await session.commit()
    await session.refresh(settings)
    return settings


def workflow_mode_label(mode: str) -> str:
    return WORKFLOW_MODES.get(mode, mode)
