import re
import unicodedata
from typing import Any

PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}

# ---------------------------------------------------------------------------
# Funções auxiliares mantidas (usadas por profiles.py, service.py, etc.)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Funções de personagens (mantidas para compatibilidade)
# ---------------------------------------------------------------------------

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
)

NON_CORPOREAL_CHARACTER_NAMES = {"sistema"}

NON_CORPOREAL_CHARACTER_WORDS = ("ia", "voz")

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
    "I.A.",
    "INTELIGENCIA ARTIFICIAL",
    "INTELIGÊNCIA ARTIFICIAL",
    "MENINO",
    "MENINA",
    "GAROTO",
    "GAROTA",
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
    if candidate_tokens[0] != existing_tokens[0]:
        return False
    return candidate_norm in existing_norm or existing_norm in candidate_norm


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


def _script_character_names(script_content: str) -> list[str]:
    """Extrai nomes de personagens do roteiro (usado como fallback)."""
    names: list[str] = []
    seen: set[str] = set()
    for raw_line in script_content.splitlines():
        for match in re.finditer(
            r"\b(?P<name>(?:(?:SR|SRA|DR|DRA)\.\s*)?"
            r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{1,48})\s*\(",
            raw_line,
        ):
            _append_script_character_name(names, seen, match.group("name"))
        line = re.sub(r"\([^)]*\)", "", raw_line).strip(" .:-")
        if not line or len(line) > 48:
            continue
        if not re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{2,}", line):
            continue
        if _looks_like_non_character_name(line) or line.startswith(("INT", "EXT")):
            continue
        _append_script_character_name(names, seen, line)
    return names


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


# ---------------------------------------------------------------------------
# Extração via Meta LLM
# ---------------------------------------------------------------------------


async def _llm_extract_characters_and_locations(
    session: Any,
    project_id: object,
    script_content: str,
) -> tuple[list[dict], list[dict]]:
    """Extrai personagens e locais do roteiro usando Meta LLM.

    Retorna (personagens, locais) como listas de perfis.
    """
    from uuid import UUID as _UUID

    from app.generation.model_settings import llm_provider_for_task
    from app.providers.llm.types import LLMRequest

    provider, model = await llm_provider_for_task(
        session, _UUID(str(project_id)), "generate_visual_bible"
    )

    # Truncar roteiro para caber no contexto do LLM
    max_chars = 8000
    truncated = script_content[:max_chars]
    if len(script_content) > max_chars:
        truncated += "\n\n[...] (roteiro truncado)"

    prompt = f"""Analise o roteiro abaixo e extraia APENAS os personagens e locais reais.

REGRAS:
- Personagens: apenas pessoas com nome proprio que participam da historia.
  NAO inclua: narrador, voz off, IA, emocoes (medo, amor), coletivos (equipe, familia),
  generos (homem, mulher, crianca), ou termos genericos.
- Locais: apenas ambientes fisicos onde as cenas acontecem.
  NAO inclua: periodos (dia, noite), timestamps, ou descricoes vagas.
  Cada local deve ter UM unico nome limpo
  (ex: "Estacao Espacial", nao "INT. Estacao Espacial - Dia").

Responda APENAS com JSON valido no formato:
{{
  "characters": [
    {{"name": "Nome", "role": "descricao do papel na historia"}}
  ],
  "locations": [
    {{"name": "Nome do Local", "description": "descricao curta do ambiente"}}
  ]
}}

ROTEIRO:
{truncated}"""

    request = LLMRequest(
        task="extract_characters_locations",
        prompt=prompt,
        model=model,
        max_tokens=1024,
        temperature=0.1,
    )
    result = await provider.generate_structured(request)

    # Parse do JSON retornado pelo LLM
    import json as _json

    text = str(result.raw_content or "").strip()
    # Remover markdown code blocks se presentes
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        return [], []

    characters = [
        {"name": str(c.get("name", "")).strip(), "role": str(c.get("role", "")).strip()}
        for c in (data.get("characters") or [])
        if str(c.get("name", "")).strip()
    ]
    locations = [
        {
            "name": str(loc.get("name", "")).strip(),
            "description": str(loc.get("description", "")).strip(),
        }
        for loc in (data.get("locations") or [])
        if str(loc.get("name", "")).strip()
    ]
    return characters, locations
