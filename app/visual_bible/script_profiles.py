# ruff: noqa: F401

import logging
import re
import unicodedata
from typing import Any

from app.visual_bible.script_profile_contracts import (
    ADJUDICATION_OUTPUT_SCHEMA,
    EXTRACTION_OUTPUT_SCHEMA,
    SCRIPT_EXTRACTION_CHUNK_CHARS,
    VISUAL_DESIGN_FIELDS,
)
from app.visual_bible.script_profile_contracts import (
    adjudication_prompt as _adjudication_prompt,
)
from app.visual_bible.script_profile_contracts import (
    clean_extracted_item as _clean_extracted_item,
)
from app.visual_bible.script_profile_contracts import (
    extraction_prompt as _extraction_prompt,
)
from app.visual_bible.script_profile_contracts import (
    result_payload as _result_payload,
)
from app.visual_bible.script_profile_contracts import (
    script_extraction_chunks as _script_extraction_chunks,
)
from app.visual_bible.script_profile_contracts import (
    visual_design_prompt as _visual_design_prompt,
)

PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}
logger = logging.getLogger(__name__)
# Tentativas de extração por chunk do roteiro (1ª + 1 retry): um chunk que
# falha em todas é registrado e a extração continua com os demais.
CHUNK_EXTRACTION_MAX_ATTEMPTS = 2

