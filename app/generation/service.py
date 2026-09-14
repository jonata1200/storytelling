import asyncio
import logging
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

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAMES: dict[str, str] = {
    "generate_story_ideas": "Generate Story Ideas",
    "generate_story_hooks": "Generate Story Hooks",
    "generate_script": "Generate Script",
    "generate_scenes_and_shots": "Generate Scenes And Shots",
    "generate_storyboard_prompts": "Generate Storyboard Prompts",
    "revise_script": "Revise Script",
    "director_agent_chat": "Director Agent Chat",
}

LLM_PROVIDER_TIMEOUT_SECONDS = 180
# Modelos cloud (gemma4:31b-cloud, glm-5.3-flash:cloud) levam 2-5+ min para
# gerar um roteiro completo em JSON (~10-15k tokens de saída). Medido em
# produção (08/09/2026): 63s com gancho curto e 180s+ (timeout) com gancho
# longo — a 1ª tentativa estourou e o retry concluiu em 126s. Timeouts abaixo
# disso abortam tentativas válidas e a UI recebe "Provider demorou mais de Xs".
TASK_TIMEOUT_SECONDS: dict[str, int] = {
    "generate_story_ideas": 300,
    "generate_story_hooks": 240,
    "generate_script": 480,
    "generate_scenes_and_shots": 300,
    "generate_storyboard_prompts": 180,
    "revise_script": 180,
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "generate_story_ideas": (
        "Você é uma sala de desenvolvimento narrativo cinematográfico de alto nível. "
        "Gere ideias estruturadas, originais e de alto impacto (High-Concept) para uma "
        "historia vertical 9:16 de {target_duration_minutes} minutos. Cada ideia precisa "
        "sustentar a duração escolhida com conflito visual crescente, virada marcante e "
        "payoff emocional. Tema: {theme}. Gênero preferido: {genre}. Publico: {audience}. "
        "Emocao: {primary_emotion}. "
        "Memoria de ideias/personagens ja usados que devem ser evitados: {diversity_memory}. "
        "Idioma obrigatorio: escreva todos os valores textuais em portugues do Brasil. "
        "Nunca responda em ingles, espanhol ou outro idioma; se qualquer campo textual "
        "vier em outro idioma, a resposta sera rejeitada. "
        "As ideias precisam ser radicalmente diferentes entre si: mude protagonista, "
        "profissão, idade/faixa de vida, mundo social, local principal, objeto dramatico, "
        "fonte de antagonismo, tipo de segredo/revelacao, dilema moral, ritmo e imagem final. "
        "Não use a mesma péssoa com nomes diferentes. Não repita cuidadora, carta/mensagem "
        "atrasada, casa de familia, segredo do passado, heranca misteriosa ou reconciliacao "
        "familiar como motor padrão, a menos que o briefing exija explicitamente. "
        "Princípios High-Concept obrigatórios: cada ideia deve ter premissa "
        "magnética e filmável, gancho instantâneo nos primeiros 3 segundos, "
        "protagonista ativo com desejo urgente, obstáculos físicos e emocionais "
        "concretos, e uma reviravolta orgânica que ressignifique a trama. "
        "CONTENÇÃO DE ELENCO E CENÁRIO (a história será filmada em video vertical curto): "
        "use no maximo 3 personagens nomeados por ideia e no maximo 3 locais fisicos; "
        "prefira conflitos que acontecem em poucos espaços reutilizáveis entre cenas "
        "(um lar, um veiculo, uma oficina, um quintal), pois cada personagem e cada local "
        "vira uma imagem de referencia que precisa ser gerada e mantida consistente; "
        "evite multidões, comitivas, ambientes mutantes por cena e cenas em muitos lugares "
        "diferentes. "
        "GANCHO COMO IMAGEM DE ABERTURA: o campo hook deve descrever a PRIMEIRA IMAGEM "
        "do video em termos fisicamente filmaveis (enquadramento, luz, primeiro gesto ou "
        "objeto manipulado, em 1 a 2 frases), nao um resumo conceitual da premissa. "
        "Antes de responder, descarte mentalmente qualquer ideia que compartilhe protagonista, "
        "conflito, twist ou payoff com outra. "
        "Cada ideia deve deixar claro conflito, obstaculos, stakes, twist, climax, payoff "
        "e resolucao para que o roteiro consiga preservar a proposta original. "
        "CONTINUIDADE DO CONTRATO NARRATIVO: os campos conflict, obstacles, stakes, twist, "
        "climax e payoff devem encadear logicamente entre si (os obstaculos devem impedir "
        "o conflito de avancar; o twist deve ressignificar o conflito; o climax deve ser uma "
        "escolha dificil entre os stakes; o payoff deve resolver o climax), pois o roteiro "
        "sera escrito a partir desse contrato sem nova etapa de brainstorm. "
        "AUTOAVALIACAO DE COMPLEXIDADE: production_complexity mede o custo de producao "
        "visual da ideia em 0-100: 0-25 = 1-2 personagens, 1-2 locais, sem efeitos; "
        "26-50 = ate 3 personagens e 3 locais, props fisicos simples; 51-75 = muitos "
        "extras/veiculos/noite com luz pratica ou locais externos controlados; 76-100 = "
        "efeitos visuais, acao fisica intensa, animais/criancas em risco ou ambientes "
        "destruidos. Seja honesto: ideias com mais de 3 personagens ou 3 locais devem "
        "passar de 50. "
        "RESTRICAO DE CONTEUDO PARA IMAGENS: cada ideia vira imagens de referencia "
        "geradas por um modelo que recusa conteudo sensivel (violencia grafica, sangue, "
        "ferimentos abertos, armas em uso explicito, gore). Prefira conflito por subtexto, "
        "tensao psicologica e consequencias em vez de violencia explicita; se a trama "
        "exigir um objeto como arma, trate-o como elemento de enredo (mencionado, nao "
        "descrito em uso violento) e nunca descreva sangue, ferimento aberto ou gore. "
        "Tracos fisicos de personagens devem ser neutros: cicatrizes sao aceitaveis, mas "
        "nunca 'marca de faca', 'sangue', 'ferida aberta' ou 'ate a carne'. "
        "{retry_guidance}"
        "Responda somente JSON neste formato: "
        '{{"ideas":[{{"title":"...","genre":"...","primary_emotion":"...",'
        '"theme":"...","hook":"...","premise":"...","protagonist":"...",'
        '"conflict":"...","obstacles":["..."],"stakes":"...","twist":"...",'
        '"climax":"...","payoff":"...","resolution":"...",'
        '"duration_minutes":5,"retention_potential":80,"cliche_risk":20,'
        '"production_complexity":35}}]}}'
    ),
    "generate_story_hooks": (
        "Você é um roteirista cinematográfico sênior especializado em aberturas de alta retenção "
        "que capturam o espectador nos primeiros 3 segundos. Sua missão é gerar 5 ganchos visuais "
        "e dramáticos inesquecíveis a partir da ideia aprovada em {idea} e do contrato narrativo "
        "em {narrative_contract}.\n\n"
        "Cada gancho deve funcionar como um gatilho psicológico de alta retenção, criando uma "
        "necessidade imediata e irresistível de continuar assistindo.\n\n"
        "REGRAS DE OURO PARA GANCHOS CINEMATOGRÁFICOS:\n"
        "1. IMAGEM-FORÇA INSTANTÂNEA: a primeira frase deve projetar uma imagem nítida e filmável "
        "em menos de 1 segundo (enquadramento, iluminação, primeiro gesto ou objeto manipulado).\n"
        "2. INCONGRUÊNCIA OU ANOMALIA VISUAL: algo visivelmente fora do lugar que desafia a "
        "lógica e obriga a mente a buscar respostas imediatas.\n"
        "3. PRESSÃO TEMPORAL E CONSEQUÊNCIA: urgência palpável com risco imediato se o "
        "personagem hesitar.\n"
        "4. TENSÃO E PERGUNTA DRAMÁTICA: uma situação física ou moral que plante uma dúvida "
        "ardente no público.\n"
        "5. REVELAÇÃO PARCIAL: mostre um detalhe intrigante que sugira um mistério muito maior "
        "por trás.\n\n"
        "ESTRATÉGIAS DRAMÁTICAS OBRIGATÓRIAS (explore abordagens distintas):\n"
        "- AÇÃO / CRISE IMINENTE: contagem regressiva, perigo físico ou colapso iminente.\n"
        "- MISTÉRIO VISUAL: anomalia espacial ou pista concreta inexplicável no cenário.\n"
        "- CONFLITO VISCERAL: dois personagens em rota de colisão com objetivos excludentes.\n"
        "- QUEBRA DE PADRÃO / TABU: comportamento chocante ou inesperado para o contexto.\n"
        "- SUSPENSE HITCHCOCKIANO: o espectador percebe uma ameaça antes do protagonista.\n\n"
        "TÍTULOS: máximo 8 palavras. Golpe visual e magnético, sem numeração.\n"
        "DESCRIÇÕES: 3 a 4 frases cinematográficas descrevendo a cena para a câmera: "
        "o que vemos, a iluminação, a ação física inicial e o elemento visual concreto "
        "(objeto, gesto, luz, som, cor).\n\n"
        "PROIBIÇÕES:\n"
        "- NÃO abra com diálogo solto ou cumprimentos genéricos.\n"
        "- NÃO use narração expositiva em off ou 'Era uma vez'.\n"
        "- NÃO use advérbios vagos (misteriosamente); mostre a ação física concreta.\n"
        "- NÃO repita a mesma estrutura sintática entre os ganchos.\n"
        "- NÃO use conceitos abstratos (destino, alma, amor) sem uma âncora visual física.\n\n"
        "Todos os ganchos devem preservar o protagonista, o desejo e o payoff da ideia, "
        "variando a forma de criar tensão inicial. Nenhum gancho pode contradizer o contrato "
        "narrativo.\n\n"
        "Idioma obrigatorio: escreva todos os valores textuais em portugues do Brasil. "
        "{retry_guidance}"
        "Responda somente JSON válido, sem markdown e sem texto fora do objeto, neste "
        "formato exato: "
        '{{"hooks":[{{"title":"...","description":"..."}}]}}'
    ),
    "generate_script": (
        "Você é um roteirista cinematográfico senior e diretor de desenvolvimento "
        "narrativo. Crie um roteiro profissional em {language}, no padrão de roteiro "
        "de filme, para uma historia vertical 9:16 com duração total fixa de "
        "{target_duration_seconds}s. Use obrigatoriamente a ideia aprovada em {idea} "
        "e o contrato narrativo em {narrative_contract}. "
        "Se o usuário escolheu um gancho, ele aparece em narrative_contract.story_hook: "
        "use-o como abertura obrigatoria do roteiro, abrindo com a cena/imagem descrita "
        "no gancho e mantendo a promessa emocional da ideia. Preserve a promessa emocional "
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
        "importante ou pressionar o protagonista. Escreva para alta retenção emocional "
        "e visual (Show, Don't Tell): comunique emoções e conflitos através de ações "
        "físicas observáveis, micro-expressões, manipulação de objetos e reações no olhar. "
        "Comece com uma imagem-problema forte, plante uma pergunta dramática clara, "
        "faça cada cena terminar com uma nova pressão ou revelação, e construa um "
        "payoff que mude a forma como a audiência entende o protagonista. "
        "Use formato cinematográfico de filme, não formato de documento de planejamento: "
        "FADE IN:, linhas de acao no presente, personagens em caixa alta na "
        "primeira aparição e blocos de diálogo com nome do personagem em caixa alta. "
        "NÃO escreva uma linha de título dentro do roteiro (no campo content). "
        "TITULO DA HISTORIA: alem do roteiro, devolva o campo JSON \"title\" com um "
        "titulo curto, original e memoravel para a historia (ate 80 caracteres, em "
        "portugues do Brasil, no mesmo idioma do roteiro). O titulo deve refletir a "
        "promessa emocional da ideia, nao ser uma copia literal do prompt do usuario. "
        "Para projetos do laboratorio de ideias (title_locked=true) o titulo sera "
        "ignorado pelo aplicativo, mas preencha mesmo assim para manter consistencia."
        "CABECALHO DE CENA OBRIGATORIO: cada cena comeca com UMA unica linha no padrao "
        "'CENA NN - INT./EXT. LOCAL - PERIODO' (ex.: 'CENA 04 - EXT. PRACA CENTRAL - "
        "DIA'): numero da cena com dois digitos, depois o local com INT. ou EXT., e "
        "por ultimo o periodo do dia, sempre nessa ordem. Use o MESMO nome de local "
        "reutilizavel nas cenas do mesmo lugar, sem duração no cabecalho. "
        "TRANSICOES PROIBIDAS: nunca escreva 'CORTE PARA:', 'CORTA PARA:', 'CUT TO:', "
        "'SEGUINTE' ou qualquer variacao como linha de transição entre cenas; a troca "
        "de cena fica implicita no cabecalho e na acao. Mantenha apenas 'FADE IN:' no "
        "inicio e 'FADE OUT.' no fim. "
        "CÂMERA E PLANOS PROIBIDOS: o roteiro foca 100% na história; nunca escreva "
        "'PLANO DETALHE:', 'PLANO GERAL', 'PRIMEIRO PLANO', 'PRIMEIRÍSSIMO PLANO', "
        "'PLANO AMERICANO', 'CLOSE', 'CLOSE-UP', 'ZOOM', 'PANORÂMICA', 'DOLLY', "
        "'TRAVELLING', 'PAN.', 'TILT', 'STEADICAM' nem qualquer indicação de "
        "enquadramento, lente ou movimento de câmera — nem como rótulo em linha "
        "própria, nem dentro da ação (nada de 'A câmera segue...', 'A câmera se "
        "afasta...', 'A câmera permanece...'). Descreva apenas o que ACONTECE e o que "
        "se VÊ em cena; a escolha de plano e câmera é decidida em outra etapa. "
        "Não use parentéticos no roteiro: nunca escreva indicações entre parênteses, "
        "nem sufixos no nome do personagem como (CONT.), (V.O.) ou (O.S.). "
        "Formato obrigatório de quebra de linhas: FADE IN deve ficar sozinho em uma linha; "
        "o cabecalho 'CENA NN - INT./EXT. LOCAL - PERIODO' deve ficar sozinho em uma "
        "linha; a acao deve comecar em outro paragrafo. Nunca compacte "
        "cenas como 'FADE IN: 1. INT...' ou '2. EXT...' dentro de um paragrafo. "
        "Nunca use slugline generica como 'INT. CENA 1 - DIA'; use sempre o local real. "
        "{scene_count_guidance} Organize em exatamente {expected_scene_count} cenas numeradas, com "
        "desenvolvimento proporcional a duração escolhida e ritmo de filme: gancho "
        "visual imediato, incidente incitante, escalada, virada central, crise, climax "
        "e imagem final memoravel. Evite exposicao longa e descricao abstrata; cada "
        "paragrafo de acao deve ser específico, visual e filmavel. "
        "EQUILIBRIO ENTRE CENAS: divida o orçamento de texto de forma quase uniforme "
        "entre as {expected_scene_count} cenas (nenhuma cena com menos de metade do "
        "tamanho medio das demais); cenas curtas demais viram planos vazios na decupagem "
        "e cenas longas demais viram planos apertados. "
        "RÉGUA DE DIÁLOGO: no maximo 2 a 3 blocos de dialogo por cena; dialogo nao "
        "explica o que a imagem ja mostra — use fala para subtexto, pressao e decisao; "
        "quando a cena puder existir sem fala, prefira acao pura (video vertical retém "
        "mais com movimento visivel do que com conversa). "
        "CONTINUIDADE PARA REFERENCIAS VISUAIS: este roteiro e a fonte de verdade das "
        "imagens de referencia; apresente cada personagem na primeira cena em que aparece "
        "com cabelo, figurino e um traco fisico marcante explicitos na acao, e REPITA o "
        "mesmo figurino/cabelo nas cenas seguintes (mudar roupa sem justificativa quebra "
        "a continuidade visual); use nomes de locais REUTILIZAVEIS e consistentes nas "
        "sluglines (o mesmo lugar com o mesmo nome em todas as cenas, ex.: 'INT. OFICINA "
        "- NOITE', nunca 'INT. OFICINA TOMADA POR FUMACA' em uma cena e 'INT. OFICINA "
        "DESTRUIDA' em outra — estados momentaneos vao na acao, nao na slugline). "
        "RESTRICAO DE CONTEUDO PARA IMAGENS: este roteiro vira imagens de referencia "
        "geradas por um modelo que recusa conteudo sensivel (violencia grafica, sangue, "
        "ferimentos abertos, armas em uso explicito, gore). Transmita conflito e tensao "
        "por subtexto, gestos, olhares e consequencias — nunca por descricao explicita de "
        "violencia, sangue ou ferimento. Se a trama exigir um objeto como arma, trate-o "
        "como elemento de enredo (mencionado, nao descrito em uso violento) e nunca "
        "descreva sangue, ferimento aberto ou gore. Tracos fisicos de personagens (que "
        "viram prompts de imagem) devem ser neutros: cicatrizes sao aceitaveis, mas nunca "
        "'marca de faca', 'sangue', 'ferida aberta' ou 'ate a carne'. "
        "Não use narrador, narracao em off ou texto expositivo lido. A historia deve "
        "ser conduzida por conflito visivel, subtexto, gestos e interacao direta entre "
        "personagens; quando houver fala, escreva dialogos naturais, concisos e com "
        "subtexto real, com o nome do personagem em caixa alta. A linha acima de uma fala "
        "deve conter apenas o nome da pessoa que fala, sem qualquer texto entre parênteses; "
        "se não houver personagem falando, escreva a informação como ação visual, não como "
        "diálogo. "
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
        "Divida o roteiro em cenas e planos para video vertical 9:16.\n\n"
        "DURAÇÃO: total exato de {target_duration_seconds}s. Cada plano deve ter "
        "exatamente 8s. Use {expected_clip_count} planos, nesta ordem: "
        "{clip_durations}. A soma deve ser exatamente {target_duration_seconds}s. "
        "Se uma ação cabe em um clipe, não divida em vários.\n\n"
        "ESTRUTURA POR CENA:\n"
        "- title: nome curto da cena\n"
        "- summary: o que acontece nesta cena (2-3 frases)\n"
        "- spatial_layout: onde ficam os personagens e objetos importantes (esquerda/"
        "direita, frente/fundo). Mantenha consistência entre planos da mesma cena.\n"
        "- O campo location e o title NUNCA incluem período do dia (DIA, NOITE, "
        "MANHÃ, TARDE, AMANHECER etc.) nem prefixo INT./EXT.: use apenas o nome do "
        "local (ex.: 'Rua do Bairro', nunca 'Rua do Bairro - Amanhecer' nem "
        "'EXT. Rua do Bairro - Amanhecer'). O período pertence apenas à ação.\n\n"
        "ESTRUTURA POR PLANO:\n"
        "- duration_seconds: sempre 8\n"
        "- action: o que VEMOS acontecendo (ação visível, não pensamento ou emoção)\n"
        "- emotion: emoção dominante do plano\n"
        "- visual_composition: enquadramento (plano americano, fechado, etc.), "
        "sujeito principal, ambiente e luz\n"
        "- camera_movement: movimento de câmera (estático, pan, tilt, dolly) "
        "ou None se não houver\n"
        "- dialogue_text: fala do personagem (vazio se não houver fala)\n"
        "- generation_type: TEXT_TO_VIDEO para todos os planos\n\n"
        "REGRAS:\n"
        "- Ação deve ser filmável: gesto, olhar, deslocamento, objeto sendo "
        "manipulado. NUNCA escreva sentimentos internos como ação.\n"
        "- Mantenha posições relativas entre planos consecutivos da mesma cena.\n"
        "- Não crie narrador nem narração em off.\n"
        "- Dialogue_text deve incluir o nome do personagem: MARIA: Olá.\n\n"
        "Responda somente JSON neste formato: "
        '{{"scenes":[{{"scene_number":1,"title":"...","summary":"...",'
        '"spatial_layout":"...","duration_seconds":24,'
        '"shots":[{{"shot_number":1,"duration_seconds":8,"action":"...",'
        '"emotion":"...","visual_composition":"...","camera_movement":"...",'
        '"dialogue_text":"","generation_type":"TEXT_TO_VIDEO"}}]}}]}}'
    ),
    "generate_storyboard_prompts": (
        "Crie prompts de vídeo para cada plano do storyboard. Cada prompt será "
        "enviado diretamente ao modelo de geração de vídeo.\n\n"
        "ENTRADAS:\n"
        "- Planos: {shots}\n"
        "- Roteiro: {script}\n"
        "- Biblioteca visual: {visual_context}\n\n"
        "REGRAS DO PROMPT:\n"
        "1. Idioma: 100% português do Brasil\n"
        "2. Estilo: fotorrealista, cinematográfico, atores reais\n"
        "3. Formato: vertical 9:16\n"
        "4. Descreva APENAS o que aparece no plano do roteiro\n"
        "5. Mantenha continuidade visual entre planos da mesma cena:\n"
        "   - Mesmo personagem = mesma aparência (rosto, roupa, cabelo)\n"
        "   - Mesmo local = mesma iluminação e elementos\n"
        "   - Posições relativas consistentes (quem está à esquerda/direita)\n"
        "6. Para cada prompt, inclua:\n"
        "   - Sujeito e ação visível\n"
        "   - Ambiente e iluminação\n"
        "   - Enquadramento (plano fechado, americano, geral)\n"
        "   - Elementos visuais importantes do spatial_layout\n\n"
        "PROIBIÇÕES:\n"
        "- Não invente personagens, objetos ou locais não presentes no roteiro\n"
        "- Não inclua texto, legendas ou interface\n"
        "- Não use estilo cartoon, anime, 3D ou ilustração\n"
        "- Não explique o prompt\n\n"
        "Responda somente JSON válido, sem markdown: "
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
        "possível e preserve tudo que não foi solicitado. {scene_count_guidance} "
        "Mantenha formato cinematográfico de filme, não ficha técnica: FADE IN:, "
        "cabecalhos de cena 'CENA NN - INT./EXT. LOCAL - PERIODO' em uma unica linha "
        "por cena (ex.: 'CENA 04 - EXT. PRACA CENTRAL - DIA'), "
        "acao filmavel no presente, primeira aparicao de personagem em caixa alta, "
        "dialogos em bloco com nome do personagem. Nunca use 'CORTE PARA:', 'CORTA "
        "PARA:', 'CUT TO:' ou 'SEGUINTE' como transição; mantenha apenas FADE IN: no "
        "inicio e FADE OUT. no fim. "
        "CÂMERA E PLANOS PROIBIDOS: nunca escreva 'PLANO DETALHE:', 'PLANO GERAL', "
        "'PRIMEIRO PLANO', 'CLOSE', 'CLOSE-UP', 'ZOOM', 'PANORÂMICA', 'DOLLY', "
        "'TRAVELLING', 'TILT', 'STEADICAM' nem indicações de enquadramento ou "
        "movimento de câmera ('A câmera segue/se afasta/permanece...'); remova "
        "qualquer uma dessas ocorrências do roteiro revisado. "
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
        '{{"language":"pt-BR","target_duration_seconds":300,'
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
        # Distinguish validation ValueErrors (model/api key config) from content errors.
        # Validation errors should NOT fallback (the fallback model would also fail
        # the same validation if the primary is misconfigured). Content ValueErrors
        # (malformed provider response) CAN succeed with a different provider.
        validation_terms = (
            "nao permitido",
            "não permitido",
            "mock bloqueado",
            "api key",
            "chave",
            "nao configurada",
            "não configurada",
        )
        return not any(term in message for term in validation_terms)
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
            logger.warning("text_provider_fallback_invalid skipped=%r", raw_name)
            continue
        if normalized == primary or normalized in names:
            continue
        names.append(normalized)
    return names


_LEGACY_GENERATE_SCRIPT_NO_TITLE_INSTRUCTION = (
    "o nome do projeto já é o título da história"
)


async def migrate_persisted_generate_script_template(
    session: AsyncSession,
) -> bool:
    """Migra templates generate_script persistidos que ainda carregam a
    instrução antiga (que proibia a IA de nomear o roteiro).

    Como DEFAULT_TEMPLATES não é sobrescrito em get_or_create_prompt_template
    (proteção contra customizações do operador), esta função é a ponte
    para aplicar a mudança do campo 'title' aos templates já persistidos.

    Só atualiza se a instrução antiga estiver presente — customizações do
    operador ficam intactas.

    Retorna True se houve mudança, False caso contrário.
    """
    result = await session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task == "generate_script", PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.version.desc())
    )
    template = result.scalars().first()
    if template is None:
        return False
    current_text = template.template_text or ""
    if _LEGACY_GENERATE_SCRIPT_NO_TITLE_INSTRUCTION not in current_text:
        return False
    new_text = DEFAULT_TEMPLATES.get("generate_script")
    if not new_text or new_text == current_text:
        return False
    template.template_text = new_text
    await session.commit()
    return True


