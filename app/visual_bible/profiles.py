import hashlib
import json
import re
import unicodedata

from app.generation.prompt_language import ensure_portuguese_prompt_text


def _fingerprint(payload: dict) -> dict:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return {
        "schema_version": 1,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "canonical_prompt": payload.get("canonical_prompt", ""),
        "reference_asset_ids": [],
    }


def _profile_sha256(payload: dict) -> str:
    return str(_fingerprint(payload)["sha256"])


def _visual_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _visual_profile_identity(profile: dict) -> str:
    permanent_id = _visual_key(profile.get("permanent_id"))
    if permanent_id:
        return permanent_id
    return _visual_key(profile.get("name"))


def _profile_items(value: object) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[dict] = []
        for item in value:
            if _is_internal_field_scalar(item):
                continue
            if isinstance(item, list):
                items.extend(_profile_items(item))
            else:
                items.append(_profile_mapping(item))
        return items
    if isinstance(value, dict):
        if _looks_like_single_profile(value):
            return [_profile_mapping(value)]
        mapped_items: list[dict] = []
        for key, item in value.items():
            if isinstance(item, dict):
                if _looks_like_single_profile(item):
                    mapped_items.append(
                        _profile_mapping(item, fallback_name=_humanize_identifier(key))
                    )
                else:
                    mapped_items.extend(_profile_items(item))
            elif isinstance(item, list):
                mapped_items.extend(_profile_items(item))
            elif not _is_profile_detail_key(key) and _short_scalar_item(item):
                mapped_items.append(_profile_mapping(item))
        return mapped_items
    return [_profile_mapping(value)]


