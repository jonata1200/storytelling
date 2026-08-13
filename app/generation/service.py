import asyncio
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import (
    SUPPORTED_TEXT_PROVIDERS,
    effective_provider_for_channel,
    normalize_provider_name,
    provider_model,
    validate_model_name,
)
from app.config.settings import get_settings
from app.generation.models import PromptExecution, PromptTemplate
from app.generation.prompt_compiler import compile_prompt
from app.observability.models import OperationalEvent
from app.observability.redaction import redact_secrets
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

LLM_PROVIDER_TIMEOUT_SECONDS = 180
TASK_TIMEOUT_SECONDS: dict[str, int] = {
    "generate_story_ideas": 75,
    "generate_script": 180,
    "generate_scenes_and_shots": 180,
    "generate_visual_bible": 180,
    "generate_storyboard_prompts": 180,
    "revise_script": 180,
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
        "Você é uma sala de desenvolvimento narrativo com repertorio amplo. Gere duas "
        "ideias estruturadas para uma historia vertical de {target_duration_minutes} "
        "minutos. Cada ideia precisa sustentar a duração escolhida com conflito, virada e payoff. "
        "Tema: {theme}. Gênero preferido: {genre}. Publico: {audience}. "
        "Emocao: {primary_emotion}. "
        "Memoria de ideias/personagens ja usados que devem ser evitados: {diversity_memory}. "
        "As duas ideias precisam ser radicalmente diferentes entre si: mude protagonista, "
        "profissão, idade/faixa de vida, mundo social, local principal, objeto dramatico, "
        "fonte de antagonismo, tipo de segredo/revelacao, dilema moral, ritmo e imagem final. "
        "Não use a mesma péssoa com nomes diferentes. Não repita cuidadora, carta/mensagem "
        "atrasada, casa de familia, segredo do passado, heranca misteriosa ou reconciliacao "
        "familiar como motor padrão, a menos que o briefing exija explicitamente. "
        "Antes de responder, descarte mentalmente qualquer ideia que compartilhe protagonista, "
        "conflito, twist ou payoff com outra. "
        "Prefira duas opções fortes e baratas de avaliar em vez de muitas variações medianas. "
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
        "coerente. Antes de escrever, defina mentalmente os nomes canonicos dos "
        "personagens a partir de narrative_contract.characters; use esses nomes nos "
        "blocos de dialogo. Nunca use nomes de locais, cenarios ou sluglines como cue "
        "de dialogo: SALA, CASA, HOSPITAL, RUA, QUARTO e similares são lugares, não "
        "personagens. "
        "A duração escolhida deve orientar a profundidade: roteiros curtos precisam ser "
        "diretos, com conflito simples e payoff rapido; roteiros mais longos precisam "
        "de escalada mais rica, consequencias progressivas, virada central mais forte "
        "e desenvolvimento emocional mais gradual. Nenhuma cena deve parecer "
        "preenchimento: cada cena precisa alterar a situacao, revelar uma informacao "
        "importante ou pressionar o protagonista. Escreva para alta retenção emocional: "
        "comece com uma imagem-problema forte, plante uma pergunta dramática clara, "
        "faça cada cena terminar com uma nova pressão ou revelação, e construa um "
        "payoff que mude a forma como a audiência entende o protagonista. "
        "Use formato cinematográfico de filme, não formato de documento de planejamento: "
        "titulo, FADE IN:, cenas numeradas e slugline em caixa alta no padrão "
        "INT./EXT. LOCAL - PERIODO, sem duração na slugline, linhas de acao no presente, "
        "personagens em caixa alta na primeira aparição, blocos de diálogo com nome do "
        "personagem em caixa alta e transicoes raras como CORTE PARA: ou FADE OUT:. "
        "Não use parentéticos no roteiro: nunca escreva indicações entre parênteses, "
        "nem sufixos no nome do personagem como (CONT.), (V.O.) ou (O.S.). "
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
        "personagem em caixa alta. A linha acima de uma fala deve conter apenas o nome "
        "da pessoa que fala, sem qualquer texto entre parênteses; se não houver "
        "personagem falando, escreva a informação como ação visual, não como diálogo. "
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
        "A etapa de video usa Veo 3.1 Lite: cada plano deve ter exatamente 4s, 6s "
        "ou 8s. Use exatamente {expected_clip_count} "
        "planos com está distribuicao de duração, na ordem: {clip_durations}. "
        "A soma dos planos precisa ser exatamente {target_duration_seconds}s. "
        "Priorize menos planos e ações mais claras quando houver escolha; não divida uma "
        "mesma ação simples em varios planos se um único clipe resolve. "
        "Cenas podem agrupar varios planos; duration_seconds de cada cena deve ser a soma "
        "dos seus planos. Extraia personagens, locais, objetos, acao filmavel e "
        "diálogo de cada trecho. Não criar narrador nem fala em off. "
        "Para cada cena, crie spatial_layout como um mapa espacial continuo: onde cada "
        "personagem fica, quem esta a esquerda/direita, onde estao mesa, portas, janelas, "
        "objetos importantes e fundo. Para planos consecutivos da mesma cena, nunca inverta "
        "posicoes de personagens, direcao de olhar ou lado da tela sem uma acao clara de "
        "deslocamento dentro do roteiro. "
        "visual_composition deve descrever enquadramento vertical, "
        "sujeito principal, ambiente, luz, profundidade, lado da tela e referência de "
        "continuidade espacial. "
        "spatial_continuity de cada plano deve explicar como o quadro preserva o mapa "
        "espacial da cena: posicao relativa dos personagens, distancia entre eles, "
        "objetos na mesa/maos, direcao de olhar e eixo de camera. "
        "camera_movement deve orientar movimento realista compativel com clipe curto. "
        "action deve ser visivel, especifica e executavel em uma única tomada curta. "
        "Rejeite ações abstratas como 'percebe a verdade' ou 'sente saudade'; converta "
        "em gesto, olhar, deslocamento, manipulação de objeto ou interação filmável. "
        "Marque objetos apenas quando tiverem função narrativa clara no plano. "
        "narration_text é um campo tecnico legado: preencha com uma descricao visual "
        "curta do que acontece no plano, sem texto para ser narrado. dialogue_text deve "
        "conter apenas falas de personagens; inclua o nome do personagem quando houver "
        "diálogo. Se o plano não tiver fala, dialogue_text pode ser string vazia. "
        "Responda somente JSON neste formato exato: "
        '{{"scenes":[{{"scene_number":1,"title":"...","summary":"...",'
        '"spatial_layout":"...","duration_seconds":24,'
        '"shots":[{{"shot_number":1,"duration_seconds":8,'
        '"narration_text":"...","dialogue_text":"","action":"...","emotion":"...",'
        '"visual_composition":"...","spatial_continuity":"...",'
        '"camera_movement":"...","generation_type":"IMAGE_TO_VIDEO"}}]}}]}}'
    ),
    "generate_visual_bible": (
        "Você é diretor de arte e prompt designer para imagens geradas por IA. "
        "A partir do roteiro em {script} e da ideia aprovada em {idea}, crie uma "
        "biblioteca visual objetiva para produção: personagens, locais e objetos. "
        "Extraia apenas itens que aparecem ou são claramente necessários no roteiro. "
        "Não transforme marcadores estruturais em entidades: FIM, EPÍLOGO, PRÓLOGO, "
        "ATO, CENA, IMAGEM FINAL, FADE IN/OUT e transições nunca são personagens, "
        "locais nem objetos. "
        "Personagens devem ser pessoas, criaturas ou vozes com presença dramática; "
        "inclua apenas nomes que aparecem como fala, apresentação em ação ou elenco "
        "da ideia aprovada. Nunca inclua como personagem entidades sem corpo físico: "
        "narrador, narração em off, observador externo, inteligência artificial, "
        "sistema ou voz sem corpo visível; se uma IA ou voz se manifesta por um "
        "aparelho físico (celular, caixa de som, painel, alto-falante), registre "
        "apenas esse aparelho como objeto narrativo, nunca a entidade em si. "
        "Nunca crie personagens para grupos, equipes ou coletivos de pessoas: equipe, "
        "turma, time, bando, gangue, multidão, público, plateia, casal, família, irmãos, "
        "amigos, vizinhos, colegas, policiais, soldados, guardas, membros, funcionários "
        "ou qualquer nome que represente um conjunto; se um grupo importa, registre "
        "apenas os indivíduos nomeados individualmente. "
        "Locais devem vir de sluglines ou ambientes filmáveis reais. "
        "O nome do local deve ser só o ambiente físico, nunca uma indicação temporal "
        "ou transição; por exemplo, use 'Sala de Segurança do Museu' em vez de "
        "'Momentos depois do museu sala de segurança'. "
        "Todos os valores textuais visiveis ao usuario devem ficar 100% em portugues "
        "do Brasil; as chaves JSON em ingles sao apenas schema interno e nao devem "
        "contaminar descricoes, nomes, prompts ou evidencias. "
        "Liste no máximo 6 objetos, somente os principais da história: itens que um "
        "personagem manipula/usa/lê/entrega/esconde/revela, que recebem destaque claro "
        "em cena, reaparecem ou sustentam payoff. Se um objeto é proeminente na história, "
        "ele deve estar na lista mesmo que a ação com ele seja indireta ou o destaque seja "
        "descritivo. Não crie imagem isolada para cada "
        "item citado no ambiente. Objetos devem ser narrativos; não liste decoração comum como "
        "almofada, abajur, parede, cama, porta ou mesa sem função dramática explícita. "
        "O nome de cada objeto deve representar um único item isolável para imagem, "
        "sem ação, posição, esconderijo ou outro objeto no nome; por exemplo, use "
        "'Chave' em vez de 'Chave escondida atrás de um quadro'. "
        "Faça deduplicação antes de responder: una aliases e variações do mesmo item "
        "narrativo, como carta/envelope/bilhete, celular/telefone ou casa/sala da mesma "
        "família quando forem a mesma entidade de produção. "
        "Classifique mentalmente itens como obrigatórios quando aparecem em storyboards "
        "prováveis ou sustentam ação/payoff; itens decorativos e opcionais devem ficar fora. "
        "Para cada item, preencha scene_numbers e evidence_text com um trecho curto "
        "literal do roteiro que comprove a extração. "
        "Para cada personagem, descreva identidade visual consistente, idade aparente, "
        "gênero visual, corpo, rosto, pele, olhos, cabelo, figurino base exclusivo, "
        "paleta, papel narrativo, personalidade e arco. Para cada local, descreva "
        "função dramática, organizacao espacial filmável, materiais, paleta, luz e "
        "regras espaciais. "
        "Para cada objeto, descreva importância narrativa, dimensões, material, cor, "
        "estado, dono/relação narrativa e cenas relevantes. Não gere imagens. "
        "Não use nomes genéricos como Personagem, Local ou Objeto. "
        "Os campos devem ser específicos o bastante para virarem prompts fotorrealistas "
        "de continuidade. Responda somente JSON válido, sem markdown, neste formato: "
        '{{"characters":[{{"name":"...","role":"...","gender":"personagem feminino",'
        '"apparent_age":"...","body_type":"...","face_shape":"...","skin_tone":"...",'
        '"eyes":"...","hair":"...","base_outfit":"...","palette":["..."],'
        '"personality":"...","arc":"...","scene_numbers":[1],"evidence_text":["..."]}}],'
        '"locations":[{{"name":"...","description":"...","layout":"...",'
        '"materials":["..."],"palette":["..."],"lighting":"...",'
        '"scene_numbers":[1],"evidence_text":["..."]}}],'
        '"props":[{{"name":"...","narrative_importance":"...","dimensions":"...",'
        '"material":"...","color":"...","state":"...","owner":"...",'
        '"scene_numbers":[1],"evidence_text":["..."]}}]}}'
    ),
    "generate_storyboard_prompts": (
        "Você é diretor de arte cinematográfico e prompt designer para IA de imagem. "
        "Crie prompts finais de storyboard para os planos em {shots}, usando o roteiro "
        "em {script} e a biblioteca visual canonica em {visual_context}. "
        "Cada prompt será enviado a um modelo de geração de imagens, então escreva "
        "um prompt único, visual, filmável e específico para o primeiro frame de "
        "video a partir de imagem vertical 9:16. Escreva todos os prompts 100% em "
        "portugues do Brasil. O estilo global deve ser sempre fotorrealista, "
        "cinematográfico com atores reais e fiel às referências canônicas da biblioteca visual. "
        "Use continuidade rigorosa de rosto, idade, cabelo, figurino, local, luz, "
        "paleta, objetos, materiais, escala, blocking e geografia espacial. "
        "Para cada scene_number, trate spatial_layout como mapa fixo de cena: preserve "
        "quem fica a esquerda/direita, quem esta sentado/de pe, distancia entre personagens, "
        "objetos nas maos/mesa, direcao de olhar, eixo de camera e fundo. A camera pode "
        "mudar de plano, mas os personagens nao podem teleportar, trocar de lado ou mudar "
        "postura sem acao visivel que justifique. "
        "Não invente personagens, locais ou objetos fora do plano. Não inclua texto, "
        "legendas, marcas d'água, interface, balões, montagem, colagem ou tela dividida. "
        "Não use desenho, animação, desenho caricato, anime, quadrinhos, renderizacao 3D, pintura, "
        "arte conceitual ou estética ilustrada. "
        "Não explique o prompt e não gere imagens. "
        "Use os prompts-base em {fallback_prompts} apenas como referência de segurança, "
        "mas entregue versões mais cinematográficas, coerentes e compactas. "
        "Responda somente JSON válido, sem markdown, neste formato: "
        '{{"prompts":[{{"shot_id":"uuid-do-plano","prompt":"prompt final"}}]}}'
    ),
    "revise_script": (
        "Revise o roteiro existente atendendo ao pedido do usuario. "
        "Preserve a continuidade da ideia, dos personagens e dos ativos visuais, "
        "mas ajuste tamanho e duração quando o pedido solicitar. Roteiro atual: "
        "{current_duration_seconds}s e {current_word_count} palavras. Meta desta revisão: "
        "{revision_target_duration_seconds}s e aproximadamente {revision_target_word_count} "
        "palavras. {revision_sizing_guidance} Pedido do usuario: {instruction}. "
        "Contexto do projeto: {project_context}. Roteiro atual: {current_script}. "
        "Se o pedido citar cenas especificas por número, reescreva somente essas cenas "
        "e preserve as demais cenas com o mesmo conteúdo, ordem e numeração. Se o pedido "
        "solicitar roteiro completo, nova versão ou reescrita geral, reescreva o roteiro "
        "inteiro mantendo o contrato narrativo do projeto. Antes de reescrever, classifique "
        "mentalmente o pedido como local ou global; para pedido local, faça a menor alteração "
        "possível e preserve tudo que não foi solicitado. "
        "Mantenha formato cinematográfico de filme, não ficha técnica: FADE IN:, "
        "cenas numeradas, sluglines INT./EXT. em caixa alta sem duração, "
        "acao filmavel no presente, primeira aparicao de personagem em caixa alta, "
        "dialogos em bloco com nome do personagem e transicoes discretas. "
        "Não use parentéticos no roteiro: nunca escreva indicações entre parênteses, "
        "nem sufixos no nome do personagem como (CONT.), (V.O.) ou (O.S.). "
        "Nos blocos de dialogo, a cue deve ser sempre o nome de uma pessoa/personagem, "
        "nunca o nome de um local, cenario ou slugline como CASA, SALA, RUA, HOSPITAL "
        "ou QUARTO. Preserve ou corrija nomes canonicos dos personagens quando revisar. "
        "Melhore a força dramatica: cada cena revisada deve ganhar pressão, subtexto, "
        "conflito visivel e consequência emocional, sem virar explicação. "
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


def should_fallback_to_text_provider(exc: Exception) -> bool:
    message = str(exc).lower()
    if isinstance(exc, ValueError):
        return False
    non_transient_terms = (
        "_api_key",
        "api key",
        "chave",
        "não configurada",
        "nao configurada",
        "json válido",
        "json valido",
        "json fora",
        "conteúdo que não é json",
        "conteudo que nao e json",
        "empty field",
        "schema",
        "mock bloqueado",
    )
    if any(term in message for term in non_transient_terms):
        return False
    transient_terms = (
        "http 429",
        " 429",
        "rate limit",
        "quota",
        "resource exhausted",
        "resourceexhausted",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "5xx",
        "timeout",
        "timed out",
        "network",
        "connection",
        "urlerror",
        "dns",
        "temporary failure",
        "temporarily unavailable",
        "remote end closed",
        "overloaded",
    )
    return any(term in message for term in transient_terms)


def text_provider_fallback_names(settings: object, primary_provider: str) -> list[str]:
    configured = str(getattr(settings, "text_provider_fallbacks", "") or "")
    primary = str(primary_provider or "").strip().casefold()
    names: list[str] = []
    for raw_name in configured.split(","):
        name = raw_name.strip().casefold()
        if not name:
            continue
        try:
            normalized = normalize_provider_name(
                name,
                "TEXT_PROVIDER_FALLBACKS",
                SUPPORTED_TEXT_PROVIDERS,
            )
        except ValueError:
            continue
        if normalized == primary or normalized in names:
            continue
        names.append(normalized)
    return names


async def get_or_create_prompt_template(session: AsyncSession, task: str) -> PromptTemplate:
    result = await session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task == task, PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.version.desc())
    )
    default_text = DEFAULT_TEMPLATES.get(task)
    template = result.scalars().first()
    if template is not None:
        default_name = DEFAULT_TEMPLATE_NAMES.get(task, task.replace("_", " ").title())
        if (
            default_text is not None
            and template.name == default_name
            and template.template_text != default_text
        ):
            template.template_text = default_text
            template.output_schema = {}
            template.version += 1
            await session.flush()
        return template

    template = PromptTemplate(
        name=DEFAULT_TEMPLATE_NAMES.get(task, task.replace("_", " ").title()),
        task=task,
        version=1,
        template_text=default_text or "{prompt}",
        output_schema={},
        active=True,
    )
    session.add(template)
    await session.flush()
    return template


