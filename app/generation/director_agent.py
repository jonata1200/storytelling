from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation

SECTION_TASKS = {
    "script": "generate_script",
    "assets": "generate_script",
    "storyboard": "generate_scenes_and_shots",
    "video": "generate_scenes_and_shots",
}

SECTION_NAMES = {
    "script": "roteiro",
    "assets": "personagens, locais e objetos",
    "storyboard": "storyboard",
    "video": "produção e montagem de vídeo",
}


async def ask_director_agent(
    session: AsyncSession,
    project_id: UUID,
    section: str,
    message: str,
    project_context: dict[str, Any],
    history: list[dict[str, str]],
) -> str:
    task = SECTION_TASKS.get(section, "generate_script")
    provider, model = await llm_provider_for_task(session, project_id, task)
    recent_history = history[-8:]
    prompt = (
        "Você é o Diretor IA de um estúdio de criação audiovisual. "
        f"O usuário está na área de {SECTION_NAMES.get(section, section)}. "
        "Responda em português do Brasil, de forma prática, criativa e curta. "
        "Considere o estado real do projeto, preserve continuidade e sugira o próximo passo. "
        "Se o pedido exigir uma geração, explique claramente qual ação da interface executar. "
        f"Estado do projeto: {project_context}. "
        f"Conversa recente: {recent_history}. Pedido atual: {message}"
    )
    result, _execution = await run_structured_generation(
        session,
        provider,
        project_id,
        "director_agent_chat",
        {
            "prompt": prompt,
            "section": section,
            "message": message,
            "project_context": project_context,
            "history": recent_history,
        },
        model=model,
        fallback_on_runtime_error=True,
    )
    await session.commit()
    response = result.content.get("message")
    return str(response or "Posso ajudar a desenvolver esta etapa. O que deseja ajustar?")
