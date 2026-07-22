import re

from app.visual_bible.profiles import (
    PLACEHOLDER_PROFILE_NAMES,
    _first_value,
    _is_primary_protagonist_role,
    _role_display_name,
)

SCENE_LOCATION_RE = re.compile(
    r"(?im)^\s*(?:INT|EXT|INT/EXT|INTERIOR|EXTERIOR)\.?\s+(?P<location>.+?)\s*$"
)
SCRIPT_PROP_KEYWORDS = (
    "anel",
    "bilhete",
    "boneca",
    "brinquedo",
    "caixa",
    "caneta",
    "carta",
    "chave",
    "colher",
    "colar",
    "cumbuca",
    "diario",
    "envelope",
    "faca",
    "fita",
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
)


def _clean_script_entity_name(value: str) -> str:
    text = re.sub(r"\([^)]*\)", "", value)
    text = re.split(r"\s+-\s+", text, maxsplit=1)[0]
    text = re.sub(r"\b\d+\s*s\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text.title()


def _script_location_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    for match in SCENE_LOCATION_RE.finditer(script_content):
        name = _clean_script_entity_name(match.group("location"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        profiles.append(
            {
                "name": name,
                "description": f"Ambiente extraido do roteiro: {name}",
                "layout": "geografia definida pelas acoes e entradas descritas no roteiro",
                "materials": "materiais, moveis e objetos visiveis no texto da cena",
                "lighting": "luz coerente com o periodo da slugline e o tom dramatico",
            }
        )
        if len(profiles) >= 6:
            break
    return profiles


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
            name = _clean_script_entity_name(raw_name)
            if not name or len(name) < 3:
                continue
            key = name.lower()
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
        if len(profiles) >= 6:
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
}


def _script_character_names(script_content: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw_line in script_content.splitlines():
        line = re.sub(r"\([^)]*\)", "", raw_line).strip(" .:-")
        if not line or len(line) > 48:
            continue
        if not re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{2,}", line):
            continue
        if line in SCRIPT_CHARACTER_EXCLUSIONS or line.startswith(("INT", "EXT")):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(line.title())
    return names


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



