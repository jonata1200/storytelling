import re

from app.visual_bible.profiles import (
    _ascii_lower,
    _looks_like_temporal_location_name,
    _visual_key,
)
from app.visual_bible.script_profiles import _looks_like_non_character_name

GENERIC_VISUAL_NAMES = {
    "character": {"", "item", "personagem", "personagem 1", "protagonista"},
    "location": {"", "item", "local", "local 1", "local principal", "cenario", "cenário"},
}

SCREENPLAY_MARKER_NAMES = {
    "abertura",
    "ato",
    "ato i",
    "ato ii",
    "ato iii",
    "capitulo",
    "capítulo",
    "cena",
    "corte para",
    "creditos",
    "créditos",
    "detalhes",
    "epilogo",
    "epílogo",
    "fade in",
    "fade out",
    "fade to black",
    "fim",
    "flashback",
    "imagem",
    "imagem final",
    "prologo",
    "prólogo",
    "volta ao presente",
}

VISUAL_CHARACTER_HONORIFIC_PREFIXES = {
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


def _visual_item_name(item: dict) -> str:
    name = str(
        item.get("name") or item.get("nome") or item.get("title") or item.get("titulo") or ""
    ).strip()
    return name


def _looks_like_screenplay_marker_name(value: object) -> bool:
    normalized = re.sub(r"\s+", " ", _ascii_lower(value)).strip()
    normalized = re.sub(r"\s*\([^)]*\)\s*", " ", normalized).strip()
    if normalized in SCREENPLAY_MARKER_NAMES:
        return True
    return normalized.startswith(
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
        )
    )


def _invalid_visual_item(target_kind: str, item: dict) -> bool:
    name = _visual_item_name(item)
    if _looks_like_screenplay_marker_name(name):
        return True
    if target_kind == "character" and _looks_like_non_character_name(name):
        return True
    if target_kind == "location" and _looks_like_temporal_location_name(name):
        return True
    return False


LOCATION_MERGE_STOPWORDS = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "na",
    "no",
    "nas",
    "nos",
    "em",
    "o",
    "a",
    "os",
    "as",
    "para",
    "com",
    "ao",
    "aos",
    "à",
    "às",
    "e",
}


def _location_merge_tokens(name: str) -> list[str]:
    clean = _ascii_lower(name)
    tokens = re.findall(r"[a-z0-9]+", clean)
    meaningful = [t for t in tokens if t not in LOCATION_MERGE_STOPWORDS]
    return meaningful or tokens


def _visual_merge_key(target_kind: str, item: dict) -> str:
    key = _visual_key(item.get("id") or item.get("permanent_id"))
    if key:
        return key
    name = _visual_item_name(item)
    if target_kind == "location":
        tokens = _location_merge_tokens(name)
        return "_".join(tokens) or _visual_key(name)
    if target_kind != "character":
        return _visual_key(name)
    tokens = _ascii_lower(name).split()
    while len(tokens) > 1 and tokens[0].strip(".") in VISUAL_CHARACTER_HONORIFIC_PREFIXES:
        tokens.pop(0)
    return _visual_key(" ".join(tokens) or name)


def _is_stub_visual_item(item: dict) -> bool:
    desc = str(item.get("description") or item.get("descricao") or "").strip().lower()
    return desc.startswith("ambiente extraido do roteiro") or desc.startswith(
        "ambiente extraído do roteiro"
    )


def _visual_item_quality_score(item: dict) -> int:
    score = 0
    desc = str(item.get("description") or item.get("descricao") or "").strip()
    if desc and not _is_stub_visual_item(item):
        score += 50 + min(len(desc), 100)
    name = _visual_item_name(item)
    score += len(name)
    if item.get("evidence_text"):
        score += 10
    if item.get("layout"):
        score += 15
    if item.get("lighting"):
        score += 15
    if item.get("materials"):
        score += 10
    return score


def _prefer_visual_item(candidate: dict, existing: dict) -> bool:
    return _visual_item_quality_score(candidate) > _visual_item_quality_score(existing)


def visual_profile_validation_errors(target_kind: str, profile: dict) -> list[str]:
    errors: list[str] = []
    name = str(profile.get("name") or "").strip()
    normalized_name = name.lower()
    if not name:
        errors.append("name vazio")
    elif normalized_name in GENERIC_VISUAL_NAMES.get(target_kind, set()):
        errors.append(f"name generico: {name}")
    elif _looks_like_screenplay_marker_name(name):
        errors.append(f"name marcador de roteiro: {name}")
    elif target_kind == "character" and _looks_like_non_character_name(name):
        errors.append(f"name sem corpo visual: {name}")
    elif target_kind == "location" and _looks_like_temporal_location_name(name):
        errors.append(f"name temporal em vez de local: {name}")
    if profile.get("asset_kind") != target_kind:
        errors.append(f"asset_kind deve ser {target_kind}")
    if not str(profile.get("canonical_prompt") or "").strip():
        errors.append("canonical_prompt vazio")

    if target_kind == "character":
        for key in ("role",):
            if profile.get(key) in (None, "", [], {}):
                errors.append(f"{key} vazio")
    elif target_kind == "location":
        for key in ("description", "layout", "lighting"):
            if profile.get(key) in (None, "", [], {}):
                errors.append(f"{key} vazio")
    else:
        errors.append(f"target_kind inválido: {target_kind}")
    return errors


def _generic_visual_item(target_kind: str, item: dict) -> bool:
    name = str(item.get("name") or item.get("nome") or "").strip().lower()
    return name in GENERIC_VISUAL_NAMES.get(target_kind, set())


def _merge_profile_items(target_kind: str, primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: dict[str, int] = {}

    def append(item: dict) -> None:
        if _invalid_visual_item(target_kind, item):
            return
        key = _visual_merge_key(target_kind, item)
        if not key:
            return
        if key in seen:
            existing_index = seen[key]
            if _prefer_visual_item(item, merged[existing_index]):
                merged[existing_index] = item
            return
        merged.append(item)
        seen[key] = len(merged) - 1

    for item in primary:
        if fallback and _generic_visual_item(target_kind, item):
            continue
        append(item)
    for item in fallback:
        append(item)
    return merged


def _raise_visual_profile_errors(target_kind: str, profiles: list[dict]) -> None:
    errors: list[str] = []
    for index, profile in enumerate(profiles, 1):
        errors.extend(
            f"{target_kind}[{index}]: {error}"
            for error in visual_profile_validation_errors(target_kind, profile)
        )
    if errors:
        raise ValueError("Biblioteca visual incompleta: " + "; ".join(errors))
