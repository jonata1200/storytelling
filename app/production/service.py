from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import is_mock_model, validate_model_name
from app.config.settings import GOOGLE_AI_IMAGE_MODELS, GOOGLE_AI_VIDEO_MODELS
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
AUDIO_MODES = {"dialogue_only"}
MOCK_IMAGE_MODEL = "mock-image"
MOCK_VIDEO_MODEL = "mock-video"
LEGACY_DEFAULT_IMAGE_MODELS = {
    ".......",
    "chatgpt-web/gpt-5.5",
    "sourceful/riverflow-v2.5-pro",
    "sourceful/riverflow-v2-fast",
}
LEGACY_DEFAULT_VIDEO_MODELS = {
    ".......",
    "bytedance/seedance-2.0-fast",
    "Kling-3.0-omni",
}


def _validate_model_name(value: object, field_name: str) -> str:
    return validate_model_name(value, field_name)


def _validate_allowed_model(value: object, field_name: str, allowed_models: tuple[str, ...]) -> str:
    model = _validate_model_name(value, field_name)
    if model not in allowed_models:
        allowed = ", ".join(allowed_models)
        raise ValueError(f"Modelo inválido para {field_name}: {model}. Use: {allowed}")
    return model


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
            raise ValueError(f"Valor inválido para {key}: {validated[key]}. Use: {allowed}")
    if "image_model" in validated:
        validated["image_model"] = _validate_allowed_model(
            validated["image_model"],
            "image_model",
            GOOGLE_AI_IMAGE_MODELS,
        )
    if "video_model" in validated:
        validated["video_model"] = _validate_allowed_model(
            validated["video_model"],
            "video_model",
            GOOGLE_AI_VIDEO_MODELS,
        )
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
        model = validate_model_name(project_model, "image_model")
        if model in GOOGLE_AI_IMAGE_MODELS:
            return model
    if default_model and not is_mock_model(default_model):
        model = validate_model_name(default_model, "IMAGE_MODEL")
        if model in GOOGLE_AI_IMAGE_MODELS:
            return model
        return GOOGLE_AI_IMAGE_MODELS[0]
    raise ValueError("Configure um modelo real de imagem antes de gerar imagens.")


def resolve_video_model(project_video_model: str | None, default_video_model: str | None) -> str:
    project_model = str(project_video_model or "").strip()
    default_model = str(default_video_model or "").strip()
    if (
        project_model
        and not is_mock_model(project_model)
        and project_model not in LEGACY_DEFAULT_VIDEO_MODELS
    ):
        model = validate_model_name(project_model, "video_model")
        if model in GOOGLE_AI_VIDEO_MODELS:
            return model
    if default_model and not is_mock_model(default_model):
        model = validate_model_name(default_model, "VIDEO_MODEL")
        if model in GOOGLE_AI_VIDEO_MODELS:
            return model
        return GOOGLE_AI_VIDEO_MODELS[0]
    raise ValueError("Configure um modelo real de vídeo antes de gerar clipes.")


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