def _prompt_text(value: object) -> str:
    if isinstance(value, dict):
        parts = [
            f"{str(key).strip().replace('_', ' ').lower()}: {_prompt_text(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_prompt_text(item) for item in value if item not in (None, "", {}))
    return str(value or "").strip()


def _first_value(raw: dict, *keys: str, fallback: object = "") -> object:
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return fallback


def _role_display_name(value: object) -> str:
    text = _prompt_text(value)
    text = re.split(r"\s*\(", text, maxsplit=1)[0]
    text = re.sub(
        r"\b(?:coadjuvante|co-protagonista|coprotagonista|protagonista|principal|secundario|secundaria|apoio)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text.title()


def _is_primary_protagonist_role(value: object) -> bool:
    text = str(value or "").strip().lower()
    if "co-protagonista" in text or "coprotagonista" in text or "co protagonista" in text:
        return False
    return text == "protagonista" or text.startswith("protagonista ")


def _ascii_lower(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _entity_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii_lower(value))


def _clean_script_entity_name(value: str) -> str:
    text = re.sub(r"\([^)]*\)", "", value)
    text = re.split(r"\s+-\s+", text, maxsplit=1)[0]
    text = re.split(
        r"\s+(?:e|ou)\s+(?:um|uma|o|a|os|as)\s+",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = re.sub(r"(?i)\s+(?:e|ou)\s+(?:um|uma|o|a|os|as)\s*$", "", text)
    text = re.sub(r"(?i)^\s*(?:o|a|os|as)\s+", "", text)
    text = re.sub(r"\b\d+\s*s\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text.title()


def _is_placeholder_profile_name(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in PLACEHOLDER_PROFILE_NAMES


CHARACTER_HONORIFIC_PREFIXES = {
    "dona",
    "dom",
    "dr",
    "dra",
    "doutor",
    "doutora",
    "madame",
    "senhor",
    "senhora",
    "seu",
    "sr",
    "sra",
}


def _character_exclusion_key(value: object) -> str:
    return re.sub(r"\s+", " ", _ascii_lower(value)).strip().upper()


def _strip_character_honorifics(value: object) -> str:
    tokens = _ascii_lower(value).split()
    while len(tokens) > 1 and tokens[0].strip(".") in CHARACTER_HONORIFIC_PREFIXES:
        tokens.pop(0)
    return " ".join(tokens)


NON_CORPOREAL_CHARACTER_PHRASES = (
    "narrador",
    "narradora",
    "narracao",
    "narracao em off",
    "observador",
    "observadora",
    "assistente virtual",
    "chatbot",
    "inteligencia artificial",
    "inteligência artificial",
    "voz da ia",
    "voz do sistema",
    "voz em off",
    "voz off",
    # "REFLEXO DE LÚCIA" é o reflexo da pessoa no espelho, não um personagem
    # distinto — a Lúcia real é quem fala/age. O cue de diálogo do reflexo
    # não pode virar um segundo personagem.
    "reflexo de",
    "reflexo da",
    "reflexo do",
)

NON_CORPOREAL_CHARACTER_NAMES = {"sistema"}

NON_CORPOREAL_CHARACTER_WORDS = ("ia", "voz")

# Substantivos comuns que roteiros usam em caps de DESTAQUE na ação e o
# segundo passe do parser pode tomar como personagem ("Um CORPO está caído",
# "uma SOMBRA se move"). Uma pessoa nunca se chama só "Corpo"/"Sombra".
COMMON_NOUN_CHARACTER_NAMES = {
    "corpo",
    "cadaver",
    "cadáver",
    "sombra",
    "mancha",
    "silhueta",
    "vulto",
}

ABSTRACT_CHARACTER_NAMES = {
    "agonia",
    "alegria",
    "amor",
    "ansiedade",
    "arrependimento",
    "calma",
    "ciume",
    "ciúme",
    "coragem",
    "culpa",
    "desespero",
    "destino",
    "dor",
    "duvida",
    "dúvida",
    "esperanca",
    "esperança",
    "fe",
    "fé",
    "furia",
    "fúria",
    "luto",
    "medo",
    "memoria",
    "memória",
    "odio",
    "ódio",
    "panico",
    "pânico",
    "raiva",
    "saudade",
    "silencio",
    "silêncio",
    "solidao",
    "solidão",
    "tensao",
    "tensão",
    "tristeza",
    "verdade",
}

ABSTRACT_CHARACTER_KEYS = {_ascii_lower(item) for item in ABSTRACT_CHARACTER_NAMES}

# Palavras de animal que, precedendo um nome em caps ("Seu cachorro, THOR,
# late"), indicam um PET e não um personagem humano.
PET_ANIMAL_WORDS = (
    "cachorro",
    "cadela",
    "cao",
    "cão",
    "gato",
    "gata",
    "cavalo",
    "egua",
    "égua",
    "boi",
    "vaca",
    "passaro",
    "pássaro",
    "papagaio",
    "cachorrinho",
    "gatinho",
    "potro",
    "bicho",
    "bichinho",
    "pet",
)

SCRIPT_CHARACTER_EXCLUSIONS = {
    "ABERTURA",
    "ATO",
    "ATO I",
    "ATO II",
    "ATO III",
    "CAPITULO",
    "CAPÍTULO",
    "CREDITOS",
    "CRÉDITOS",
    "FADE IN",
    "FADE OUT",
    "FADE TO BLACK",
    "FIM",
    "CORTE PARA",
    "INT",
    "EXT",
    "CONTINUO",
    "DETALHES",
    "DIA",
    "NOITE",
    "MANHA",
    "MANHÃ",
    "TARDE",
    "CONTINUACAO",
    "CONTINUAÇÃO",
    "FLASHBACK",
    "VOLTA AO PRESENTE",
    "IMAGEM FINAL",
    "EPILOGO",
    "EPÍLOGO",
    "PROLOGO",
    "PRÓLOGO",
    "CENA",
    "NARRADOR",
    "NARRADORA",
    "NARRACAO",
    "NARRAÇÃO",
    "OBSERVADOR",
    "OBSERVADORA",
    "VOZ",
    "VOZ OFF",
    "IA",
    # Elementos técnicos/objetos que roteiros usam como rótulo em caixa alta ou
    # cue de fala ("GRAVAÇÃO", "ÚLTIMA TRANSMISSÃO") e o parser/LLM podem tomar
    # como personagem. Objetos reais citados na ação (GRAVADOR, RÁDIO) também
    # entram aqui; uma pessoa nunca se chama só "Gravador".
    "GRAVACAO",
    "GRAVAÇÃO",
    "GRAVADOR",
    "GRAVADORA",
    "RADIO",
    "RÁDIO",
    "TELEFONE",
    "CELULAR",
    "TELA",
    "MONITOR",
    "SISTEMA",
    "TRANSMISSAO",
    "TRANSMISSÃO",
    "ULTIMA TRANSMISSAO",
    "ÚLTIMA TRANSMISSÃO",
    "SINAL PERDIDO",
    "SINAL",
    "PROTOCOLO DE CONTENCAO ATIVADO",
    "PROTOCOLO DE CONTENÇÃO ATIVADO",
    "GRAVACAO DE VOZ",
    "REC",
    "PLAY",
    "STOP",
    "I.A.",
    "INTELIGENCIA ARTIFICIAL",
    "INTELIGÊNCIA ARTIFICIAL",
    "CRIANCAS",
    "CRIANÇAS",
    "CRIANCA",
    "CRIANÇA",
}

GROUP_CHARACTER_WORDS = (
    "adolescentes",
    "alunas",
    "alunos",
    "amigas",
    "amigos",
    "assembleia",
    "audiencia",
    "avos",
    "banda",
    "bandas",
    "bando",
    "bandos",
    "casais",
    "casal",
    "colegas",
    "comissao",
    "companheiras",
    "companheiros",
    "comunidade",
    "conselho",
    "convidadas",
    "convidados",
    "delegacao",
    "dupla",
    "duplas",
    "elenco",
    "empregadas",
    "empregados",
    "equipe",
    "equipes",
    "espectadores",
    "estudantes",
    "familia",
    "familias",
    "funcionarias",
    "funcionarios",
    "gangue",
    "gangues",
    "grupo",
    "grupos",
    "guardas",
    "homens",
    "integrantes",
    "irmaas",
    "irmaos",
    "jovens",
    "juri",
    "maes",
    "membros",
    "multidao",
    "multidoes",
    "mulheres",
    "participantes",
    "pessoal",
    "pessoas",
    "plateia",
    "policiais",
    "professoras",
    "professores",
    "publico",
    "soldados",
    "time",
    "times",
    "torcida",
    "tribo",
    "tribos",
    "tribunal",
    "tripulacao",
    "turma",
    "turmas",
    "vizinhos",
    "vizinhas",
)


def _looks_like_non_character_name(name: str) -> bool:
    key = _character_exclusion_key(name)
    exclusion_keys = {_character_exclusion_key(item) for item in SCRIPT_CHARACTER_EXCLUSIONS}
    if key in exclusion_keys:
        return True
    normalized = _ascii_lower(name)
    if any(phrase in normalized for phrase in NON_CORPOREAL_CHARACTER_PHRASES):
        return True
    if normalized in NON_CORPOREAL_CHARACTER_NAMES:
        return True
    if normalized in COMMON_NOUN_CHARACTER_NAMES:
        return True
    if any(
        re.search(rf"\b{re.escape(word)}\b", normalized) for word in NON_CORPOREAL_CHARACTER_WORDS
    ):
        return True
    if normalized in ABSTRACT_CHARACTER_KEYS:
        return True
    if re.fullmatch(r"(?:sentimento|emocao|emoção)\s+(?:de\s+)?[\w\s]+", normalized):
        return True
    if any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in GROUP_CHARACTER_WORDS):
        return True
    if normalized.startswith(
        (
            "ato ",
            "capitulo ",
            "capítulo ",
            "cena ",
            "creditos",
            "créditos",
            "epilogo",
            "epílogo",
            "fim",
            "prologo",
            "prólogo",
            "volta ",
            "int ",
            "ext ",
        )
    ):
        return True
    if re.fullmatch(r"(?:imagem|sequencia|sequência|montagem)(?:\s+\w+){0,3}", normalized):
        return True
    if re.fullmatch(r"(?:os |as )?pais(?: de .+)?", normalized):
        return True
    return False


def _same_character_name(candidate: str, existing: str) -> bool:
    candidate_norm = _ascii_lower(candidate)
    existing_norm = _ascii_lower(existing)
    if candidate_norm == existing_norm:
        return True
    candidate_identity = _strip_character_honorifics(candidate)
    existing_identity = _strip_character_honorifics(existing)
    if candidate_identity and candidate_identity == existing_identity:
        return True
    candidate_tokens = candidate_identity.split() or candidate_norm.split()
    existing_tokens = existing_identity.split() or existing_norm.split()
    if not candidate_tokens or not existing_tokens:
        return False
    # Sobrenome isolado ("Costa") é a mesma pessoa do nome completo
    # ("Valentina Costa"): o último token do nome multi-palavra casa com o
    # candidato de palavra única. Sem isso, "VALENTINA COSTA, MARCOS" gera o
    # falso personagem "Costa" (o regex do segundo passe não casa o espaço
    # interno, então captura só o último token seguido de vírgula).
    # MAS: um nome multi-palavra com preposição ("Reflexo De Lúcia") é um
    # DESCRITOR, não "Nome Sobrenome" — "Lúcia" não é sobrenome de "Reflexo De
    # Lúcia", é a pessoa real. Fundir aqui engolia a Lúcia e deixava só o
    # reflexo (bug real em "A Última Mensagem").
    if len(candidate_tokens) == 1 and len(existing_tokens) > 1:
        if candidate_tokens[0] == existing_tokens[-1] and not _name_has_preposition(
            existing_tokens
        ):
            return True
    if len(existing_tokens) == 1 and len(candidate_tokens) > 1:
        if existing_tokens[0] == candidate_tokens[-1] and not _name_has_preposition(
            candidate_tokens
        ):
            return True
    if candidate_tokens[0] != existing_tokens[0]:
        return False
    return candidate_norm in existing_norm or existing_norm in candidate_norm


# Preposições que ligam um descritor a um nome ("Reflexo De Lúcia" = reflexo
# DE Lúcia): nesses casos o nome multi-palavra NÃO é "Nome Sobrenome" e o
# último token é a pessoa real, não um sobrenome a ser fundido.
_NAME_PREPOSITIONS = {"de", "da", "do", "das", "dos", "e"}


def _name_has_preposition(tokens: list[str]) -> bool:
    return any(token in _NAME_PREPOSITIONS for token in tokens)


def _append_script_character_name(names: list[str], seen: set[str], raw_name: str) -> None:
    name = _clean_script_entity_name(raw_name)
    if not name or len(name) > 48:
        return
    if _looks_like_non_character_name(name):
        return
    normalized = _ascii_lower(name)
    for existing in list(seen):
        if not _same_character_name(name, existing):
            continue
        if len(normalized) <= len(existing):
            return
        names[:] = [item for item in names if _ascii_lower(item) != existing]
        seen.remove(existing)
    seen.add(normalized)
    names.append(name)


def _lowercase_name_counts(script_content: str) -> dict[str, int]:
    """Conta ocorrências de palavras NÃO em ALL-CAPS no roteiro.

    Personagens reais reaparecem em minúsculo nas linhas de ação ("Elias
    respira fundo", "o jovem zombeteiro e seus amigos"); palavras em caps de
    DESTAQUE (adjetivos, advérbios, objetos) existem apenas naquela ocorrência
    em caps ("IMPROVISADO, pendurado", "SOZINHAS, tocando").
    """
    counts: dict[str, int] = {}
    for raw_line in script_content.splitlines():
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]{2,}", raw_line):
            # Palavra é ALL-CAPS quando não contém letra minúscula;
            # ignora siglas de 1-2 letras (TV, ONU) que não são nomes.
            if word == word.upper():
                continue
            key = _ascii_lower(word)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _script_character_names(script_content: str) -> list[str]:
    """Extrai nomes de personagens do roteiro (usado como fallback)."""
    names: list[str] = []
    seen: set[str] = set()
    previous_slugline = False
    for raw_line in script_content.splitlines():
        stripped = raw_line.strip()
        # Linha em branco não reseta o contexto: "EXT. X - NOITE\n\nMÃE" ainda
        # tem o cue MÃE logo após o slugline (flush-left).
        if not stripped:
            continue
        is_slugline = bool(
            re.fullmatch(
                r"(?:(?:INT|EXT)\.?(?:\s*/\s*(?:INT|EXT)\.?)?|I\s*/\s*E)\s+.+",
                stripped,
                flags=re.IGNORECASE,
            )
        )
        for match in re.finditer(
            r"\b(?P<name>(?:(?:SR|SRA|DR|DRA)\.\s*)?"
            r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{1,48})\s*\(",
            raw_line,
        ):
            _append_script_character_name(names, seen, match.group("name"))
        line = re.sub(r"\([^)]*\)", "", raw_line).strip(" .:-")
        if not line or len(line) > 48:
            previous_slugline = is_slugline
            continue
        if not re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{2,}", line):
            previous_slugline = is_slugline
            continue
        if _looks_like_non_character_name(line) or line.startswith(("INT", "EXT")):
            previous_slugline = is_slugline
            continue
        # No formato screenplay, o CUE de fala é flush-left ("MÃE" na coluna 1)
        # e é válido mesmo logo após o slugline. Linha ALL-CAPS INDENTADA
        # logo após o slugline descreve o cenário/clima ("EXT. FAROL - NOITE"
        # → " DE TEMPESTADE") e não é personagem.
        if previous_slugline and raw_line.startswith((" ", "\t")):
            previous_slugline = is_slugline
            continue
        previous_slugline = is_slugline
        _append_script_character_name(names, seen, line)
    # Segundo passe: introduções de personagem em linhas de ação — nome em
    # ALL-CAPS seguido de vírgula/verbo de estado ("ELIAS, faroleiro de barba
    # grisalha, sobe correndo..."; "VITOR surge"). O nome precisa ser seguido
    # de descrição para não capturar objetos em caps de destaque (RELÓGIO
    # DIGITAL marca, LUZ DO FAROL pisca, PASSAGEIROS gritam).
    lowercase_names = _lowercase_name_counts(script_content)
    for raw_line in script_content.splitlines():
        for match in re.finditer(
            r"(?<![A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç])"
            r"(?P<name>(?:(?:SR|SRA|DR|DRA)\.\s*)?"
            r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,48})"
            r"(?=,\s|\s+é\s|\s+era\s|\s+está\s|\s+aparece\s)",
            raw_line,
        ):
            after_name = raw_line[match.end():]
            # Vírgula abrindo apositivo genérico ("DENTRO, uma CRIANÇA") não é
            # introdução de personagem — exige descrição de papel/ação.
            if re.match(r",\s*(?:uma?|uns|umas|os|as|o|a)\s", after_name, flags=re.IGNORECASE):
                continue
            # Nome precedido de palavra de animal ("Seu cachorro, THOR, late")
            # não vira personagem humano.
            prefix = _ascii_lower(raw_line[: match.start()]).rstrip(" ,;:-")
            if prefix.endswith(tuple(f" {word}" for word in PET_ANIMAL_WORDS)):
                continue
            # Palavra em caps de DESTAQUE na ação ("Um HOLOFOTE IMPROVISADO,
            # pendurado...", "teclas se mover SOZINHAS, tocando...") só existe
            # em ALL-CAPS; personagens reais reaparecem em minúsculo na ação
            # ("Elias", "o jovem zombeteiro", "Lúcia"). Falso positivo real
            # (projeto O Piano na Praça): "Improvisado" e "Sozinhas" viraram
            # personagens. Rejeita quando o nome NÃO tem ocorrência em
            # não-ALL-CAPS E o aposto abre com flexão verbal/adverbial
            # (particípio -ado/-ada, gerúndio -ando/-endo, advérbio -mente) —
            # personagens reais recebem aposto de papel substantivo
            # ("ELIAS, faroleiro de barba grisalha") mesmo sem repetição em
            # minúsculo em roteiros curtos.
            first_word = match.group("name").split()[0]
            # O NOME em si sendo uma flexão verbal/adjetival (particípio
            # -ado/-ada, advérbio -mente, gerúndio -endo/-indo) nunca é pessoa:
            # "ARRANCADO, deixando" (o botão foi arrancado) virava o falso
            # personagem "Arrancado". A guarda de aposto verbal não pega esse
            # caso porque "arrancado" reaparece em minúsculo como VERBO na ação
            # ("o botão arrancado"), então a contagem de minúsculo é > 0.
            # Exclui -ando de propósito: Fernando/Armando/Orlando são nomes reais.
            if _ascii_lower(first_word).endswith(
                ("ado", "ada", "ados", "adas", "endo", "indo", "mente")
            ):
                continue
            appositive = re.match(r",\s*([A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]+)", after_name)
            appositive_word = _ascii_lower(appositive.group(1)) if appositive else ""
            verbal_ending = appositive_word.endswith(
                ("ado", "ada", "ados", "adas", "ando", "endo", "indo", "mente")
            )
            if lowercase_names.get(_ascii_lower(first_word), 0) == 0 and verbal_ending:
                continue
            _append_script_character_name(names, seen, match.group("name"))
    return names


def _script_character_items(script_content: str) -> list[dict]:
    """Build deterministic character candidates, including stable role labels."""
    names = _script_character_names(script_content)
    items: list[dict] = []
    lines = [line.strip() for line in script_content.splitlines() if line.strip()]
    for name in names:
        normalized = _ascii_lower(name)
        evidence = [
            line[:300]
            for line in lines
            if re.search(rf"\b{re.escape(normalized)}\b", _ascii_lower(line))
            and not re.fullmatch(
                r"(?:(?:INT|EXT)\.?(?:\s*/\s*(?:INT|EXT)\.?)?|I\s*/\s*E)\s+.+",
                line,
                flags=re.IGNORECASE,
            )
        ][:6]
        role = normalized if normalized in {"mae", "pai", "menina", "menino", "guarda"} else ""
        items.append(
            {
                "name": name,
                "role": role,
                "scene_numbers": [],
                "evidence_text": evidence,
                "extraction_sources": ["screenplay_parser"],
            }
        )
    return items


def _script_location_items(script_content: str) -> list[dict]:
    """Extrai sluglines físicas como proteção contra omissões do LLM."""
    locations: list[dict] = []
    seen: dict[str, dict] = {}
    current_scene: int | None = None
    for raw_line in script_content.splitlines():
        line = raw_line.strip()
        # Formato canonico: "CENA 04 - EXT. PRACA CENTRAL - DIA" (uma linha).
        combined_match = re.fullmatch(
            r"CENA\s+(\d+)\s*[-:]\s*(?P<heading>(?:INT|EXT)\..+)",
            line,
            flags=re.IGNORECASE,
        )
        if combined_match:
            current_scene = int(combined_match.group(1))
            line = combined_match.group("heading").strip()
        scene_match = re.fullmatch(r"CENA\s+(\d+)", line, flags=re.IGNORECASE)
        if scene_match:
            current_scene = int(scene_match.group(1))
            continue
        heading = re.fullmatch(
            r"(?:(?:INT|EXT)\.?(?:\s*/\s*(?:INT|EXT)\.?)?|I\s*/\s*E)\s+(.+)",
            line,
            flags=re.IGNORECASE,
        )
        if not heading:
            continue
        name = (
            re.split(
                r"\s+-\s+(?:DIA|NOITE|MANHÃ|MANHA|TARDE|FIM DE TARDE|MADRUGADA|"
                r"AMANHECER|ENTARDECER|MEIO[- ]?DIA|ANOITECER|INÍCIO DA NOITE|"
                r"INICIO DA NOITE|ALTA NOITE|CONTÍNUO|CONTINUO)\b",
                heading.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            .strip(" .:-")
            .title()
        )
        key = _entity_key(name)
        if not key:
            continue
        if key not in seen:
            item = {
                "name": name,
                "description": "",
                "scene_numbers": [],
                "evidence_text": [],
                "extraction_sources": ["screenplay_parser"],
            }
            seen[key] = item
            locations.append(item)
        item = seen[key]
        if current_scene is not None and current_scene not in item["scene_numbers"]:
            item["scene_numbers"].append(current_scene)
        if line not in item["evidence_text"]:
            item["evidence_text"].append(line)
    return locations


def _repair_missing_character_names(
    items: list[dict], script_content: str, protagonist_hint: str = ""
) -> list[dict]:
    candidates = _script_character_names(script_content)
    missing_count = sum(1 for item in items if _is_placeholder_profile_name(item.get("name")))
    use_script_candidates = missing_count > 0 and len(candidates) >= missing_count
    candidate_index = 0
    repaired: list[dict] = []
    used_names: set[str] = set()
    for item in items:
        profile = dict(item)
        if _is_placeholder_profile_name(profile.get("name")):
            role = _first_value(profile, "role", "funcao", "função", fallback="")
            replacement = ""
            if protagonist_hint and _is_primary_protagonist_role(role):
                replacement = protagonist_hint
            elif use_script_candidates and candidate_index < len(candidates):
                replacement = candidates[candidate_index]
                candidate_index += 1
            else:
                replacement = _role_display_name(role)
            if replacement:
                profile["name"] = replacement
        name = str(profile.get("name") or "").strip()
        key = name.lower()
        if key and key in used_names:
            role_name = _role_display_name(_first_value(profile, "role", "funcao", "função"))
            if role_name and role_name.lower() != key:
                profile["name"] = role_name
                key = role_name.lower()
        if key:
            used_names.add(key)
        repaired.append(profile)
    return repaired



def _merge_extracted_items(
    items: list[dict],
    *,
    entity_kind: str = "",
) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        key = _entity_key(item.get("name"))
        if not key:
            continue
        if entity_kind == "character" and key not in merged:
            name = str(item.get("name") or "")
            candidate_names = [name, *list(item.get("aliases") or [])]
            key = next(
                (
                    existing_key
                    for existing_key, existing in merged.items()
                    if any(
                        _same_character_name(candidate_name, existing_name)
                        for candidate_name in candidate_names
                        for existing_name in [
                            str(existing.get("name") or ""),
                            *list(existing.get("aliases") or []),
                        ]
                    )
                ),
                key,
            )
        if key not in merged:
            merged[key] = dict(item)
            order.append(key)
            continue
        target = merged[key]
        for field, value in item.items():
            if value in (None, "", [], {}):
                continue
            if field in {
                "scene_numbers",
                "evidence_text",
                "materials",
                "palette",
                "extraction_sources",
                "aliases",
            }:
                existing = target.get(field, [])
                if not isinstance(existing, list):
                    existing = [existing]
                additions = value if isinstance(value, list) else [value]
                target[field] = list(dict.fromkeys([*existing, *additions]))
            elif target.get(field) in (None, "", [], {}):
                target[field] = value
    return [merged[key] for key in order]


def _apply_visual_design(
    originals: list[dict],
    designed: list[dict],
    *,
    entity_kind: str,
) -> list[dict]:
    fields = VISUAL_DESIGN_FIELDS[entity_kind]
    result: list[dict] = []
    for original in originals:
        original_name = str(original.get("name") or "")
        match = next(
            (
                candidate
                for candidate in designed
                if (
                    _same_character_name(original_name, str(candidate.get("name") or ""))
                    if entity_kind == "character"
                    else _entity_key(original_name) == _entity_key(candidate.get("name"))
                )
            ),
            None,
        )
        enriched = dict(original)
        if match is not None:
            for field in fields:
                value = match.get(field)
                if value not in (None, "", [], {}) and enriched.get(field) in (
                    None,
                    "",
                    [],
                    {},
                ):
                    enriched[field] = value
            sources = list(enriched.get("extraction_sources") or [])
            enriched["extraction_sources"] = list(dict.fromkeys([*sources, "llm_visual_direction"]))
        result.append(enriched)
    return result


def visual_extraction_coverage(
    script_content: str,
    characters: list[dict],
    locations: list[dict],
) -> dict[str, list[str]]:
    """Report deterministic screenplay candidates that were lost by consolidation."""
    missing_characters = [
        expected["name"]
        for expected in _script_character_items(script_content)
        if not any(
            _same_character_name(str(expected["name"]), str(item.get("name") or ""))
            or any(
                _same_character_name(str(expected["name"]), str(alias))
                for alias in item.get("aliases") or []
            )
            for item in characters
        )
    ]
    location_keys = {_entity_key(item.get("name")) for item in locations}
    missing_locations = [
        expected["name"]
        for expected in _script_location_items(script_content)
        if _entity_key(expected["name"]) not in location_keys
    ]
    return {
        "missing_characters": missing_characters,
        "missing_locations": missing_locations,
    }


def _character_presence_signals(script_content: str, name: str) -> dict[str, int]:
    """Sinais determinísticos de força do candidato no roteiro inteiro.

    - dialogue_cues: quantas cues de fala o nome tem (linhas ALL-CAPS próprias
      seguidas de fala, ou "NOME (continuação)").
    - action_mentions: quantas linhas de ação citam o nome (não-caps, qualquer
      flexão de caixa é aceita pois personagens reaparecem em minúsculo).
    - scene_presence: número de cenas distintas com QUALQUER ocorrência.
    """
    normalized = _ascii_lower(name)
    if not normalized:
        return {"dialogue_cues": 0, "action_mentions": 0, "scene_presence": 0}
    dialogue_cues = 0
    action_mentions = 0
    scenes: set[int] = set()
    current_scene = 0
    name_pattern = re.compile(rf"\b{re.escape(normalized)}\b")
    for raw_line in script_content.splitlines():
        stripped = raw_line.strip()
        scene_match = re.fullmatch(r"CENA\s+(\d+)", stripped, flags=re.IGNORECASE)
        if scene_match:
            current_scene = int(scene_match.group(1))
            continue
        combined_scene = re.match(r"(?i)^CENA\s+(\d+)\s*[-:]", stripped)
        if combined_scene:
            current_scene = int(combined_scene.group(1))
        if not stripped:
            continue
        # Cue de fala: linha ALL-CAPS própria (com ou sem parêntese), sem
        # ser slugline nem marcador.
        line_no_parens = re.sub(r"\([^)]*\)", "", stripped).strip(" .:-")
        is_slugline = stripped.upper().startswith(("INT.", "EXT.", "INT/", "EXT/"))
        if (
            not is_slugline
            and line_no_parens
            and len(line_no_parens) <= 48
            and re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{2,}", line_no_parens)
            and name_pattern.fullmatch(_ascii_lower(line_no_parens))
        ):
            dialogue_cues += 1
            if current_scene:
                scenes.add(current_scene)
            continue
        if is_slugline:
            continue
        if name_pattern.search(_ascii_lower(stripped)):
            action_mentions += 1
            if current_scene:
                scenes.add(current_scene)
    return {
        "dialogue_cues": dialogue_cues,
        "action_mentions": action_mentions,
        "scene_presence": len(scenes),
    }


def _adjudication_inventory(
    script_content: str, characters: list[dict]
) -> list[dict]:
    """Monta o inventário compacto (nome + sinais + evidências) para o LLM."""
    inventory: list[dict] = []
    for item in characters:
        name = str(item.get("name") or "")
        if not name:
            continue
        signals = _character_presence_signals(script_content, name)
        aliases = [str(alias) for alias in item.get("aliases") or [] if str(alias)]
        inventory.append(
            {
                "name": name,
                "role": str(item.get("role") or ""),
                "aliases": aliases,
                "scene_presence": signals["scene_presence"],
                "dialogue_cues": signals["dialogue_cues"],
                "action_mentions": signals["action_mentions"],
                "evidence_text": [
                    str(evidence)[:200]
                    for evidence in (item.get("evidence_text") or [])[:6]
                ],
            }
        )
    return inventory


def _find_candidate_index(candidates: list[dict], name: str) -> int:
    """Índice do candidato que casa com o nome (tolerante, como o merge)."""
    target = str(name or "").strip()
    for index, candidate in enumerate(candidates):
        candidate_name = str(candidate.get("name") or "")
        if _same_character_name(target, candidate_name):
            return index
        if any(
            _same_character_name(target, str(alias))
            for alias in candidate.get("aliases") or []
        ):
            return index
    return -1


def _apply_adjudication(
    characters: list[dict],
    verdict: dict[str, Any] | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Aplica o veredito do LLM: exclusões, merges e marcação de confiança.

    Retorna (personagens finais, exclusões aplicadas, baixa confiança).
    Exclusão/merge só atingem candidatos citados pelo veredito e nunca
    removem todos os personagens (conservadorismo).
    """
    if not characters:
        return [], [], []
    if not isinstance(verdict, dict):
        return characters, [], []

    excluded_keys = {_entity_key(entry.get("name")) for entry in verdict.get("exclude") or []}
    excluded_keys.discard("")
    merged_into: dict[str, str] = {}
    for entry in verdict.get("merge") or []:
        keep = _entity_key(entry.get("keep"))
        if not keep:
            continue
        for name in entry.get("merge_into") or []:
            name_key = _entity_key(name)
            if name_key and name_key != keep:
                merged_into[name_key] = keep

    kept: list[dict] = []
    exclusions: list[dict] = []
    for character in characters:
        key = _entity_key(character.get("name"))
        if key in excluded_keys or merged_into.get(key):
            exclusions.append(
                {
                    "name": str(character.get("name") or ""),
                    "reason": next(
                        (
                            str(entry.get("reason") or "")
                            for entry in verdict.get("exclude") or []
                            if _entity_key(entry.get("name")) == key
                        ),
                        next(
                            (
                                str(entry.get("reason") or "")
                                for entry in verdict.get("merge") or []
                                if key
                                in {_entity_key(n) for n in entry.get("merge_into") or []}
                            ),
                            "unificado com outro candidato pelo LLM",
                        ),
                    ),
                }
            )
            continue
        kept.append(character)

    # Nunca deixa o veredito apagar o elenco inteiro (conservadorismo).
    if not kept:
        return characters, [], []
    # Merge: move aliases/evidências dos unidos para o sobrevivente.
    for keep_key in {merged_into[k] for k in merged_into}:  # noqa: B007 — nome intencional
        survivor = next(
            (c for c in kept if _entity_key(c.get("name")) == keep_key), None
        )
        if survivor is None:
            continue
        for removed in characters:
            removed_key = _entity_key(removed.get("name"))
            if merged_into.get(removed_key) != keep or removed_key == keep:
                continue
            for field in ("evidence_text", "scene_numbers"):
                existing = survivor.get(field) or []
                additions = removed.get(field) or []
                if isinstance(existing, list):
                    survivor[field] = list(dict.fromkeys([*existing, *additions]))
            aliases = list(survivor.get("aliases") or [])
            removed_name = str(removed.get("name") or "")
            if removed_name and removed_name not in aliases:
                aliases.append(removed_name)
            survivor["aliases"] = aliases

    low_confidence: list[dict] = []
    low_names = {_entity_key(entry.get("name")) for entry in verdict.get("low_confidence") or []}
    for character in kept:
        if _entity_key(character.get("name")) not in low_names:
            continue
        reason = next(
            (
                str(entry.get("reason") or "")
                for entry in verdict.get("low_confidence") or []
                if _entity_key(entry.get("name")) == _entity_key(character.get("name"))
            ),
            "",
        )
        character["low_confidence"] = {"reason": reason}
        low_confidence.append(
            {
                "name": str(character.get("name") or ""),
                "reason": reason,
            }
        )
    return kept, exclusions, low_confidence


async def _llm_extract_characters_and_locations(
    session: Any,
    project_id: object,
    script_content: str,
    *,
    story_context: str = "",
) -> tuple[list[dict], list[dict]]:
    """Extrai personagens e locais do roteiro inteiro usando o LLM configurado.

    Retorna (personagens, locais) como listas de perfis.
    """
    from uuid import UUID as _UUID

    from app.generation.model_settings import llm_provider_for_task
    from app.providers.llm.types import LLMRequest

    provider, model = await llm_provider_for_task(
        session, _UUID(str(project_id)), "generate_visual_bible"
    )

    chunks = _script_extraction_chunks(script_content)
    characters: list[dict] = []
    locations: list[dict] = []
    failed_chunks: list[int] = []
    # Candidatos do parser determinístico: cada chunk recebe os nomes que o
    # parser detectou DENTRO dele, para o LLM verificar um a um (mata omissões
    # do tipo Elias/THOR na origem, em vez de confiar só na memória do LLM).
    for index, chunk in enumerate(chunks, start=1):
        parser_hints = [
            item["name"] for item in _script_character_items(chunk)
        ] + [item["name"] for item in _script_location_items(chunk)]
        request = LLMRequest(
            task="extract_characters_locations",
            prompt=_extraction_prompt(chunk, index, len(chunks), story_context, parser_hints),
            model=model,
            output_schema=EXTRACTION_OUTPUT_SCHEMA,
            timeout_seconds=180,
        )
        # Um chunk com instabilidade (timeout, 429, JSON inválido) não derruba a
        # extração inteira: tenta de novo e, persistindo a falha, segue com os
        # chunks válidos — o merge determinístico por nome tolera parciais.
        data: dict[str, Any] | None = None
        for attempt in range(1, CHUNK_EXTRACTION_MAX_ATTEMPTS + 1):
            try:
                data = _result_payload(await provider.generate_structured(request))
                if data is not None:
                    break
                logger.warning(
                    "script_extraction_chunk_invalid_json project_id=%s chunk=%d/%d "
                    "attempt=%d; retrying",
                    project_id,
                    index,
                    len(chunks),
                    attempt,
                )
            except Exception as exc:
                logger.warning(
                    "script_extraction_chunk_failed project_id=%s chunk=%d/%d "
                    "attempt=%d error=%s; retrying",
                    project_id,
                    index,
                    len(chunks),
                    attempt,
                    exc,
                )
        if data is None:
            failed_chunks.append(index)
            continue
        characters.extend(
            cleaned
            for raw in data.get("characters", [])
            if (cleaned := _clean_extracted_item(raw)) is not None
        )
        locations.extend(
            cleaned
            for raw in data.get("locations", [])
            if (cleaned := _clean_extracted_item(raw, location=True)) is not None
        )
    if failed_chunks:
        logger.error(
            "script_extraction_chunks_lost project_id=%s chunks=%s of %d; "
            "entities from these chunks are missing",
            project_id,
            failed_chunks,
            len(chunks),
        )
    characters = _merge_extracted_items(
        [*characters, *_script_character_items(script_content)],
        entity_kind="character",
    )
    locations = _merge_extracted_items(
        [*locations, *_script_location_items(script_content)],
        entity_kind="location",
    )
    # Visibilidade: candidatos determinísticos do parser que a consolidação
    # final não manteve (omissões do LLM, nomes filtrados). Não altera o
    # resultado — registra para diagnóstico.
    coverage = visual_extraction_coverage(script_content, characters, locations)
    if coverage["missing_characters"]:
        logger.warning(
            "script_extraction_characters_missing project_id=%s missing=%s",
            project_id,
            coverage["missing_characters"],
        )
    if coverage["missing_locations"]:
        logger.warning(
            "script_extraction_locations_missing project_id=%s missing=%s",
            project_id,
            coverage["missing_locations"],
        )
    # Fase 2 (adjudicação global): com o inventário consolidado, uma passada
    # LLM de ENTRADA PEQUENA decide com visão global o que os chunks não
    # conseguem — exclusões com justificativa (objetos/eventos em caps de
    # destaque) e unificação de aliases entre cenas. Falha da fase é tolerada:
    # mantém todos os candidatos (comportamento anterior).
    if characters:
        verdict: dict[str, Any] | None = None
        adjudication_request = LLMRequest(
            task="adjudicate_visual_candidates",
            prompt=_adjudication_prompt(
                _adjudication_inventory(script_content, characters), story_context
            ),
            model=model,
            output_schema=ADJUDICATION_OUTPUT_SCHEMA,
            timeout_seconds=120,
        )
        for attempt in range(1, CHUNK_EXTRACTION_MAX_ATTEMPTS + 1):
            try:
                verdict = _result_payload(await provider.generate_structured(adjudication_request))
                if verdict is not None:
                    break
            except Exception as exc:
                logger.warning(
                    "script_extraction_adjudication_failed project_id=%s attempt=%d error=%s",
                    project_id,
                    attempt,
                    exc,
                )
        if verdict is not None:
            characters, exclusions, low_confidence = _apply_adjudication(characters, verdict)
            if exclusions:
                logger.info(
                    "script_extraction_adjudicated_exclusions project_id=%s excluded=%s",
                    project_id,
                    [entry["name"] for entry in exclusions],
                )
            if low_confidence:
                logger.info(
                    "script_extraction_low_confidence project_id=%s names=%s",
                    project_id,
                    [entry["name"] for entry in low_confidence],
                )
        else:
            logger.warning(
                "script_extraction_adjudication_unavailable project_id=%s; keeping all candidates",
                project_id,
            )
    if not characters and not locations:
        return [], []
    design_request = LLMRequest(
        task="design_visual_bible_profiles",
        prompt=_visual_design_prompt(characters, locations, story_context),
        model=model,
        output_schema=EXTRACTION_OUTPUT_SCHEMA,
        timeout_seconds=180,
    )
    try:
        design_data = _result_payload(await provider.generate_structured(design_request))
    except Exception as exc:
        logger.warning(
            "visual_direction_failed project_id=%s; using evidence-only profiles: %s",
            project_id,
            exc,
        )
        return characters, locations
    if design_data is None:
        logger.warning(
            "visual_direction_invalid_json project_id=%s; using evidence-only profiles",
            project_id,
        )
        return characters, locations
    designed_characters = [
        cleaned
        for raw in design_data.get("characters", [])
        if (cleaned := _clean_extracted_item(raw)) is not None
    ]
    designed_locations = [
        cleaned
        for raw in design_data.get("locations", [])
        if (cleaned := _clean_extracted_item(raw, location=True)) is not None
    ]
    return (
        _apply_visual_design(characters, designed_characters, entity_kind="character"),
        _apply_visual_design(locations, designed_locations, entity_kind="location"),
    )
