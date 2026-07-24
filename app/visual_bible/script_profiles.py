import re
import unicodedata

PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}

SCENE_LOCATION_RE = re.compile(
    r"(?im)^\s*(?:INT|EXT|INT/EXT|INTERIOR|EXTERIOR)\.?\s+(?P<location>.+?)\s*$"
)
SCRIPT_PROP_KEYWORDS = (
    "anel",
    "bilhete",
    "boneca",
    "brinquedo",
    "caderno",
    "cachimbo",
    "caixa",
    "caneta",
    "carta",
    "chave",
    "chocalho",
    "colher",
    "colar",
    "corda",
    "cumbuca",
    "diario",
    "desenho",
    "envelope",
    "faca",
    "fita",
    "flauta",
    "fotografia",
    "livro",
    "mala",
    "mochila",
    "panela",
    "partitura",
    "pote",
    "prato",
    "receita",
    "relogio",
    "retrato",
    "tabua",
    "tambor",
    "violino",
)


def _prompt_text(value: object) -> str:
    if isinstance(value, dict):
        parts = [
            f"{str(key).strip().replace('_', ' ').lower()}: {_prompt_text(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_prompt_text(item) for item in value if item not in (None, "", [], {}))
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


SCENE_LOCATION_CONTEXT_MARKERS = {
    "dia",
    "noite",
    "manha",
    "manhã",
    "tarde",
    "continuacao",
    "continuação",
    "flashback",
    "imagem final",
}


FEMININE_LOCATION_PARENTS = {"casa", "cidade", "cozinha", "escola", "sala"}


def _clean_script_location_name(value: str) -> str:
    parts = [
        re.sub(r"\([^)]*\)", "", part).strip(" .:-")
        for part in re.split(r"\s+-\s+", value)
    ]
    location_parts = [
        part for part in parts if part and _ascii_lower(part) not in SCENE_LOCATION_CONTEXT_MARKERS
    ]
    if len(location_parts) >= 2:
        head = _clean_script_entity_name(location_parts[-1])
        parent = _clean_script_entity_name(" ".join(location_parts[:-1]))
        parent_root = _ascii_lower(parent).split()[0]
        parent_prefix = "Da" if parent_root in FEMININE_LOCATION_PARENTS else "Do"
        return f"{head} {parent_prefix} {parent}".strip()
    return _clean_script_entity_name(location_parts[0] if location_parts else value)


GENERIC_LOCATION_ROOTS = {
    "casa",
    "cidade",
    "escola",
    "hospital",
    "jardim",
    "patio",
    "quarto",
    "sala",
    "telhado",
}


def _same_location_family(candidate: str, existing: str) -> bool:
    candidate_key = _entity_key(candidate)
    existing_key = _entity_key(existing)
    if not candidate_key or not existing_key or candidate_key == existing_key:
        return True
    if existing_key in candidate_key or candidate_key in existing_key:
        return True
    candidate_words = set(_ascii_lower(candidate).split())
    existing_words = set(_ascii_lower(existing).split())
    return bool(candidate_words & existing_words & GENERIC_LOCATION_ROOTS)


def _script_location_profile(name: str) -> dict:
    return {
        "name": name,
        "description": f"Ambiente extraido do roteiro: {name}",
        "layout": "geografia definida pelas acoes e entradas descritas no roteiro",
        "materials": "materiais, moveis e objetos visiveis no texto da cena",
        "lighting": "luz coerente com o periodo da slugline e o tom dramatico",
    }


def _append_script_location_profile(profiles: list[dict], seen: set[str], name: str) -> None:
    key = _entity_key(name)
    if not key or key in seen:
        return
    for index, item in enumerate(profiles):
        existing_name = str(item.get("name") or "")
        existing_key = _entity_key(existing_name)
        if not _same_location_family(name, existing_name):
            continue
        if existing_key in key and len(key) > len(existing_key):
            seen.discard(existing_key)
            seen.add(key)
            profiles[index] = _script_location_profile(name)
            return
        if key in existing_key:
            return
    seen.add(key)
    profiles.append(_script_location_profile(name))


def _script_location_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    for match in SCENE_LOCATION_RE.finditer(script_content):
        name = _clean_script_location_name(match.group("location"))
        if not name:
            continue
        _append_script_location_profile(profiles, seen, name)
        if len(profiles) >= 12:
            break
    return profiles


def _clean_script_prop_name(value: str) -> str:
    text = _clean_script_entity_name(value)
    text = re.split(
        r"(?i)\s+(?:e|ou|eh|é|esta|está|fica|parece|ve|vê|olha|pega|segura|sai|entra)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.split(
        r"(?i)\s+(?:no|na|nos|nas)\s+(?:chao|chão|mesa|parede|bolso|mao|mão|maos|mãos|ar)\b",
        text,
        maxsplit=1,
    )[0]
    return re.sub(r"\s+", " ", text).strip(" .:-")


def _script_prop_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    for keyword in SCRIPT_PROP_KEYWORDS:
        pattern = re.compile(
            rf"\b(?:um|uma|o|a|os|as|do|da|dos|das)?\s*"
            rf"((?:\w+\s+){{0,2}}{re.escape(keyword)}"
            r"(?:\s+(?!de\b|do\b|da\b|dos\b|das\b|com\b)\w+){0,2}"
            r"(?:\s+(?:de|do|da|dos|das|com)\s+\w+(?:\s+\w+){0,3})?)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(script_content):
            raw_name = match.group(1)
            keyword_match = re.search(rf"\b{re.escape(keyword)}\b", raw_name, re.IGNORECASE)
            if keyword_match is not None:
                raw_name = raw_name[keyword_match.start() :]
            name = _clean_script_prop_name(raw_name)
            if not name or len(name) < 3:
                continue
            key = _entity_key(name)
            if key in seen:
                continue
            seen.add(key)
            profiles.append(
                {
                    "name": name,
                    "narrative_importance": f"Objeto narrativo extraido do roteiro: {name}",
                    "material": "material visivel conforme descrito no roteiro",
                    "state": "estado coerente com a cena em que aparece",
                }
            )
            break
        if len(profiles) >= 12:
            break
    return profiles


SCRIPT_CHARACTER_EXCLUSIONS = {
    "FADE IN",
    "FADE OUT",
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
    "CENA",
    "MENINO",
    "MENINA",
    "GAROTO",
    "GAROTA",
    "CRIANCAS",
    "CRIANÇAS",
    "CRIANCA",
    "CRIANÇA",
}


def _character_exclusion_key(value: object) -> str:
    return re.sub(r"\s+", " ", _ascii_lower(value)).strip().upper()


def _looks_like_non_character_name(name: str) -> bool:
    key = _character_exclusion_key(name)
    exclusion_keys = {_character_exclusion_key(item) for item in SCRIPT_CHARACTER_EXCLUSIONS}
    if key in exclusion_keys:
        return True
    normalized = _ascii_lower(name)
    if normalized.startswith(("cena ", "volta ", "int ", "ext ")):
        return True
    if re.fullmatch(r"(?:os |as )?pais(?: de .+)?", normalized):
        return True
    return False


def _same_character_name(candidate: str, existing: str) -> bool:
    candidate_norm = _ascii_lower(candidate)
    existing_norm = _ascii_lower(existing)
    if candidate_norm == existing_norm:
        return True
    candidate_tokens = candidate_norm.split()
    existing_tokens = existing_norm.split()
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
    names: list[str] = []
    seen: set[str] = set()
    for raw_line in script_content.splitlines():
        for match in re.finditer(
            r"\b(?P<name>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{1,48})\s*\(",
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


def _script_character_profiles(script_content: str) -> list[dict]:
    return [
        {
            "name": name,
            "role": "personagem extraido do roteiro",
        }
        for name in _script_character_names(script_content)
    ]


def _is_placeholder_profile_name(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in PLACEHOLDER_PROFILE_NAMES


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



