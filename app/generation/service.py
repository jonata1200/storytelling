import asyncio
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
    "generate_script": "Generate Script",
    "generate_scenes_and_shots": "Generate Scenes And Shots",
    "revise_script": "Revise Script",
    "director_agent_chat": "Director Agent Chat",
}

LLM_PROVIDER_TIMEOUT_SECONDS = 60
CREATIVE_NARRATIVE_TASKS = {
    "generate_story_ideas",
    "generate_script",
    "generate_scenes_and_shots",
    "revise_script",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Voce e uma sala de desenvolvimento narrativo com repertorio amplo. Gere tres "
        "ideias estruturadas para uma historia vertical de {target_duration_minutes} "
        "minutos. Cada ideia precisa sustentar a duracao escolhida com conflito, virada e payoff. "
        "Tema: {theme}. Genero preferido: {genre}. Publico: {audience}. "
        "Emocao: {primary_emotion}. "
        "Memoria de ideias/personagens ja usados que devem ser evitados: {diversity_memory}. "
        "As tres ideias precisam ser radicalmente diferentes entre si: mude protagonista, "
        "profissao, idade/faixa de vida, mundo social, local principal, objeto dramatico, "
        "fonte de antagonismo, tipo de segredo/revelacao, dilema moral, ritmo e imagem final. "
        "Nao use a mesma pessoa com nomes diferentes. Nao repita cuidadora, carta/mensagem "
        "atrasada, casa de familia, segredo do passado, heranca misteriosa ou reconciliacao "
        "familiar como motor padrao, a menos que o briefing exija explicitamente. "
        "Antes de responder, descarte mentalmente qualquer ideia que compartilhe protagonista, "
        "conflito, twist ou payoff com outra. "
        "Cada ideia deve deixar claro conflito, obstaculos, stakes, twist, climax, payoff "
        "e resolucao para que o roteiro consiga preservar a proposta original. "
        "{retry_guidance}"
        "Responda somente JSON neste formato: "
        '{{"ideas":[{{"title":"...","genre":"...","primary_emotion":"...",'
        '"theme":"...","hook":"...","premise":"...","protagonist":"...",'
        '"conflict":"...","obstacles":["..."],"stakes":"...","twist":"...",'
        '"climax":"...","payoff":"...","resolution":"...",'
        '"duration_minutes":5,"retention_potential":80,"cliche_risk":20,'
        '"production_complexity":35}}]}}'
    ),
    "generate_script": (
        "Voce e um roteirista cinematografico senior e diretor de desenvolvimento "
        "narrativo. Crie um roteiro profissional em {language}, no padrao de roteiro "
        "de filme, para uma historia vertical 9:16 com duracao total fixa de "
        "{target_duration_seconds}s. Use obrigatoriamente a ideia aprovada em {idea} "
        "e o contrato narrativo em {narrative_contract}. Preserve a promessa emocional "
        "da ideia, com protagonista ativo, desejo claro, conflito crescente, obstaculos "
        "concretos, virada central, climax baseado em escolha dificil e payoff emocional "
        "coerente. "
        "A duracao escolhida deve orientar a profundidade: roteiros curtos precisam ser "
        "diretos, com conflito simples e payoff rapido; roteiros mais longos precisam "
        "de escalada mais rica, consequencias progressivas, virada central mais forte "
        "e desenvolvimento emocional mais gradual. Nenhuma cena deve parecer "
        "preenchimento: cada cena precisa alterar a situacao, revelar uma informacao "
        "importante ou pressionar o protagonista. "
        "Use formato cinematografico de filme, nao formato de documento de planejamento: "
        "titulo, FADE IN:, cenas numeradas e slugline em caixa alta no padrao "
        "INT./EXT. LOCAL - PERIODO, sem duracao na slugline, linhas de acao no presente, "
        "personagens em caixa alta na primeira aparicao, blocos de dialogo com nome do "
        "personagem em caixa alta, parenteticos apenas quando essenciais, transicoes "
        "raras como CORTE PARA: ou FADE OUT:. "
        "Organize em exatamente {expected_scene_count} cenas numeradas, com "
        "desenvolvimento proporcional a duracao escolhida e ritmo de filme: gancho "
        "visual imediato, incidente incitante, escalada, virada central, crise, climax "
        "e imagem final memoravel. Evite exposicao longa e descricao abstrata; cada "
        "paragrafo de acao deve ser especifico, visual e filmavel. "
        "Nao use listas tecnicas dentro do roteiro, nao escreva 'objetivo', "
        "'personagens', 'local', 'duracao', 'storyboard', 'video', 'camera' ou "
        "'objetos narrativos' como campos aparentes dentro de content. A informacao "
        "deve aparecer naturalmente em acao, imagem e dialogo. "
        "A etapa de video usa Seedance 2.0 Fast, portanto os planos finais serao "
        "clipes independentes de {clip_min_seconds}s a {clip_max_seconds}s, com alvo "
        "pratico de {clip_target_seconds}s por clipe. Escreva o roteiro para sustentar "
        "aproximadamente {expected_clip_count} clipes, sem tentar colocar um plano unico "
        "mais longo que esse limite. "
        "Tambem retorne production_plan separado do roteiro, com cenas e planos tecnicos "
        "derivados diretamente do roteiro para uso interno. Esse plano deve seguir "
        "exatamente {expected_clip_count} planos com duracoes nesta ordem: "
        "{clip_durations}. Cada plano deve conter acao visual, emocao, composicao "
        "vertical, movimento de camera e texto de narracao ou dialogo quando houver. "
        "Nao misture production_plan dentro de content. {retry_guidance}"
        "Responda somente JSON valido, sem markdown e sem texto fora do objeto, neste "
        "formato exato: "
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
        "Preserve a continuidade da ideia, dos personagens e dos ativos visuais, "
        "mantendo a duracao alvo de "
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


def allow_runtime_mock_fallback(task: str, requested: bool) -> bool:
    if not requested:
        return False
    return task not in CREATIVE_NARRATIVE_TASKS


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
        provider_call = provider.generate_structured(request)
        if getattr(provider, "provider_name", "") == "mock":
            result = await provider_call
        else:
            result = await asyncio.wait_for(
                provider_call,
                timeout=LLM_PROVIDER_TIMEOUT_SECONDS,
            )
    except (RuntimeError, TimeoutError) as exc:
        if isinstance(exc, TimeoutError):
            exc = RuntimeError(
                f"Provider demorou mais de {LLM_PROVIDER_TIMEOUT_SECONDS}s"
            )
        should_fallback = allow_runtime_mock_fallback(
            task, fallback_on_runtime_error or should_fallback_to_mock(exc)
        )
        if getattr(provider, "provider_name", "") == "mock" or not should_fallback:
            raise exc
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
