import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    SUPPORTED_MODEL_PROVIDERS,
    SUPPORTED_TEXT_PROVIDERS,
    effective_provider_for_channel,
    ensure_provider_api_key,
    provider_api_key,
    provider_model,
    provider_requires_api_key,
    validate_model_name,
)
from app.config.settings import (
    OLLAMA_CLOUD_TEXT_MODELS,
    get_settings,
    normalize_ollama_cloud_text_model,
)
from app.generation.models import ProjectModelSetting
from app.providers.llm.types import LLMProvider
from app.providers.registry import resolve_text_provider

logger = logging.getLogger(__name__)

NARRATIVE_TASKS = [
    "generate_story_ideas",
    "generate_story_hooks",
    "generate_script",
    "generate_scenes_and_shots",
    "generate_storyboard_prompts",
]

TASK_LABELS = {
    "generate_story_ideas": "Ideias",
    "generate_story_hooks": "Ganchos",
    "generate_script": "Roteiro",
    "generate_scenes_and_shots": "Cenas e planos",
    "generate_storyboard_prompts": "Prompts de storyboard",
}


def llm_provider_for_name(settings: Any, provider: str) -> LLMProvider:
    if provider not in SUPPORTED_TEXT_PROVIDERS:
        raise ValueError("Provider de texto não suportado.")
    if provider_requires_api_key(settings, provider):
        ensure_provider_api_key(
            provider_api_key(settings, provider),
            provider,
        )
    if provider == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")
    return resolve_text_provider(settings, provider)


def configured_text_llm_provider(settings: Any) -> tuple[LLMProvider, str, str]:
    provider = effective_provider_for_channel(settings, "text")
    llm_provider = llm_provider_for_name(settings, provider)
    model = validate_text_provider_model(provider, provider_model(settings, provider, "text"))
    return llm_provider, model, provider


def validate_text_provider_model(provider: str, value: object) -> str:
    model = validate_model_name(value, provider=provider)
    if provider == "ollama_cloud":
        normalized = normalize_ollama_cloud_text_model(model)
        if normalized != model:
            allowed = ", ".join(OLLAMA_CLOUD_TEXT_MODELS)
            raise ValueError(f"Modelo Ollama Cloud inválido: {model}. Use: {allowed}")
        return normalized
    return model


async def get_model_setting(
    session: AsyncSession, project_id: UUID, task: str
) -> ProjectModelSetting | None:
    result = await session.execute(
        select(ProjectModelSetting).where(
            ProjectModelSetting.project_id == project_id,
            ProjectModelSetting.task == task,
            ProjectModelSetting.enabled.is_(True),
        )
    )
    return result.scalars().first()


async def set_model_setting(
    session: AsyncSession,
    project_id: UUID,
    task: str,
    provider: str,
    model: str,
) -> ProjectModelSetting:
    provider = provider.strip().casefold()
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ValueError("Use um provider de IA real. Providers mock estão bloqueados.")
    model = validate_text_provider_model(provider, model)
    result = await session.execute(
        select(ProjectModelSetting).where(
            ProjectModelSetting.project_id == project_id,
            ProjectModelSetting.task == task,
        )
    )
    setting = result.scalars().first()
    if setting is None:
        setting = ProjectModelSetting(
            project_id=project_id,
            task=task,
            provider=provider,
            model=model,
            enabled=True,
            parameters={},
        )
        session.add(setting)
    else:
        setting.provider = provider
        setting.model = model
        setting.enabled = True
    await session.commit()
    await session.refresh(setting)
    return setting


async def ensure_default_model_settings(
    session: AsyncSession, project_id: UUID
) -> list[ProjectModelSetting]:
    settings = get_settings()
    created: list[ProjectModelSetting] = []
    provider = effective_provider_for_channel(settings, "text")
    try:
        model = validate_text_provider_model(provider, provider_model(settings, provider, "text"))
    except ValueError as exc:
        logger.warning(
            "ensure_default_model_settings_validation_failed project_id=%s provider=%s: %s",
            project_id,
            provider,
            exc,
        )
        return created
    for task in NARRATIVE_TASKS:
        setting = await get_model_setting(session, project_id, task)
        if setting is None:
            created.append(await set_model_setting(session, project_id, task, provider, model))
    return created


async def llm_provider_for_task(
    session: AsyncSession, project_id: UUID, task: str
) -> tuple[LLMProvider, str]:
    settings = get_settings()
    setting = await get_model_setting(session, project_id, task)
    provider = str(
        getattr(setting, "provider", "") or effective_provider_for_channel(settings, "text")
    )
    configured_model = (
        getattr(setting, "model", None)
        if setting is not None
        else provider_model(settings, provider, "text")
    )
    model = validate_text_provider_model(provider, configured_model)
    return llm_provider_for_name(settings, provider), model
