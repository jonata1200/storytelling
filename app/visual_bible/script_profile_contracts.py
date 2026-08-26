"""Schemas, chunking, and prompts used by script profile extraction."""

import json
import re
from typing import Any

SCRIPT_EXTRACTION_CHUNK_CHARS = 7000

EXTRACTION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "role": {"type": "string"},
                    "gender": {"type": "string"},
                    "origin": {"type": "string"},
                    "apparent_age": {"type": "string"},
                    "height_cm": {"type": "string"},
                    "weight_kg": {"type": "string"},
                    "body_type": {"type": "string"},
                    "face_shape": {"type": "string"},
                    "skin_tone": {"type": "string"},
                    "eyes": {"type": "string"},
                    "hair": {"type": "string"},
                    "base_outfit": {"type": "string"},
                    "footwear": {"type": "string"},
                    "distinctive_features": {"type": "string"},
                    "palette": {"type": "string"},
                    "personality": {"type": "string"},
                    "arc": {"type": "string"},
                    "scene_numbers": {"type": "array", "items": {"type": "integer"}},
                    "evidence_text": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name",
                    "aliases",
                    "role",
                    "gender",
                    "origin",
                    "apparent_age",
                    "height_cm",
                    "weight_kg",
                    "body_type",
                    "face_shape",
                    "skin_tone",
                    "eyes",
                    "hair",
                    "base_outfit",
                    "footwear",
                    "distinctive_features",
                    "palette",
                    "personality",
                    "arc",
                    "scene_numbers",
                    "evidence_text",
                ],
            },
        },
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "layout": {"type": "string"},
                    "materials": {"type": "array", "items": {"type": "string"}},
                    "palette": {"type": "array", "items": {"type": "string"}},
                    "lighting": {"type": "string"},
                    "key_objects": {"type": "array", "items": {"type": "string"}},
                    "scene_numbers": {"type": "array", "items": {"type": "integer"}},
                    "evidence_text": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name",
                    "description",
                    "layout",
                    "materials",
                    "palette",
                    "lighting",
                    "key_objects",
                    "scene_numbers",
                    "evidence_text",
                ],
            },
        },
    },
    "required": ["characters", "locations"],
}

ADJUDICATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "exclude": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "reason"],
            },
        },
        "merge": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "keep": {"type": "string"},
                    "merge_into": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["keep", "merge_into", "reason"],
            },
        },
        "low_confidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "reason"],
            },
        },
    },
    "required": ["exclude", "merge", "low_confidence"],
}

VISUAL_DESIGN_FIELDS = {
    "character": {
        "role",
        "gender",
        "origin",
        "apparent_age",
        "height_cm",
        "weight_kg",
        "body_type",
        "face_shape",
        "skin_tone",
        "eyes",
        "hair",
        "base_outfit",
        "footwear",
        "distinctive_features",
        "palette",
        "personality",
        "arc",
    },
    "location": {
        "description",
        "layout",
        "materials",
        "palette",
        "lighting",
        "key_objects",
    },
}


def clean_extracted_item(raw: object, *, location: bool = False) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    cleaned = {key: value for key, value in raw.items() if value not in (None, "", [], {})}
    cleaned["name"] = name
    cleaned["scene_numbers"] = list(
        dict.fromkeys(number for number in raw.get("scene_numbers", []) if isinstance(number, int))
    )
    cleaned["evidence_text"] = list(
        dict.fromkeys(
            str(value).strip()[:300] for value in raw.get("evidence_text", []) if str(value).strip()
        )
    )
    cleaned["extraction_sources"] = ["llm_extraction"]
    if location:
        for key in ("materials", "palette"):
            values = raw.get(key, [])
            if isinstance(values, list):
                cleaned[key] = list(
                    dict.fromkeys(str(value).strip() for value in values if str(value).strip())
                )
    else:
        aliases = raw.get("aliases", [])
        if isinstance(aliases, list):
            cleaned["aliases"] = list(
                dict.fromkeys(str(value).strip() for value in aliases if str(value).strip())
            )
    return cleaned


