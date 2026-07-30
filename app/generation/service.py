import asyncio
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_model,
    validate_model_name,
)
from app.config.settings import get_settings
from app.generation.models import PromptExecution, PromptTemplate
from app.generation.prompt_compiler import compile_prompt
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
    "generate_visual_bible": "Generate Visual Bible",
    "generate_storyboard_prompts": "Generate Storyboard Prompts",
    "revise_script": "Revise Script",
    "director_agent_chat": "Director Agent Chat",
}

LLM_PROVIDER_TIMEOUT_SECONDS = 300
TASK_TIMEOUT_SECONDS: dict[str, int] = {
    "generate_story_ideas": 120,
    "generate_script": 120,
    "generate_scenes_and_shots": 120,
    "generate_visual_bible": 180,
    "generate_storyboard_prompts": 180,
    "revise_script": 120,
}
CREATIVE_NARRATIVE_TASKS = {
    "generate_story_ideas",
    "generate_script",
    "generate_scenes_and_shots",
    "generate_visual_bible",
    "generate_storyboard_prompts",
    "revise_script",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Você é uma sala de desenvolvimento narrativo com repertorio amplo. Gere tres "
        "ideias estruturadas para uma historia vertical de {target_duration_minutes} "
        "minutos. Cada ideia precisa sustentar a duração escolhida com conflito, virada e payoff. "
        "Tema: {theme}. Gênero preferido: {genre}. Publico: {audience}. "
        "Emocao: {primary_emotion}. "
        "Memoria de ideias/personagens ja usados que devem ser evitados: {diversity_memory}. "
        "As tres ideias precisam ser radicalmente diferentes entre si: mude protagonista, "
        "profissão, idade/faixa de vida, mundo social, local principal, objeto dramatico, "
        "fonte de antagonismo, tipo de segredo/revelacao, dilema moral, ritmo e imagem final. "
        "Não use a mesma péssoa com nomes diferentes. Não repita cuidadora, carta/mensagem "
        "atrasada, casa de familia, segredo do passado, heranca misteriosa ou reconciliacao "
        "familiar como motor padrão, a menos que o briefing exija explicitamente. "
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
        "Você é um roteirista cinematográfico senior e diretor de desenvolvimento "
        "narrativo. Crie um roteiro profissional em {language}, no padrão de roteiro "
        "de filme, para uma historia vertical 9:16 com duração total fixa de "
        "{target_duration_seconds}s. Use obrigatoriamente a ideia aprovada em {idea} "
        "e o contrato narrativo em {narrative_contract}. Preserve a promessa emocional "
        "da ideia, com protagonista ativo, desejo claro, conflito crescente, obstaculos "
        "concretos, virada central, climax baseado em escolha dificil e payoff emocional "
        "coerente. "
        "A duração escolhida deve orientar a profundidade: roteiros curtos precisam ser "
        "diretos, com conflito simples e payoff rapido; roteiros mais longos precisam "
        "de escalada mais rica, consequencias progressivas, virada central mais forte "
        "e desenvolvimento emocional mais gradual. Nenhuma cena deve parecer "
        "preenchimento: cada cena precisa alterar a situacao, revelar uma informacao "
        "importante ou pressionar o protagonista. "
        "Use formato cinematográfico de filme, não formato de documento de planejamento: "
        "titulo, FADE IN:, cenas numeradas e slugline em caixa alta no padrão "
        "INT./EXT. LOCAL - PERIODO, sem duração na slugline, linhas de acao no presente, "
        "personagens em caixa alta na primeira aparição, blocos de diálogo com nome do "
        "personagem em caixa alta, parenteticos apenas quando essenciais, transicoes "
        "raras como CORTE PARA: ou FADE OUT:. "
        "Formato obrigatório de quebra de linhas: FADE IN deve ficar sozinho em uma linha; "
        "cada CENA NN deve ficar sozinha em uma linha; a slugline INT./EXT. deve ficar "
        "sozinha na linha seguinte; a acao deve comecar em outro paragrafo. Nunca compacte "
        "cenas como 'FADE IN: 1. INT...' ou '2. EXT...' dentro de um paragrafo. "
        "Nunca use slugline generica como 'INT. CENA 1 - DIA'; use sempre o local real. "
        "Organize em exatamente {expected_scene_count} cenas numeradas, com "
        "desenvolvimento proporcional a duração escolhida e ritmo de filme: gancho "
        "visual imediato, incidente incitante, escalada, virada central, crise, climax "
        "e imagem final memoravel. Evite exposicao longa e descricao abstrata; cada "
        "paragrafo de acao deve ser específico, visual e filmavel. "
        "Não use narrador, narracao em off ou texto expositivo lido. A historia deve "
        "ser conduzida por conflito visivel, subtexto, gestos e interacao direta entre "
        "personagens; quando houver fala, escreva dialogos naturais com o nome do "
        "personagem em caixa alta. "
        "Não use listas técnicas dentro do roteiro, não escreva 'objetivo', "
        "'personagens', 'local', 'duração', 'storyboard', 'video', 'camera' ou "
        "'objetos narrativos' como campos aparentes dentro de content. A informacao "
        "deve aparecer naturalmente em ação, imagem e diálogo. "
        "Escreva somente o roteiro cinematográfico. Não retorne plano tecnico, "
        "production_plan, lista de shots, storyboard, camera_movement ou campos de video; "
        "a decupagem técnica será derivada em outra etapa. {retry_guidance}"
        "Responda somente JSON válido, sem markdown e sem texto fora do objeto, neste "
        "formato exato: "
        '{{"title":"...","language":"pt-BR","target_duration_seconds":300,'
        '"word_count":650,"content":"ROTEIRO CINEMATOGRAFICO COMPLETO AQUI"}}'
    ),
    "generate_scenes_and_shots": (
        "Divida o roteiro em {script} em cenas e planos prontos para geração de video "
        "vertical 9:16. A duração total obrigatoria e {target_duration_seconds}s. "
        "A etapa de video usa Veo Free: cada plano deve ter entre "
        "{clip_min_seconds}s e {clip_max_seconds}s. Use exatamente {expected_clip_count} "
        "planos com está distribuicao de duração, na ordem: {clip_durations}. "
        "A soma dos planos precisa ser exatamente {target_duration_seconds}s. "
        "Cenas podem agrupar varios planos; duration_seconds de cada cena deve ser a soma "
        "dos seus planos. Extraia personagens, locais, objetos, acao filmavel e "
        "diálogo de cada trecho. Não criar narrador nem fala em off. "
        "visual_composition deve descrever enquadramento vertical, "
        "sujeito principal, ambiente, luz, profundidade e referência de continuidade. "
        "camera_movement deve orientar movimento realista compativel com clipe curto. "
        "action deve ser visivel, especifica e executavel em uma única tomada curta. "
        "narration_text é um campo tecnico legado: preencha com uma descricao visual "
        "curta do que acontece no plano, sem texto para ser narrado. dialogue_text deve "
        "conter apenas falas de personagens; inclua o nome do personagem quando houver "
        "diálogo. Se o plano não tiver fala, dialogue_text pode ser string vazia. "
        "Responda somente JSON neste formato exato: "
        '{{"scenes":[{{"scene_number":1,"title":"...","summary":"...",'
        '"duration_seconds":45,"shots":[{{"shot_number":1,"duration_seconds":15,'
        '"narration_text":"...","dialogue_text":"","action":"...","emotion":"...",'
        '"visual_composition":"...","camera_movement":"...","generation_type":"IMAGE_TO_VIDEO"}}]}}]}}'
    ),
    "generate_visual_bible": (
        "Você é diretor de arte e prompt designer para imagens geradas por IA. "
        "A partir do roteiro em {script} e da ideia aprovada em {idea}, crie uma "
        "biblioteca visual objetiva para produção: personagens, locais e objetos. "
        "Extraia apenas itens que aparecem ou são claramente necessários no roteiro. "
        "Para cada personagem, descreva identidade visual consistente, idade aparente, "
        "gênero visual, corpo, rosto, pele, olhos, cabelo, figurino base exclusivo, "
        "paleta, papel narrativo, personalidade e arco. Para cada local, descreva "
        "função dramática, layout filmável, materiais, paleta, luz e regras espaciais. "
        "Para cada objeto, descreva importância narrativa, dimensões, material, cor, "
        "estado, dono/relação narrativa e cenas relevantes. Não gere imagens. "
        "Não use nomes genéricos como Personagem, Local ou Objeto. "
        "Os campos devem ser específicos o bastante para virarem prompts fotorrealistas "
        "de continuidade. Responda somente JSON válido, sem markdown, neste formato: "
        '{{"characters":[{{"name":"...","role":"...","gender":"personagem feminino",'
        '"apparent_age":"...","body_type":"...","face_shape":"...","skin_tone":"...",'
        '"eyes":"...","hair":"...","base_outfit":"...","palette":["..."],'
        '"personality":"...","arc":"...","scene_numbers":[1]}}],'
        '"locations":[{{"name":"...","description":"...","layout":"...",'
        '"materials":["..."],"palette":["..."],"lighting":"...",'
        '"scene_numbers":[1]}}],'
        '"props":[{{"name":"...","narrative_importance":"...","dimensions":"...",'
        '"material":"...","color":"...","state":"...","owner":"...",'
        '"scene_numbers":[1]}}]}}'
    ),
    "generate_storyboard_prompts": (
        "Você é diretor de arte cinematográfico e prompt designer para IA de imagem. "
        "Crie prompts finais de storyboard para os planos em {shots}, usando o roteiro "
        "em {script} e a biblioteca visual canonica em {visual_context}. "
        "Cada prompt será enviado a um modelo de geração de imagens, então escreva "
        "um prompt único, visual, filmável e específico para o primeiro frame de "
        "image-to-video vertical 9:16. Use continuidade rigorosa de rosto, idade, "
        "figurino, local, luz, paleta, objetos e geografia espacial. "
        "Não invente personagens, locais ou objetos fora do plano. Não inclua texto, "
        "legendas, marcas d'água, interface, balões, montagem, colagem ou split screen. "
        "Não explique o prompt e não gere imagens. "
        "Use os prompts-base em {fallback_prompts} apenas como referência de segurança, "
        "mas entregue versões mais cinematográficas, coerentes e compactas. "
        "Responda somente JSON válido, sem markdown, neste formato: "
        '{{"prompts":[{{"shot_id":"uuid-do-plano","prompt":"prompt final"}}]}}'
    ),
    "revise_script": (
        "Revise o roteiro existente atendendo ao pedido do usuario. "
        "Preserve a continuidade da ideia, dos personagens e dos ativos visuais, "
        "mantendo a duração alvo de "
        "{target_duration_seconds}s. Pedido do usuario: {instruction}. "
        "Contexto do projeto: {project_context}. Roteiro atual: {current_script}. "
        "Se o pedido citar cenas especificas por número, reescreva somente essas cenas "
        "e preserve as demais cenas com o mesmo conteúdo, ordem e numeração. Se o pedido "
        "solicitar roteiro completo, nova versão ou reescrita geral, reescreva o roteiro "
        "inteiro mantendo o contrato narrativo do projeto. "
        "Mantenha formato cinematográfico de filme, não ficha técnica: FADE IN:, "
        "cenas numeradas, sluglines INT./EXT. em caixa alta sem duração, "
        "acao filmavel no presente, primeira aparicao de personagem em caixa alta, "
        "dialogos em bloco com nome do personagem, parenteticos raros e transicoes discretas. "
        "Não adicionar narrador, narracao em off ou texto expositivo lido; preservar "
        "a historia baseada em interacao entre personagens. "
        "Não transforme o roteiro em lista técnica com campos de objetivo/personagens/local/"
        "duração/storyboard/video/camera. {retry_guidance}"
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


def _raw_response_preview(value: str | None, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


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
        "omniroute retornou resposta fora",
        "omniroute retornou resposta sem choices",
        "omniroute retornou choices fora",
        "omniroute retornou message fora",
        "omniroute retornou content vazio",
        "omniroute retornou conteúdo que não é json válido",
        "omniroute retornou json fora",
    )
    return any(term in message for term in transient_terms)


def allow_runtime_mock_fallback(task: str, requested: bool) -> bool:
    _ = task, requested
    return False


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
    timeout_seconds = min(
        TASK_TIMEOUT_SECONDS.get(task, LLM_PROVIDER_TIMEOUT_SECONDS),
        LLM_PROVIDER_TIMEOUT_SECONDS,
    )
    request = LLMRequest(
        task=task,
        prompt=prompt,
        variables=variables,
        output_schema=template.output_schema,
        model=validate_model_name(
            model
            or provider_model(
                get_settings(),
                effective_provider_for_channel(get_settings(), "text"),
                "text",
            )
        ),
        timeout_seconds=timeout_seconds,
    )
    fallback_error: str | None = None
    try:
        if getattr(provider, "provider_name", "") == "mock":
            raise ValueError(
                "Provider mock bloqueado. Configure um modelo real de IA."
            )
        provider_call = provider.generate_structured(request)
        result = await asyncio.wait_for(
            provider_call,
            timeout=timeout_seconds,
        )
    except (RuntimeError, TimeoutError, ValueError) as exc:
        if isinstance(exc, TimeoutError):
            exc = RuntimeError(
                f"Provider demorou mais de {timeout_seconds}s na tarefa {task}"
            )
        _ = fallback_on_runtime_error, should_fallback_to_mock(exc)
        raise exc
    duration_ms = int((perf_counter() - started) * 1000)
    parameters: dict[str, str] = {}
    if fallback_error:
        if model is not None:
            parameters["fallback_from"] = model
        parameters["fallback_error"] = fallback_error
    if result.recovery_strategy:
        parameters["recovery_strategy"] = result.recovery_strategy
    if result.recovery_strategy and result.raw_content:
        parameters["raw_response_preview"] = _raw_response_preview(result.raw_content)
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
        parameters=parameters,
        estimated_cost=result.estimated_cost,
        duration_ms=duration_ms,
    )
    session.add(execution)
    await session.flush()
    return result, execution
