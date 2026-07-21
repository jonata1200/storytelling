from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.models import PromptExecution, PromptTemplate
from app.generation.prompt_compiler import compile_prompt
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.types import LLMProvider, LLMRequest, LLMResult
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    VIDEO_CLIP_TARGET_SECONDS,
)

DEFAULT_TEMPLATE_NAMES: dict[str, str] = {
    "generate_story_ideas": "Generate Story Ideas",
    "generate_story_bible": "Generate Story Bible",
    "generate_script": "Generate Script",
    "generate_scenes_and_shots": "Generate Scenes And Shots",
    "revise_script": "Revise Script",
    "director_agent_chat": "Director Agent Chat",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Gere tres ideias estruturadas para uma historia vertical de {target_duration_minutes} "
        "minutos. Cada ideia precisa sustentar a duracao escolhida com conflito, virada e payoff. "
        "Tema: {theme}. Genero preferido: {genre}. Publico: {audience}. "
        "Emocao: {primary_emotion}. "
        "Cada ideia deve deixar claro conflito, obstaculos, stakes, twist, climax, payoff "
        "e resolucao para que Story Bible e roteiro consigam preservar a proposta original. "
        "{retry_guidance}"
        "Responda somente JSON neste formato: "
        '{{"ideas":[{{"title":"...","genre":"...","primary_emotion":"...",'
        '"theme":"...","hook":"...","premise":"...","protagonist":"...",'
        '"conflict":"...","obstacles":["..."],"stakes":"...","twist":"...",'
        '"climax":"...","payoff":"...","resolution":"...",'
        '"duration_minutes":5,"retention_potential":80,"cliche_risk":20,'
        '"production_complexity":35}}]}}'
    ),
    "generate_story_bible": (
        "Crie uma Story Bible estruturada usando a ideia aprovada: {idea_title}. "
        "Use o briefing completo e a ideia em {idea}. Responda somente JSON valido, sem markdown, "
        "sem comentarios e sem strings soltas dentro das listas. A Story Bible deve ser uma base "
        "editorial organizada para roteiro, biblioteca visual, storyboard e video. "
        "Use exatamente esta estrutura de alto nivel: title, logline, theme, genre, tone, "
        "target_emotion, audience, story_engine, world_rules, visual_style, narrative_rules, "
        "forbidden_elements, characters, locations, props, timeline, relationships, "
        "continuity_rules, audio_style e export_profile. "
        "story_engine deve conter dramatic_question, central_conflict, emotional_promise, "
        "inciting_incident, midpoint_turn, climax e ending_image. "
        "characters deve ser sempre array de objetos, nunca array de textos. Cada personagem "
        "precisa ter id, name, role, apparent_age, gender, origin, height_cm, body_type, "
        "face_shape, skin_tone, eyes, hair, base_outfit, palette, personality, desire, fear, "
        "secret e arc. base_outfit deve ser objeto com main_piece, color, fabric, texture, "
        "wear_marks e accessories; palette deve ser array de 3 a 5 cores. "
        "locations deve ser sempre array de objetos com id, name, description, layout, "
        "materials, palette, lighting, props_in_scene, spatial_rules e forbidden_elements; "
        "locais devem estar vazios, sem pessoas. "
        "props deve ser sempre array de objetos com id, name, dimensions, material, color, "
        "state, owner, narrative_importance, first_appearance e visual_rules. "
        "timeline deve ter beats ordenados com act, beat, purpose e emotional_turn. "
        "relationships deve ter source, target, relationship e tension. "
        "continuity_rules deve ser array de regras objetivas. "
        "export_profile deve conter aspect_ratio '9:16', resolution '1080x1920' "
        "e language 'pt-BR'. "
        "Inclua tambem script_contract com personagens essenciais, locais permitidos, objetos "
        "de payoff, beats obrigatorios, regras proibidas, tom e promessa emocional; inclua "
        "visual_contract com regras de figurino, paleta, locais, props e continuidade visual. "
        "{retry_guidance}"
    ),
    "generate_script": (
        "Crie um roteiro cinematografico profissional em {language}, no padrao de roteiro "
        "de filme, para uma historia vertical 9:16 "
        "com duracao total fixa de {target_duration_seconds}s. Use o contrato narrativo em "
        "{story_bible_contract}. A etapa de video usa Seedance 2.0 Fast, portanto os planos finais "
        "serao clipes independentes de {clip_min_seconds}s a {clip_max_seconds}s, com alvo "
        "pratico de {clip_target_seconds}s por clipe. Escreva o roteiro para sustentar "
        "aproximadamente {expected_clip_count} clipes, sem tentar colocar um plano unico "
        "mais longo que esse limite. "
        "Use formato cinematografico de filme, nao formato de documento de planejamento: "
        "titulo, FADE IN:, cenas numeradas e slugline em caixa alta "
        "no padrao INT./EXT. LOCAL - PERIODO, sem duracao na slugline, "
        "linhas de acao no presente, personagens em "
        "caixa alta na primeira aparicao, blocos de dialogo com nome do personagem em caixa "
        "alta, parenteticos apenas quando essenciais, transicoes raras como CORTE PARA: "
        "ou FADE OUT:. Nao use listas tecnicas dentro do roteiro, nao escreva 'objetivo', "
        "'personagens', 'local', 'duracao', 'storyboard', 'video', 'camera' ou "
        "'objetos narrativos' como campos aparentes. A informacao deve aparecer "
        "naturalmente em acao, imagem e dialogo. Organize em 4 a 8 cenas, "
        "com ritmo de filme: gancho visual, incidente incitante, escalada, virada central, "
        "climax e imagem final. Evite exposicao longa e descricao abstrata; cada paragrafo "
        "de acao deve ser filmavel. "
        "Tambem retorne production_plan separado do roteiro, com cenas e planos tecnicos "
        "derivados do roteiro para uso interno. Esse plano deve seguir exatamente "
        "{expected_clip_count} planos com duracoes nesta ordem: {clip_durations}. "
        "Nao misture production_plan dentro de content. {retry_guidance}"
        "Responda somente JSON neste formato exato: "
        '{{"title":"...","language":"pt-BR","target_duration_seconds":300,'
        '"word_count":650,"content":"ROTEIRO CINEMATOGRAFICO COMPLETO AQUI",'
        '"production_plan":{{"scenes":[{{"scene_number":1,"title":"...",'
        '"summary":"...","duration_seconds":45,"shots":[{{"shot_number":1,'
        '"duration_seconds":15,"narration_text":"...","dialogue_text":"",'
        '"action":"...","emotion":"...","visual_composition":"...",'
        '"camera_movement":"...","generation_type":"IMAGE_TO_VIDEO"}}]}}]}}}}'
    ),
    "generate_scenes_and_shots": (
        "Divida o roteiro em {script} em cenas e planos prontos para geracao de video "
        "vertical 9:16. A duracao total obrigatoria e {target_duration_seconds}s. "
        "A etapa de video usa Seedance 2.0 Fast: cada plano deve ter entre "
        "{clip_min_seconds}s e {clip_max_seconds}s. Use exatamente {expected_clip_count} "
        "planos com esta distribuicao de duracao, na ordem: {clip_durations}. "
        "A soma dos planos precisa ser exatamente {target_duration_seconds}s. "
        "Cenas podem agrupar varios planos; duration_seconds de cada cena deve ser a soma "
        "dos seus planos. Extraia personagens, locais, objetos, acao filmavel, narracao e "
        "dialogo de cada trecho. visual_composition deve descrever enquadramento vertical, "
        "sujeito principal, ambiente, luz, profundidade e referencia de continuidade. "
        "camera_movement deve orientar movimento realista compativel com clipe curto. "
        "action deve ser visivel, especifica e executavel em uma unica tomada curta. "
        "narration_text deve ser sempre uma string nao vazia; se nao houver narrador, use "
        "uma descricao curta da acao visual do plano. dialogue_text pode ser string vazia. "
        "Responda somente JSON neste formato exato: "
        '{{"scenes":[{{"scene_number":1,"title":"...","summary":"...",'
        '"duration_seconds":45,"shots":[{{"shot_number":1,"duration_seconds":15,'
        '"narration_text":"...","dialogue_text":"","action":"...","emotion":"...",'
        '"visual_composition":"...","camera_movement":"...","generation_type":"IMAGE_TO_VIDEO"}}]}}]}}'
    ),
    "revise_script": (
        "Revise o roteiro existente atendendo ao pedido do usuario. "
        "Preserve a continuidade da Story Bible e mantenha a duracao alvo de "
        "{target_duration_seconds}s. Pedido do usuario: {instruction}. "
        "Contexto do projeto: {project_context}. Roteiro atual: {current_script}. "
        "Mantenha formato cinematografico de filme, nao ficha tecnica: FADE IN:, "
        "cenas numeradas, sluglines INT./EXT. em caixa alta sem duracao, "
        "acao filmavel no presente, primeira aparicao de personagem em caixa alta, "
        "dialogos em bloco com nome do personagem, parenteticos raros e transicoes discretas. "
        "Nao transforme o roteiro em lista tecnica com campos de objetivo/personagens/local/"
        "duracao/storyboard/video/camera. {retry_guidance}"
        "Responda somente JSON neste formato exato: "
        '{{"title":"...","language":"pt-BR","target_duration_seconds":300,'
        '"word_count":650,"content":"ROTEIRO CINEMATOGRAFICO REVISADO COMPLETO AQUI"}}'
    ),
    "director_agent_chat": "{prompt}",
}

