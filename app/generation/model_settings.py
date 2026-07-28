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
from app.config.settings import get_settings
from app.generation.models import ProjectModelSetting
from app.providers.llm.omniroute import OmniRouteLLMProvider
from app.providers.llm.types import LLMProvider

NARRATIVE_TASKS = [
    "generate_story_ideas",
    "generate_script",
    "generate_scenes_and_shots",
]

TASK_LABELS = {
    "generate_story_ideas": "Ideias",
    "generate_script": "Roteiro",
    "generate_scenes_and_shots": "Cenas e planos",
}


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
    model = validate_model_name(model, provider=provider)
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
        model = validate_model_name(provider_model(settings, provider, "text"), provider=provider)
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
    if setting is not None and setting.provider == "omniroute":
        ensure_provider_api_key(settings.omniroute_api_key, "omniroute", "OMNIROUTE_API_KEY")
        return OmniRouteLLMProvider(), validate_model_name(setting.model, provider="omniroute")
    if setting is not None and setting.provider == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")
    provider = effective_provider_for_channel(settings, "text")
    ensure_provider_api_key(settings.omniroute_api_key, "omniroute", "OMNIROUTE_API_KEY")
    return OmniRouteLLMProvider(), validate_model_name(
        provider_model(settings, provider, "text"),
        provider=provider,
    )