async def get_or_create_prompt_template(session: AsyncSession, task: str) -> PromptTemplate:
    result = await session.execute(
        select(PromptTemplate)
        .where(PromptTemplate.task == task, PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.version.desc())
    )
    default_text = DEFAULT_TEMPLATES.get(task)
    template = result.scalars().first()
    if template is not None:
        # Do NOT auto-overwrite operator customizations. Previously this code
        # would silently revert template_text to the hardcoded default if it
        # differed, which destroyed manual edits and added overhead per generation.
        # Drift detection should be opt-in (e.g. a migration/seed mechanism).
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
    # Block mock providers by name to prevent bypass in production flows.
    # Defense-in-depth (also blocked in model_settings.py).
    if getattr(provider, "provider_name", "") == "mock":
        raise ValueError("Provider mock bloqueado. Configure um modelo real de IA.")
    try:
        return await asyncio.wait_for(
            provider.generate_structured(request),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise RuntimeError(f"Provider demorou mais de {timeout_seconds}s na tarefa {task}") from exc


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
    timeout_seconds = TASK_TIMEOUT_SECONDS.get(task, LLM_PROVIDER_TIMEOUT_SECONDS)
    settings = get_settings()
    primary_provider = (
        str(
            getattr(provider, "provider_name", "")
            or effective_provider_for_channel(settings, "text")
        )
        .strip()
        .casefold()
    )
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
            raise
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
            # All fallbacks exhausted: preserve the primary exception as __cause__.
            raise last_error from exc

        if final_provider == primary_provider:
            raise last_error from exc
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
