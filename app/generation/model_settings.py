from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_policy import ensure_openrouter_api_key, validate_openrouter_model_name
from app.config.settings import get_settings
from app.generation.models import ProjectModelSetting
from app.providers.llm.openrouter import OpenRouterLLMProvider
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
    if provider != "openrouter":
        raise ValueError("Use OpenRouter com um modelo real. Providers mock estão bloqueados.")
    model = validate_openrouter_model_name(model)
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
    provider = "openrouter"
    try:
        model = validate_openrouter_model_name(settings.openrouter_default_model)
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
    ensure_openrouter_api_key(settings.openrouter_api_key)
    if setting is not None and setting.provider == "openrouter":
        return OpenRouterLLMProvider(), validate_openrouter_model_name(setting.model)
    if setting is not None and setting.provider == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real da OpenRouter.")
    return OpenRouterLLMProvider(), validate_openrouter_model_name(
        settings.openrouter_default_model
    )
