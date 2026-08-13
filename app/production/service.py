from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import is_mock_model, validate_model_name
from app.config.settings import GOOGLE_AI_IMAGE_MODELS, GOOGLE_AI_VIDEO_MODELS
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
IMAGE_RESOLUTIONS = ["720x1280", "1280x720"]
IMAGE_RESOLUTION_BY_ASPECT_RATIO = {
    "9:16": "720x1280",
    "16:9": "1280x720",
}
VIDEO_RESOLUTIONS = ["720p"]
AUDIO_MODES = {"dialogue_only"}
MOCK_IMAGE_MODEL = "mock-image"


def _validate_model_name(value: object, field_name: str) -> str:
    return validate_model_name(value, field_name)


def _validate_allowed_model(value: object, field_name: str, allowed_models: tuple[str, ...]) -> str:
    model = _validate_model_name(value, field_name)
    if model not in allowed_models:
        allowed = ", ".join(allowed_models)
        raise ValueError(f"Modelo inválido para {field_name}: {model}. Use: {allowed}")
    return model


def normalize_video_resolution(value: object) -> str:
    _ = value
    return VIDEO_RESOLUTIONS[0]


def normalize_image_aspect_ratio(value: object) -> str:
    aspect_ratio = str(value or "").strip()
    return aspect_ratio if aspect_ratio in IMAGE_RESOLUTION_BY_ASPECT_RATIO else "9:16"


def normalize_image_resolution(value: object, aspect_ratio: object | None = "9:16") -> str:
    has_explicit_aspect_ratio = bool(str(aspect_ratio or "").strip())
    normalized_aspect_ratio = normalize_image_aspect_ratio(aspect_ratio)
    expected_resolution = IMAGE_RESOLUTION_BY_ASPECT_RATIO[normalized_aspect_ratio]
    text = str(value or "").strip().lower()
    if text in {expected_resolution.lower(), expected_resolution.replace("x", " x ").lower()}:
        return expected_resolution
    if not has_explicit_aspect_ratio and text in {
        "1920x1080",
        "1920 x 1080",
        "1280x720",
        "1280 x 720",
    }:
        return IMAGE_RESOLUTION_BY_ASPECT_RATIO["16:9"]
    return expected_resolution


def _validated_production_payload(payload: dict) -> dict:
    validators = {
        "content_type": set(CONTENT_TYPES),
        "aspect_ratio": set(ASPECT_RATIOS),
        "image_resolution": set(IMAGE_RESOLUTIONS),
        "workflow_mode": set(WORKFLOW_MODES) | _LEGACY_WORKFLOW_MODES,
        "audio_mode": AUDIO_MODES,
    }
    validated = dict(payload)
    if "aspect_ratio" in validated:
        validated["aspect_ratio"] = normalize_image_aspect_ratio(validated["aspect_ratio"])
    if "image_resolution" in validated:
        validated["image_resolution"] = normalize_image_resolution(
            validated["image_resolution"],
            validated.get("aspect_ratio"),
        )
    if "video_resolution" in validated:
        validated["video_resolution"] = normalize_video_resolution(
            validated["video_resolution"]
        )
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
    if project_model and not is_mock_model(project_model):
        model = validate_model_name(project_model, "image_model")
        if model in GOOGLE_AI_IMAGE_MODELS:
            return model
    if default_model and not is_mock_model(default_model):
        model = validate_model_name(default_model, "IMAGE_MODEL")
        if model in GOOGLE_AI_IMAGE_MODELS:
            return model
        return GOOGLE_AI_IMAGE_MODELS[0]
    raise ValueError("Configure um modelo real de imagem antes de gerar imagens.")


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
