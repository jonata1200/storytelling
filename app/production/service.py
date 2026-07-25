from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_policy import is_mock_model, validate_openrouter_model_name
from app.production.models import ProjectProductionSettings
from app.projects.repository import ProjectRepository

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
AUDIO_MODES = {"narration_subtitles"}
MOCK_IMAGE_MODEL = "mock-image"
MOCK_VIDEO_MODEL = "mock-video"
LEGACY_DEFAULT_IMAGE_MODELS = {"sourceful/riverflow-v2.5-pro"}


def _validate_model_name(value: object, field_name: str) -> str:
    return validate_openrouter_model_name(value, field_name)


def _validated_production_payload(payload: dict) -> dict:
    validators = {
        "content_type": set(CONTENT_TYPES),
        "aspect_ratio": set(ASPECT_RATIOS),
        "image_resolution": set(RESOLUTIONS),
        "video_resolution": set(RESOLUTIONS),
        "workflow_mode": set(WORKFLOW_MODES),
        "audio_mode": AUDIO_MODES,
    }
    validated = dict(payload)
    for key, allowed_values in validators.items():
        if key in validated and validated[key] not in allowed_values:
            allowed = ", ".join(sorted(allowed_values))
            raise ValueError(f"Valor invalido para {key}: {validated[key]}. Use: {allowed}")
    for key in ("image_model", "video_model"):
        if key in validated:
            validated[key] = _validate_model_name(validated[key], key)
    if "motion_intensity" in validated:
        intensity = int(validated["motion_intensity"])
        if intensity < 1 or intensity > 10:
            raise ValueError("motion_intensity deve ficar entre 1 e 10")
        validated["motion_intensity"] = intensity
    if "episode_number" in validated:
        episode_number = int(validated["episode_number"])
        if episode_number < 1:
            raise ValueError("episode_number deve ser maior ou igual a 1")
        validated["episode_number"] = episode_number
    if "metadata_json" in validated and not isinstance(validated["metadata_json"], dict):
        raise ValueError("metadata_json deve ser um objeto")
    return validated


def resolve_image_model(project_image_model: str | None, default_image_model: str | None) -> str:
    project_model = str(project_image_model or "").strip()
    default_model = str(default_image_model or "").strip()
    if (
        project_model
        and not is_mock_model(project_model)
        and project_model not in LEGACY_DEFAULT_IMAGE_MODELS
    ):
        return validate_openrouter_model_name(project_model, "image_model")
    if default_model and not is_mock_model(default_model):
        return validate_openrouter_model_name(default_model, "OPENROUTER_IMAGE_MODEL")
    raise ValueError("Configure um modelo real de imagem da OpenRouter antes de gerar imagens.")


def resolve_video_model(project_video_model: str | None, default_video_model: str | None) -> str:
    project_model = str(project_video_model or "").strip()
    default_model = str(default_video_model or "").strip()
    if project_model and not is_mock_model(project_model):
        return validate_openrouter_model_name(project_model, "video_model")
    if default_model and not is_mock_model(default_model):
        return validate_openrouter_model_name(default_model, "OPENROUTER_VIDEO_MODEL")
    raise ValueError("Configure um modelo real de video da OpenRouter antes de gerar clipes.")


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
