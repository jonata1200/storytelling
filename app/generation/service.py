from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.models import PromptExecution, PromptTemplate
from app.generation.prompt_compiler import compile_prompt
from app.providers.llm.types import LLMProvider, LLMRequest, LLMResult

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Gere tres ideias estruturadas para um video vertical. "
        "Tema: {theme}. Publico: {audience}. Emocao: {primary_emotion}."
    ),
    "generate_story_bible": (
        "Crie uma Story Bible estruturada usando a ideia aprovada: {idea_title}."
    ),
    "generate_script": (
        "Crie um roteiro em {language} para duracao alvo de {target_duration_seconds}s."
    ),
    "generate_scenes_and_shots": (
        "Divida o roteiro em cenas e planos com duracao total de {target_duration_seconds}s."
    ),
}


async def get_or_create_prompt_template(session: AsyncSession, task: str) -> PromptTemplate:
    result = await session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task == task, PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.version.desc())
    )
    template = result.scalars().first()
    if template is not None:
        return template

    template = PromptTemplate(
        name=task.replace("_", " ").title(),
        task=task,
        version=1,
        template_text=DEFAULT_TEMPLATES[task],
        output_schema={},
        active=True,
    )
    session.add(template)
    await session.flush()
    return template


async def run_structured_generation(
    session: AsyncSession,
    provider: LLMProvider,
    project_id: UUID,
    task: str,
    variables: dict,
    artifact_id: UUID | None = None,
    model: str | None = None,
) -> tuple[LLMResult, PromptExecution]:
    template = await get_or_create_prompt_template(session, task)
    prompt = compile_prompt(template.template_text, variables)
    started = perf_counter()
    result = await provider.generate_structured(
        LLMRequest(
            task=task,
            prompt=prompt,
            variables=variables,
            output_schema=template.output_schema,
            model=model or "mock-llm",
        )
    )
    duration_ms = int((perf_counter() - started) * 1000)
    execution = PromptExecution(
        project_id=project_id,
        artifact_id=artifact_id,
        prompt_template_id=template.id,
        template_version=template.version,
        provider=result.provider,
        model=result.model,
        prompt=prompt,
        variables=variables,
        response=result.content,
        parameters={},
        estimated_cost=result.estimated_cost,
        duration_ms=duration_ms,
    )
    session.add(execution)
    await session.flush()
    return result, execution
