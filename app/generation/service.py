from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.models import PromptExecution, PromptTemplate
from app.generation.prompt_compiler import compile_prompt
from app.providers.llm.types import LLMProvider, LLMRequest, LLMResult

DEFAULT_TEMPLATE_NAMES: dict[str, str] = {
    "generate_story_ideas": "Generate Story Ideas",
    "generate_story_bible": "Generate Story Bible",
    "generate_script": "Generate Script",
    "generate_scenes_and_shots": "Generate Scenes And Shots",
    "revise_script": "Revise Script",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Gere tres ideias estruturadas para uma historia vertical de {target_duration_minutes} "
        "minutos. Cada ideia precisa sustentar a duracao escolhida com conflito, virada e payoff. "
        "Tema: {theme}. Publico: {audience}. Emocao: {primary_emotion}. "
        "Responda somente JSON neste formato: "
        '{{"ideas":[{{"title":"...","genre":"...","primary_emotion":"...",'
        '"theme":"...","hook":"...","premise":"...","protagonist":"...",'
        '"duration_minutes":5,"retention_potential":80,"cliche_risk":20,'
        '"production_complexity":35}}]}}'
    ),
    "generate_story_bible": (
        "Crie uma Story Bible estruturada usando a ideia aprovada: {idea_title}. "
        "Use o briefing completo e a ideia em {idea}. Responda somente JSON com estes campos: "
        "title, logline, theme, genre, tone, target_emotion, audience, world_rules, "
        "visual_style, narrative_rules, forbidden_elements, characters, locations, props, "
        "timeline, relationships, continuity_rules, audio_style e export_profile."
    ),
    "generate_script": (
        "Crie um roteiro narrativo completo em {language} para uma historia vertical com "
        "duracao alvo de {target_duration_seconds}s. Use a Story Bible em {story_bible}. "
        "O texto deve ter gancho inicial, desenvolvimento, virada, climax e payoff emocional. "
        "Responda somente JSON neste formato exato: "
        '{{"title":"...","language":"pt-BR","target_duration_seconds":300,'
        '"word_count":650,"content":"ROTEIRO COMPLETO AQUI"}}'
    ),
    "generate_scenes_and_shots": (
        "Divida o roteiro em {script} em cenas e planos para duracao total de "
        "{target_duration_seconds}s. Responda somente JSON neste formato exato: "
        '{{"scenes":[{{"scene_number":1,"title":"...","summary":"...",'
        '"duration_seconds":75,"shots":[{{"shot_number":1,"duration_seconds":25,'
        '"narration_text":"...","dialogue_text":"","action":"...","emotion":"...",'
        '"visual_composition":"...","camera_movement":"...","generation_type":"IMAGE_TO_VIDEO"}}]}}]}}'
    ),
    "revise_script": (
        "Revise o roteiro existente atendendo ao pedido do usuario. "
        "Preserve a continuidade da Story Bible e mantenha a duracao alvo de "
        "{target_duration_seconds}s. Pedido do usuario: {instruction}. "
        "Contexto do projeto: {project_context}. Roteiro atual: {current_script}. "
        "Responda somente JSON neste formato exato: "
        '{{"title":"...","language":"pt-BR","target_duration_seconds":300,'
        '"word_count":650,"content":"ROTEIRO REVISADO COMPLETO AQUI"}}'
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
        default_name = DEFAULT_TEMPLATE_NAMES.get(task, task.replace("_", " ").title())
        if template.name == default_name and template.template_text != DEFAULT_TEMPLATES[task]:
            template.template_text = DEFAULT_TEMPLATES[task]
            template.output_schema = {}
            template.version += 1
            await session.flush()
        return template

    template = PromptTemplate(
        name=DEFAULT_TEMPLATE_NAMES.get(task, task.replace("_", " ").title()),
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