def _build_llm_request(
    *,
    task: str,
    prompt: str,
    variables: dict,
    output_schema: dict,
    model: str,
    timeout_seconds: float,
    provider_name: str | None = None,
) -> LLMRequest:
    return LLMRequest(
        task=task,
        prompt=prompt,
        variables=variables,
        output_schema=output_schema,
        model=validate_model_name(model, provider=provider_name),
        timeout_seconds=timeout_seconds,
    )


async def _generate_with_timeout(
    provider: LLMProvider,
    request: LLMRequest,
    *,
    task: str,
    timeout_seconds: float,
) -> LLMResult:
    # Fallback para mock desativado por design (chaves e qualidade): provedores mock-*
    # são bloqueados em runtime mesmo se solicitados (ver docs/04 item 4.6).
    if getattr(provider, "provider_name", "") == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")
    try:
        return await asyncio.wait_for(
            provider.generate_structured(request),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"Provider demorou mais de {timeout_seconds}s na tarefa {task}"
        ) from exc


def _record_text_provider_failure(
    session: AsyncSession,
    *,
    project_id: UUID,
    artifact_id: UUID | None,
    task: str,
    provider_name: str,
    model: str,
    exc: Exception,
) -> None:
    session.add(
        OperationalEvent(
            project_id=project_id,
            artifact_id=artifact_id,
            event_type="text_provider_failure",
            status="failed",
            actor="system",
            provider=provider_name,
            model=model,
            operation=task,
            message=redact_secrets(exc),
            details={
                "fallback_candidate": provider_name,
                "error": redact_secrets(exc),
            },
        )
    )


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
    settings = get_settings()
    primary_provider = str(
        getattr(provider, "provider_name", "")
        or effective_provider_for_channel(settings, "text")
    ).strip().casefold()
    primary_model = validate_model_name(
        model or provider_model(settings, primary_provider, "text"),
        provider=primary_provider or None,
    )
    request = _build_llm_request(
        task=task,
        prompt=prompt,
        variables=variables,
        output_schema=template.output_schema,
        model=primary_model,
        timeout_seconds=timeout_seconds,
        provider_name=primary_provider or None,
    )
    fallback_attempts: list[dict[str, str]] = []
    final_provider = primary_provider
    final_model = primary_model
    try:
        result = await _generate_with_timeout(
            provider,
            request,
            task=task,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, TimeoutError, ValueError) as exc:
        if not (
            fallback_on_runtime_error
            and should_fallback_to_text_provider(exc)
            and text_provider_fallback_names(settings, primary_provider)
        ):
            raise exc
        _record_text_provider_failure(
            session,
            project_id=project_id,
            artifact_id=artifact_id,
            task=task,
            provider_name=primary_provider,
            model=primary_model,
            exc=exc,
        )
        fallback_attempts.append(
            {
                "provider": primary_provider,
                "model": primary_model,
                "error": redact_secrets(exc),
            }
        )
        from app.generation.model_settings import llm_provider_for_name

        last_error: Exception = exc
        for fallback_provider_name in text_provider_fallback_names(settings, primary_provider):
            try:
                fallback_provider = llm_provider_for_name(settings, fallback_provider_name)
                fallback_model = validate_model_name(
                    provider_model(settings, fallback_provider_name, "text"),
                    provider=fallback_provider_name,
                )
                fallback_request = _build_llm_request(
                    task=task,
                    prompt=prompt,
                    variables=variables,
                    output_schema=template.output_schema,
                    model=fallback_model,
                    timeout_seconds=timeout_seconds,
                    provider_name=fallback_provider_name,
                )
                result = await _generate_with_timeout(
                    fallback_provider,
                    fallback_request,
                    task=task,
                    timeout_seconds=timeout_seconds,
                )
                final_provider = fallback_provider_name
                final_model = fallback_model
                break
            except (RuntimeError, TimeoutError, ValueError) as fallback_exc:
                last_error = fallback_exc
                fallback_attempts.append(
                    {
                        "provider": fallback_provider_name,
                        "model": provider_model(settings, fallback_provider_name, "text"),
                        "error": redact_secrets(fallback_exc),
                    }
                )
                _record_text_provider_failure(
                    session,
                    project_id=project_id,
                    artifact_id=artifact_id,
                    task=task,
                    provider_name=fallback_provider_name,
                    model=provider_model(settings, fallback_provider_name, "text"),
                    exc=fallback_exc,
                )
                if not should_fallback_to_text_provider(fallback_exc):
                    break
        else:
            raise last_error

        if final_provider == primary_provider:
            raise last_error from None
    duration_ms = int((perf_counter() - started) * 1000)
    parameters: dict[str, Any] = {}
    if fallback_attempts:
        parameters["primary_provider"] = primary_provider
        parameters["primary_model"] = primary_model
        parameters["final_provider"] = final_provider
        parameters["final_model"] = final_model
        parameters["fallback_attempts"] = fallback_attempts
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
