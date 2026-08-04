from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    SUPPORTED_MODEL_PROVIDERS,
    effective_provider_for_channel,
    ensure_provider_api_key,
    provider_model,
    validate_model_name,
)
from app.config.settings import OLLAMA_CLOUD_TEXT_MODELS, get_settings
from app.generation.models import ProjectModelSetting
from app.providers.llm.ollama_cloud import OllamaCloudLLMProvider
from app.providers.llm.types import LLMProvider

NARRATIVE_TASKS = [
    "generate_story_ideas",
    "generate_script",
    "generate_scenes_and_shots",
    "generate_visual_bible",
    "generate_storyboard_prompts",
]

TASK_LABELS = {
    "generate_story_ideas": "Ideias",
    "generate_script": "Roteiro",
    "generate_scenes_and_shots": "Cenas e planos",
    "generate_visual_bible": "Biblioteca visual",
    "generate_storyboard_prompts": "Prompts de storyboard",
}


def llm_provider_for_name(settings: Any, provider: str) -> LLMProvider:
    if provider == "ollama_cloud":
        ensure_provider_api_key(
            settings.ollama_cloud_api_key,
            "ollama_cloud",
            "OLLAMA_CLOUD_API_KEY",
        )
        return OllamaCloudLLMProvider()
    if provider == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")
    raise ValueError("Provider de texto não suportado.")


def configured_text_llm_provider(settings: Any) -> tuple[LLMProvider, str, str]:
    provider = effective_provider_for_channel(settings, "text")
    llm_provider = llm_provider_for_name(settings, provider)
    model = validate_text_provider_model(
        provider,
        provider_model(settings, provider, "text"),
    )
    return llm_provider, model, provider


def validate_text_provider_model(provider: str, value: object) -> str:
    model = validate_model_name(value, provider=provider)
    if provider == "ollama_cloud" and model not in OLLAMA_CLOUD_TEXT_MODELS:
        allowed_models = ", ".join(OLLAMA_CLOUD_TEXT_MODELS)
        raise ValueError(f"Modelo Ollama Cloud não permitido. Use: {allowed_models}")
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
    except ValueError:
        return created
    for task in NARRATIVE_TASKS:
        setting = await get_model_setting(session, project_id, task)
        if setting is None:
            created.append(await set_model_setting(session, project_id, task, provider, model))
    return created


async def llm_provider_for_task(
    session: AsyncSession, project_id: UUID, task: str
) -> tuple[LLMProvider, str]:
    setting = await get_model_setting(session, project_id, task)
    settings = get_settings()
    if setting is not None and setting.provider in SUPPORTED_MODEL_PROVIDERS:
        try:
            model = validate_text_provider_model(setting.provider, setting.model)
        except ValueError:
            return configured_text_llm_provider(settings)[:2]
        return llm_provider_for_name(settings, setting.provider), model
    llm_provider, model, _provider = configured_text_llm_provider(settings)
    return llm_provider, model