def _payload_section(payload: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    for container_key in ("visual_bible", "story_bible", "bible", "universo_visual"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            value = _payload_section(container, keys)
            if value:
                return value
    return None


PROFILE_NAME_KEYS = (
    "name",
    "nome",
    "title",
    "titulo",
    "description",
    "descricao",
    "descrição",
)
PROFILE_DETAIL_KEYS = frozenset(
    {
        "id",
        "role",
        "funcao",
        "função",
        "arc",
        "arco",
        "personality",
        "personalidade",
        "palette",
        "paleta",
        "paleta_de_cores",
        "apparent_age",
        "idade_aparente",
        "idade",
        "body_type",
        "tipo_fisico",
        "corpo",
        "face_shape",
        "formato_rosto",
        "rosto",
        "skin_tone",
        "tom_de_pele",
        "pele",
        "eyes",
        "olhos",
        "hair",
        "cabelo",
        "base_outfit",
        "figurino_base",
        "roupa",
        "figurino",
        "gender",
        "gênero",
        "sexo",
        "origin",
        "origem",
        "nacionalidade",
        "height_cm",
        "altura_cm",
        "altura",
        "mood",
        "atmosfera",
        "layout",
        "planta",
        "disposicao",
        "disposição",
        "materials",
        "materiais",
        "lighting",
        "iluminação",
        "luz",
        "props_in_scene",
        "spatial_rules",
        "dimensions",
        "dimensoes",
        "dimensões",
        "tamanho",
        "material",
        "color",
        "cor",
        "cores",
        "state",
        "estado",
        "condicao",
        "condição",
        "owner",
        "dono",
        "proprietario",
        "proprietário",
        "importance",
        "importancia",
        "importância",
        "narrative_importance",
    }
)


def _is_profile_detail_key(key: object) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized in PROFILE_DETAIL_KEYS:
        return True
    return any(
        normalized.startswith(f"{prefix}_")
        for prefix in (
            "arc",
            "arco",
            "personality",
            "personalidade",
            "palette",
            "paleta",
            "hair",
            "cabelo",
            "eyes",
            "olhos",
            "role",
            "funcao",
            "local",
            "objeto",
        )
    )


def _looks_like_single_profile(value: dict) -> bool:
    return any(key in value for key in PROFILE_NAME_KEYS) or any(
        _is_profile_detail_key(key) for key in value
    )


def _humanize_identifier(value: object) -> str:
    text = str(value or "").strip().strip("_-")
    if not text:
        return "Item"
    prefixes = ("char_", "loc_", "prop_", "personagem_", "local_", "objeto_")
    lower_text = text.lower()
    for prefix in prefixes:
        if lower_text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return " ".join(part for part in text.replace("-", "_").split("_") if part).title() or "Item"


def _short_scalar_item(value: object) -> bool:
    if value in (None, "", [], {}):
        return False
    return len(str(value).strip()) <= 90


def _is_internal_field_scalar(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return _is_profile_detail_key(text)


def _prompt_text(value: object) -> str:
    if isinstance(value, dict):
        parts = [
            f"{_humanize_identifier(key).lower()}: {_prompt_text(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_prompt_text(item) for item in value if item not in (None, "", [], {}))
    return str(value or "").strip()


def _clean_prompt_fragment(value: object, prefixes: tuple[str, ...]) -> str:
    text = _prompt_text(value).strip()
    if not text:
        return ""
    for prefix in prefixes:
        clean_prefix = re.escape(prefix.strip())
        if not clean_prefix:
            continue
        stripped = re.sub(
            rf"^{clean_prefix}\b[\s:,\-]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        if stripped != text:
            return stripped
        if re.fullmatch(clean_prefix, text, flags=re.IGNORECASE):
            return ""
    return text


PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}


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


def _story_idea_protagonist_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.split(r"[,;(\n]", text, maxsplit=1)[0]
    text = re.sub(r"\b\d+\s*anos?.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text.title()


def _is_primary_protagonist_role(value: object) -> bool:
    text = str(value or "").strip().lower()
    if "co-protagonista" in text or "coprotagonista" in text or "co protagonista" in text:
        return False
    return text == "protagonista" or text.startswith("protagonista ")


def _profile_mapping(raw: object, fallback_name: str | None = None) -> dict:
    if isinstance(raw, dict):
        normalized = dict(raw)
        if not normalized.get("name"):
            identifier_name = (
                _humanize_identifier(normalized.get("id")) if normalized.get("id") else ""
            )
            role_name = _role_display_name(
                _first_value(normalized, "role", "funcao", "função", fallback="")
            )
            normalized["name"] = (
                normalized.get("nome")
                or normalized.get("title")
                or normalized.get("titulo")
                or fallback_name
                or identifier_name
                or role_name
                or "Item"
            )
        return normalized
    text = str(raw or "").strip()
    return {"name": text or "Item", "description": text}


def _short_text(value: object, fallback: str, max_length: int) -> str:
    text = str(value or fallback).strip() or fallback
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3].rstrip()}..."


def _first_value(raw: dict, *keys: str, fallback: object = "") -> object:
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return fallback


def _seeded_choice(seed: str, options: list[str], offset: int = 0) -> str:
    digest = hashlib.sha1(f"{seed}:{offset}".encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _ascii_lower(value: object) -> str:
    text = _prompt_text(value)
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


TEMPORAL_LOCATION_PREFIX_RE = re.compile(
    r"^(?:alguns?\s+)?(?:momentos?\s+depois|instantes?\s+depois|mais\s+tarde|"
    r"logo\s+depois|em\s+seguida|depois)\b",
    re.IGNORECASE,
)


def _looks_like_temporal_location_name(value: object) -> bool:
    return bool(TEMPORAL_LOCATION_PREFIX_RE.search(_ascii_lower(value)))


# Common location suffixes/prefixes that indicate sub-areas of the same building
LOCATION_SUBAREA_KEYWORDS = {
    "hall",
    "corredor",
    "elevador",
    "escada",
    "entrada",
    "saida",
    "sala",
    "consultorio",
    "escritorio",
    "quarto",
    "banheiro",
    "cozinha",
    "sala de espera",
    "recepcao",
    "parking",
    "estacionamento",
    "garagem",
}

BUILDING_KEYWORDS = {
    "hospital",
    "escola",
    "universidade",
    "museu",
    "igreja",
    "templo",
    "banco",
    "hotel",
    "escritorio",
    "escritório",
    "empresa",
    "sede",
    "fabrica",
    "fábrica",
    "prisao",
    "prisão",
    "tribunal",
    "casa",
    "mansao",
    "mansão",
    "apartamento",
    "condominio",
    "condomínio",
    "edificio",
    "edifício",
    "predio",
    "prédio",
    "estacao",
    "estação",
    "estacao orbital",
    "estação orbital",
    "nave",
    "espaconave",
    "espaçonave",
    "base",
    "laboratorio",
    "laboratório",
    "observatorio",
    "observatório",
    "armazem",
    "armazém",
    "galpao",
    "galpão",
    "hangar",
    "abrigo",
    "bunker",
    "complexo",
    "torre",
    "plataforma",
    "centro",
    "clinica",
    "clínica",
}


def _extract_building_keyword(name: str) -> str:
    """Extract the main building/structure keyword from a location name."""
    normalized = _ascii_lower(name)
    for keyword in BUILDING_KEYWORDS:
        if keyword in normalized:
            return keyword
    return ""


def _is_subarea_of_building(name: str) -> bool:
    """Check if a location name looks like a sub-area of a building."""
    normalized = _ascii_lower(name)
    for keyword in LOCATION_SUBAREA_KEYWORDS:
        if keyword in normalized:
            return True
    return False


def _location_significant_token_set(name: str) -> set[str]:
    stopwords = {
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
    tokens = re.findall(r"[a-z0-9]+", _ascii_lower(name))
    meaningful = {t for t in tokens if t not in stopwords and len(t) > 1}
    return meaningful or set(tokens)


def _locations_share_building(loc1: dict, loc2: dict) -> bool:
    """Check if two locations belong to the same building/structure or are similar."""
    name1 = str(loc1.get("name") or "")
    name2 = str(loc2.get("name") or "")

    tokens1 = _location_significant_token_set(name1)
    tokens2 = _location_significant_token_set(name2)
    if tokens1 and tokens2:
        if tokens1 == tokens2:
            return True
        intersection = tokens1.intersection(tokens2)
        smaller_size = min(len(tokens1), len(tokens2))
        if smaller_size >= 2 and len(intersection) == smaller_size:
            return True
        union = tokens1.union(tokens2)
        if union and (len(intersection) / len(union)) >= 0.60:
            return True

    building1 = _extract_building_keyword(name1)
    building2 = _extract_building_keyword(name2)

    # Both have the same building keyword (e.g., both are "hospital" or "estacao")
    if building1 and building1 == building2:
        return True

    # Check if one location name is contained in the other
    normalized1 = _ascii_lower(name1)
    normalized2 = _ascii_lower(name2)
    if len(normalized1) > 5 and len(normalized2) > 5:
        if normalized1 in normalized2 or normalized2 in normalized1:
            return True

    return False


def _semantic_deduplicate_locations(locations: list[dict]) -> list[dict]:
    """Deduplicate locations that are semantically the same space.

    For example, 'Hospital Do Hall De Entrada' and 'Hall de entrada do hospital'
    should be merged into a single location.
    """
    if len(locations) <= 1:
        return locations

    merged: list[dict] = []
    used: set[int] = set()

    for i, loc in enumerate(locations):
        if i in used:
            continue

        # Find all locations that are semantically similar to this one
        similar_indices = [i]
        for j in range(i + 1, len(locations)):
            if j in used:
                continue
            if _locations_share_building(loc, locations[j]):
                similar_indices.append(j)

        if len(similar_indices) == 1:
            # No similar locations found, keep as-is
            merged.append(loc)
        else:
            # Merge similar locations - keep the most descriptive one
            def _location_quality_score(idx: int) -> int:
                item = locations[idx]
                desc = str(item.get("description") or "").strip()
                is_stub = desc.lower().startswith(
                    "ambiente extraido do roteiro"
                ) or desc.lower().startswith("ambiente extraído do roteiro")
                score = (0 if is_stub else 100) + len(desc) + len(str(item.get("name") or ""))
                if item.get("layout"):
                    score += 20
                if item.get("lighting"):
                    score += 20
                if item.get("materials"):
                    score += 10
                return score

            best_idx = max(similar_indices, key=_location_quality_score)
            best_loc = dict(locations[best_idx])

            # Combine evidence from all similar locations
            all_evidence = []
            all_scene_numbers = []
            for idx in similar_indices:
                evidence = locations[idx].get("evidence_text", [])
                if isinstance(evidence, list):
                    all_evidence.extend(evidence)
                scene_nums = locations[idx].get("scene_numbers", [])
                if isinstance(scene_nums, list):
                    all_scene_numbers.extend(scene_nums)

            # Remove duplicates while preserving order
            seen_evidence = set()
            unique_evidence = []
            for e in all_evidence:
                e_str = str(e)
                if e_str not in seen_evidence:
                    seen_evidence.add(e_str)
                    unique_evidence.append(e)

            seen_scenes = set()
            unique_scenes = []
            for s in all_scene_numbers:
                if s not in seen_scenes:
                    seen_scenes.add(s)
                    unique_scenes.append(s)

            best_loc["evidence_text"] = unique_evidence
            best_loc["scene_numbers"] = unique_scenes

            # Mark all similar locations as used
            for idx in similar_indices:
                used.add(idx)

            merged.append(best_loc)

    return merged


from app.visual_bible.character_profiles import (  # noqa: E402,F401
    _character_gender,
    _character_gender_guardrail,
    _character_profile,
    _character_visual_defaults,
)


def _location_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Local")
    description = _first_value(
        raw,
        "description",
        "descricao",
        "descrição",
        "mood",
        "atmosfera",
        fallback="local emocional da historia",
    )
    layout = _first_value(
        raw,
        "layout",
        "planta",
        "disposicao",
        "disposição",
        fallback="espaco com pontos de camera claros",
    )
    materials = _first_value(
        raw, "materials", "materiais", fallback=["madeira", "parede clara", "tecidos simples"]
    )
    palette = _first_value(
        raw,
        "palette",
        "paleta",
        "paleta_de_cores",
        fallback=["azul frio", "dourado quente", "neutros gastos"],
    )
    lighting = _first_value(
        raw,
        "lighting",
        "iluminação",
        "iluminação",
        "luz",
        fallback="luz natural suave com contraste cinematográfico",
    )
    narrative_profile = {
        "name": name,
        "description": description,
    }
    # Montar prompt textual simplificado (apenas "ativo" para referencia)
    parts = [f"{name}."]
    if description:
        parts.append(f"{_prompt_text(description)}.")
    if layout:
        parts.append(f"Organizacao: {_prompt_text(layout)}.")
    if materials:
        parts.append(f"Materiais: {_prompt_text(materials)}.")
    if palette:
        parts.append(f"Paleta: {_prompt_text(palette)}.")
    if lighting:
        parts.append(f"Iluminacao: {_prompt_text(lighting)}.")
    canonical_prompt = ensure_portuguese_prompt_text(" ".join(parts))

    return {
        "permanent_id": raw.get("id", f"loc_{hashlib.sha1(name.encode()).hexdigest()[:8]}"),
        "name": name,
        "description": description,
        "layout": layout,
        "materials": materials,
        "palette": palette,
        "lighting": lighting,
        "scene_numbers": raw.get("scene_numbers", []),
        "evidence_text": raw.get("evidence_text", []),
        "importance": raw.get("importance", ""),
        "narrative_profile": narrative_profile,
        "asset_kind": "location",
        "canonical_prompt": canonical_prompt,
    }


from app.visual_bible.profile_validation import (  # noqa: E402,F401
    GENERIC_VISUAL_NAMES,
    SCREENPLAY_MARKER_NAMES,
    VISUAL_CHARACTER_HONORIFIC_PREFIXES,
    _generic_visual_item,
    _invalid_visual_item,
    _looks_like_screenplay_marker_name,
    _merge_profile_items,
    _prefer_visual_item,
    _raise_visual_profile_errors,
    _visual_item_name,
    _visual_merge_key,
    visual_profile_validation_errors,
)
from app.visual_bible.script_profiles import (  # noqa: E402,F401
    SCRIPT_CHARACTER_EXCLUSIONS,
    _clean_script_entity_name,
    _is_placeholder_profile_name,
    _looks_like_non_character_name,
    _repair_missing_character_names,
    _script_character_names,
)