DEFAULT_TEMPLATE_VARIABLES: dict[str, int] = {
    "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
    "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
    "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
}


def should_fallback_to_mock(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_terms = (
        "resourceexhausted",
        "resource exhausted",
        "request limit",
        "rate limit",
        "limite",
        "429",
        "upstream error",
        "worker local total request limit",
        "temporarily unavailable",
        "overloaded",
        "timeout",
        "timed out",
        "urlerror",
        "network",
        "connection",
        "dns",
        "temporary failure",
        "remote end closed",
        "openrouter retornou resposta fora",
        "openrouter retornou resposta sem choices",
        "openrouter retornou choices fora",
        "openrouter retornou message fora",
        "openrouter retornou content vazio",
        "openrouter retornou conteudo que nao e json valido",
        "openrouter retornou json fora",
    )
    return any(term in message for term in transient_terms)


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
    fallback_on_runtime_error: bool = False,
) -> tuple[LLMResult, PromptExecution]:
    template = await get_or_create_prompt_template(session, task)
    variables = DEFAULT_TEMPLATE_VARIABLES | variables
    prompt = compile_prompt(template.template_text, variables)
    started = perf_counter()
    request = LLMRequest(
        task=task,
        prompt=prompt,
        variables=variables,
        output_schema=template.output_schema,
        model=model or "mock-llm",
    )
    fallback_error: str | None = None
    try:
        result = await provider.generate_structured(request)
    except RuntimeError as exc:
        should_fallback = fallback_on_runtime_error or should_fallback_to_mock(exc)
        if getattr(provider, "provider_name", "") == "mock" or not should_fallback:
            raise
        fallback_error = str(exc)
        result = await MockLLMProvider().generate_structured(
            LLMRequest(
                task=task,
                prompt=prompt,
                variables=variables,
                output_schema=template.output_schema,
                model="mock-llm",
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
        parameters={"fallback_from": model, "fallback_error": fallback_error}
        if fallback_error
        else {},
        estimated_cost=result.estimated_cost,
        duration_ms=duration_ms,
    )
    session.add(execution)
    await session.flush()
    return result, execution