def result_payload(result: Any) -> dict[str, Any] | None:
    """Extrai o JSON estruturado da resposta do LLM.

    Retorna None quando o conteúdo não é um objeto JSON válido — sinalizar
    falha de parse é obrigatório para que o chamador possa logar/retentar em
    vez de aceitar um chunk vazio silenciosamente.
    """
    content = getattr(result, "content", None)
    if isinstance(content, dict):
        return content
    text = str(getattr(result, "raw_content", "") or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed: Any = json.loads(text.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def script_extraction_chunks(script_content: str) -> list[str]:
    """Split a screenplay while preserving complete scenes whenever possible."""
    units: list[str] = []
    current_unit = ""
    for raw_line in script_content.splitlines(keepends=True):
        line = raw_line.strip()
        starts_numbered_scene = bool(
            re.fullmatch(r"CENA\s+\d+", line, flags=re.IGNORECASE)
            or re.fullmatch(
                r"CENA\s+\d+\s*[-:]\s*(?:INT|EXT)\..+", line, flags=re.IGNORECASE
            )
        )
        starts_slugline = bool(
            re.fullmatch(
                r"(?:(?:INT|EXT)\.?(?:\s*/\s*(?:INT|EXT)\.?)?|I\s*/\s*E)\s+.+",
                line,
                flags=re.IGNORECASE,
            )
        )
        current_has_numbered_scene = bool(
            re.search(r"(?im)^CENA\s+\d+\s*$", current_unit)
            or re.search(
                r"(?im)^CENA\s+\d+\s*[-:]\s*(?:INT|EXT)\.", current_unit
            )
        )
        starts_scene = starts_numbered_scene or (starts_slugline and not current_has_numbered_scene)
        if starts_scene and current_unit:
            units.append(current_unit)
            current_unit = ""
        current_unit += raw_line
    if current_unit or not units:
        units.append(current_unit)

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > SCRIPT_EXTRACTION_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        while len(unit) > SCRIPT_EXTRACTION_CHUNK_CHARS:
            if current:
                available = SCRIPT_EXTRACTION_CHUNK_CHARS - len(current)
                current += unit[:available]
                unit = unit[available:]
                chunks.append(current)
                current = ""
            else:
                split_at = unit.rfind("\n", 0, SCRIPT_EXTRACTION_CHUNK_CHARS + 1)
                split_at = SCRIPT_EXTRACTION_CHUNK_CHARS if split_at <= 0 else split_at + 1
                chunks.append(unit[:split_at])
                unit = unit[split_at:]
        current += unit
    if current or not chunks:
        chunks.append(current)
    return chunks


def extraction_prompt(
    chunk: str,
    chunk_number: int,
    chunk_count: int,
    story_context: str = "",
    parser_hints: list[str] | None = None,
) -> str:
    context_section = (
        f"\nCONTEXTO CANÔNICO DA HISTÓRIA:\n{story_context}\n" if story_context.strip() else ""
    )
    hints_section = ""
    if parser_hints:
        listed = ", ".join(parser_hints)
        hints_section = (
            f"\nCANDIDATOS DETECTADOS NO ROTEIRO (verifique UM A UM): {listed}\n"
            "Para cada candidato, decida com base nas evidencias do trecho: e um individuo "
            "humano visualmente presente? Se sim, descreva-o com os campos abaixo; se nao "
            "(e um objeto em destaque, coletivo, animal de estimacao, marcador de roteiro "
            "ou atmosfera), EXCLUA-o do resultado. Nao ignore candidatos humanos: cada nome "
            "propio de pessoa presente no trecho DEVE aparecer no resultado ou ser excluido "
            "com evidencia que justifique.\n"
        )
    return f"""Analise o trecho {chunk_number}/{chunk_count} do roteiro.
Extraia somente entidades presentes neste trecho.
{context_section}{hints_section}
REGRAS GERAIS:
- O roteiro e o contexto canônico acima são as únicas fontes de verdade.
- Não use presets genéricos nem invente características sem apoio nessas fontes.
- evidence_text deve conter trechos curtos e literais que sustentem a identificação ou atributo.
- scene_numbers deve registrar os números de cena explicitamente reconhecíveis.
- Consolidação entre trechos será feita pela aplicação; não tente inferir entidades ausentes.
- NENHUM campo textual pode ficar vazio quando o trecho traz a informação; se a informação
  não estiver no trecho, deixe o campo ausente (a direção de arte completa depois) — nunca
  preencha com expressões vagas como "conforme o roteiro" ou "não informado".

PERSONAGENS:
- Inclua APENAS indivíduos humanos (ou criaturas antropomórficas recorrentes)
  visualmente presentes em cena, com nome próprio ou função estável.
- Um candidato só é personagem se for uma PESSOA FÍSICA que age, fala, reage ou
  é observada fisicamente em cena. NÃO inclua: objetos, equipamentos, elementos
  técnicos, gravacoes/gravadores/rádios/telefones/telas (mesmo que apareçam em
  CAIXA ALTA no roteiro ou como cue de fala), eventos, estados, nomes de
  arquivo/transmissão ("GRAVAÇÃO", "ÚLTIMA TRANSMISSÃO", "SINAL PERDIDO"),
  lugares, sluglines, rótulos de cena, conceitos ou sentimentos.
- Uma cue de diálogo em CAIXA ALTA no meio do roteiro SÓ é personagem se
  designar uma pessoa que fala de dentro da cena; rótulos técnicos em caixa
  alta (GRAVAÇÃO, RÁDIO, TELEFONE, SISTEMA) devem ser excluídos com evidência.
- Funções como MÃE, MENINA, MENINO, GUARDA, MÉDICA ou MOTORISTA são personagens válidos
  quando designam um indivíduo recorrente ou visualmente identificável; mantenha o nome funcional.
- Não inclua narrador, voz off, IA, emoções, coletivos, gêneros ou termos genéricos.
- Registre em aliases todas as formas inequívocas usadas para o mesmo indivíduo no trecho.
- Extraia papel e, somente quando sustentados pelas fontes, origem, altura, peso, corpo, rosto,
  pele, olhos, cabelo, peças concretas do figurino, calçados, características físicas marcantes,
  acessórios, paleta, personalidade e arco.
- distinctive_features descreve APENAS traço físico ou acessório PERMANENTE do corpo ou vestido
  (cicatriz, tatuagem, óculos, mancha de nascença, penteado fixo). NUNCA uma ação, gesto,
  reação, estado de humor ou momento da história (por exemplo "trava ao entrar na cozinha",
  "canta baixinho", "chega ao amanhecer") — isso é enredo, não aparência; se a única evidência
  for de ação, deixe distinctive_features ausente.
- eyes contém APENAS cor, forma ou detalhe físico do olho ("castanhos escuros", "azuis",
  "olhos fundos"); NUNCA movimento, estado ou objeto da cena ("olhar seguindo a melodia",
  "úmidos ao cantar", "olhar fixo no caderno") — descreva isso em personality, se necessário.
- GÊNERO e IDADE APARENTE são obrigatórios em todo personagem: inferia-os das evidências do
  trecho (pronomes "ele/ela", artigos "o/a", termos como mãe, senhora, menino, médico) e
  registre a idade como faixa textual concreta (por exemplo "30 anos", "criança", "adolescente",
  "pessoa idosa"). Nunca deixe esses campos vazios — eles estruturam a continuidade visual.
  Se o trecho for absolutamente omissivo, use "não especificado" no gênero e "pessoa adulta"
  na idade em vez de strings vazias.

LOCAIS:
- Apenas ambientes físicos onde cenas acontecem; use um nome limpo e estável.
- Não inclua dia/noite, timestamps ou marcadores INT./EXT. no nome.
- Para cada local presente no trecho, componha uma descrição visual específica e fiel à história.
- Cruze slugline, ações da cena e contexto canônico. Preserve época, geografia, condição
  social, arquitetura, objetos relevantes, conservação, atmosfera e período do dia.
- Layout, materiais, paleta e iluminação devem refletir aquele local e seu uso narrativo; jamais
  preencha com combinações decorativas genéricas que poderiam pertencer a qualquer história.
- Registre em key_objects os móveis, equipamentos e objetos visualmente importantes presentes
  no roteiro. Quando a direção de arte precisar completar o ambiente, escolha objetos concretos.
- Não inclua personagens na descrição permanente do ambiente.

Responda exclusivamente no JSON definido pelo schema.

TRECHO DO ROTEIRO:
{chunk}"""


def visual_design_prompt(
    characters: list[dict],
    locations: list[dict],
    story_context: str,
) -> str:
    inventory = json.dumps(
        {"characters": characters, "locations": locations},
        ensure_ascii=False,
        default=str,
    )
    return f"""Atue como diretor de arte e transforme o inventário confirmado abaixo em perfis
visuais canônicos coerentes entre si e com a história.

CONTEXTO DA HISTÓRIA:
{story_context or "não informado; use somente as evidências do inventário"}

REGRAS:
- Não adicione, remova, renomeie ou una entidades.
- Preserve todas as evidências explícitas e nunca as contradiga.
- Complete atributos ausentes como decisões conscientes de direção de arte, derivadas de época,
  local, função narrativa, condição social, gênero e tom; não use presets aleatórios.
- PROIBIDO CAMPO VAZIO OU GENÉRICO: cada campo preenchido deve ser específico e concreto.
  Para locais, description e layout são OBRIGATÓRIOS com 15 a 40 palavras cada, derivados da
  slugline, das ações da cena e do contexto da história; nunca deixe vazio e nunca use
  expressões como "um ambiente amplo, usado e com detalhes arquitetônicos bem definidos",
  "um espaço de escala média", "um ambiente compacto, funcional", "conforme o roteiro",
  "materiais adequados" ou "iluminação compatível" — se uma dessas expressões aparecer,
  substitua pela descrição concreta do espaço real da história.
  Para personagens, cabelo, figurino e calçado são obrigatórios; nunca use "roupa discreta",
  "vestuário cotidiano", "corte neutro" ou "calçados adequados" — informe peças, cores,
  materiais e estado de conservação.
- GÊNERO e IDADE APARENTE são obrigatórios: derive-os do contexto e das evidências do
  inventário (pronomes, artigos, termos de parentesco ou profissão). Nunca os deixe vazios —
  se o inventário não trouxer evidência, use "não especificado" no gênero e uma faixa etária
  plausível (por exemplo "35 anos") na idade aparente.
- Personagens com nome funcional, como Mãe, Menina ou Guarda, precisam de aparência única e
  estável para manter continuidade.
- Cada personagem deve ter silhueta, rosto, cabelo, figurino e paleta distinguíveis.
- O resultado é FOTORREALISTA: todos os perfis descrevem pessoas e ambientes reais que serão
  fotografados em estilo de foto cinematográfica com atores reais — nunca estilo de animação,
  desenho ou 3D. Descreva os campos físicos como atributos de uma pessoa de carne e osso.
- distinctive_features e eyes descrevem APENAS traços físicos PERMANENTES (cicatriz, tatuagem,
  óculos, cor e forma dos olhos). NUNCA uma ação, gesto, reação ou momento da história
  (por exemplo "trava ao entrar na cozinha", "canta baixinho", "olhar seguindo a melodia") —
  isso é enredo, não aparência; mova-o para personality ou descarte-o.
- O figurino é obrigatório e deve refletir profissão, função, época e local da história. Em
  ambientes profissionais específicos, use uniforme ou roupa de trabalho plausível (por exemplo,
  mecânicos em oficina e profissionais de saúde em hospital). Fora desses contextos, use roupa
  cotidiana coerente com gênero, idade, condição social e tom da narrativa.
- Nunca use descrições genéricas como "vestuário cotidiano", "roupa discreta", "corte neutro"
  ou "calçados adequados". Informe peças, cores, materiais, estado de conservação e o tipo
  exato de calçado. Preencha também altura e peso com valores numéricos plausíveis.
- Cada local deve ter arquitetura, geografia, materiais, paleta e iluminação específicos.
- Para locais, nunca use expressões vagas como "conforme o roteiro", "geografia coerente",
  "materiais adequados" ou "iluminação compatível". Descreva a organização física, materiais,
  cores, fonte e direção da luz, estado de conservação e objetos concretos do ambiente.
- O perfil permanente do local não deve incluir pessoas nem misturar estados temporários.
- Copie scene_numbers e evidence_text sem alterações.
- Preencha os campos visuais com frases objetivas e concretas, sem prosa narrativa,
  repeticoes ou listas excessivas. O prompt canonico resultante deve ter densidade semelhante
  para personagens e locais, idealmente entre 80 e 120 palavras.
- Para personagens, escreva os campos físicos que formarão um pedido humano iniciado por
  "Crie a imagem de..." e detalhe faixa etária, altura, corpo, rosto, pele, olhos, cabelo,
  figurino, acessórios e características marcantes conforme o contexto. Para locais, detalhe
  tipo e periodo, arquitetura,
  organizacao espacial, materiais, objetos marcantes, paleta, iluminacao e atmosfera.
- Retorne exatamente as mesmas entidades no JSON do schema.

INVENTÁRIO CONFIRMADO:
{inventory}"""


def adjudication_prompt(
    candidates: list[dict],
    story_context: str,
) -> str:
    """Prompt da passada global de adjudicação de candidatos (fase 2 da extração).

    Entrada PEQUENA (inventário com sinais determinísticos), não o roteiro: a
    função é julgar identidade/entidade com visão global — algo que os chunks
    individuais não conseguem fazer.
    """
    inventory = json.dumps(candidates, ensure_ascii=False, default=str)
    context_section = (
        f"\nCONTEXTO CANÔNICO DA HISTÓRIA:\n{story_context}\n" if story_context.strip() else ""
    )
    return f"""Analise a lista de candidatos a personagens extraídos de um roteiro por múltiplas
passadas. Cada candidato traz: nome, papel, número de cenas com presença registrada
(scene_presence), número de falas (dialogue_cues), número de menções em linhas de ação
(action_mentions) e evidências literais do roteiro (evidence_text).
{context_section}
SINAIS — interprete assim:
- Personagens reais costumam ter scene_presence >= 2 OU dialogue_cues >= 1 OU
  action_mentions >= 2.
- Um candidato com APENAS UMA aparição, ZERO falas e ZERO menções de ação é
  suspeito: provavelmente é um objeto, elemento de cenário, evento, estado ou
  conceito que apareceu em caps de destaque, e não uma pessoa em cena.
- Cuidado com CUES DE DIÁLOGO falsas: rótulos técnicos em caixa alta como
  "GRAVAÇÃO", "ÚLTIMA TRANSMISSÃO", "RÁDIO", "TELEFONE", "SISTEMA", "SINAL
  PERDIDO" aparecem no roteiro como se fossem cue de fala, mas são elementos
  técnicos/objetos — EXCLUA-os mesmo quando têm dialogue_cues > 0. Verifique a
  evidência: se a "fala" é na verdade áudio de rádio, gravação, tela ou sistema
  (não uma pessoa presente fisicamente), não é personagem.
- Nomes que descrevem eventos/estados ("Chamada Não Completada", "Nova Chamada
  Entrante", "Telefone Tocando") NÃO são personagens, mesmo que apareçam com
  maiúsculas de destaque.
- Coletivos ("Multidão", "Funcionários") e vozes não-corpóreas (narrador, voz off,
  IA) não são personagens visuais. Exceção: "Voz Desconhecida"/"Voz no Rádio" só
  é personagem se o roteiro depois revela uma pessoa física correspondente.

TAREFAS:
1. EXCLUDE: candidatos que NÃO são indivíduos humanos visualmente presentes na
   história. Para cada um, informe o motivo em uma frase, citando o que a evidência
   mostra (por exemplo: "aparece apenas como rótulo de evento em caps, sem ação,
   fala ou presença física"). Seja conservador: só exclua quando as evidências
   sustentarem a exclusão.
2. MERGE: candidatos que são a MESMA pessoa com nomes diferentes entre cenas
   (ex.: "A Mãe do Daniel" e "Mãe"; "Sr. Ramos" e "Ramos"). Informe qual nome
   manter (o mais completo e específico usado na história) e quais nomes unir nele.
   NÃO una pessoas diferentes que compartilham apenas função genérica (duas
   "Guardas" em cenas diferentes são pessoas distintas).
3. LOW_CONFIDENCE: personagens humanos prováveis, mas com evidência fraca — entre
   no resultado, mas sinalize para o usuário revisar.

NÃO exclua personagens humanos com falas ou ações consistentes, mesmo que apareçam
pouco. Em caso de dúvida entre excluir e manter, mantenha e marque low_confidence.

Responda exclusivamente no JSON definido pelo schema.

CANDIDATOS:
{inventory}"""
