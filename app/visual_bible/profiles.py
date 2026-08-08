import hashlib
import json
import re
import unicodedata


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
                normalized.get("nome") or normalized.get("title") or normalized.get("titulo")
                or fallback_name or identifier_name or role_name or "Item"
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


def _clean_visual_prop_name(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.split(
        r"(?i)\s+(?:que|onde|quando)\b|\s+(?:atras|atrás|dentro|embaixo|sobre|ao lado)\s+",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(
        r"(?i)\b(?:escondid[ao]s?|ocult[ao]s?|guardad[ao]s?)\b",
        "",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text

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
    visual_profile = {
        "layout": layout,
        "materials": materials,
        "palette": palette,
        "lighting": lighting,
    }
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
        "visual_profile": visual_profile,
        "asset_kind": "location",
        "spatial_rules": ["manter portas, janelas e moveis na mesma posicao"],
        "canonical_prompt": (
            f"Fotorrealista, fotografia de arquitetura cinematografica. {name}, ambiente vazio. "
            f"Funcao: {_prompt_text(description)}. Layout: {_prompt_text(layout)}. "
            f"Materiais: {_prompt_text(materials)}. Paleta: {_prompt_text(palette)}. "
            f"Luz: {_prompt_text(lighting)}. "
            "Mostrar entradas, portas, janelas, moveis principais e circulacao. "
            "Objetos em posicoes consistentes. Nenhuma péssoa, sem multidao, sem silhuetas. "
            "Local específico, filmavel, com textura realista."
        ),
    }


def _prop_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = _clean_visual_prop_name(raw.get("name") or "Objeto") or "Objeto"
    dimensions = _first_value(
        raw,
        "dimensions",
        "dimensoes",
        "dimensões",
        "tamanho",
        fallback="pequeno, manipulavel com uma mao",
    )
    material = _first_value(
        raw, "material", "materiais", fallback="material cotidiano com textura reconhecivel"
    )
    color = _first_value(
        raw, "color", "cor", "cores", fallback="cor neutra com detalhe visual memoravel"
    )
    state = _first_value(
        raw, "state", "estado", "condicao", "condição", fallback="usado mas preservado"
    )
    owner = _first_value(
        raw, "owner", "dono", "proprietario", "proprietário", fallback="protagonista"
    )
    narrative_importance = _short_text(
        _first_value(raw, "importance", "narrative_importance", "importancia", "importância"),
        "objeto de payoff narrativo",
        220,
    )
    narrative_profile = {
        "name": name,
        "owner": owner,
        "narrative_importance": narrative_importance,
    }
    visual_profile = {
        "dimensions": dimensions,
        "material": material,
        "color": color,
        "state": state,
    }
    return {
        "permanent_id": raw.get("id", f"prop_{hashlib.sha1(name.encode()).hexdigest()[:8]}"),
        "name": name,
        "dimensions": dimensions,
        "material": material,
        "color": color,
        "state": state,
        "owner": owner,
        "narrative_importance": narrative_importance,
        "scene_numbers": raw.get("scene_numbers", []),
        "evidence_text": raw.get("evidence_text", []),
        "importance": raw.get("importance", ""),
        "narrative_profile": narrative_profile,
        "visual_profile": visual_profile,
        "asset_kind": "prop",
        "canonical_prompt": (
            f"Fotorrealista, fotografia de produto. Um único {name}, inteiro e centralizado. "
            f"Dimensoes: {_prompt_text(dimensions)}. Material: {_prompt_text(material)}. "
            f"Cor: {_prompt_text(color)}. Estado: {_prompt_text(state)}. "
            "Referencia isolada do prop para continuidade visual; nao encenar a acao "
            "narrativa e nao incluir objetos citados no contexto. "
            "Silhueta clara, textura realista, detalhes legíveis. "
            "Sem mãos, sem pessoas, sem cenario, sem outros objetos."
        ),
    }


GENERIC_VISUAL_NAMES = {
    "character": {"", "item", "personagem", "personagem 1", "protagonista"},
    "location": {"", "item", "local", "local 1", "local principal", "cenario", "cenário"},
    "prop": {"", "item", "objeto", "objeto 1", "objeto de revelacao", "objeto de revelação"},
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
    "fim",
    "flashback",
    "imagem",
    "imagem final",
    "prologo",
    "prólogo",
    "volta ao presente",
}

WEAK_SET_DRESSING_PROP_NAMES = {
    "abajur",
    "almofada",
    "cama",
    "cadeira",
    "cortina",
    "janela",
    "lencol",
    "lençol",
    "mesa",
    "parede",
    "porta",
    "sofa",
    "sofá",
    "tapete",
    "travesseiro",
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
        item.get("name")
        or item.get("nome")
        or item.get("title")
        or item.get("titulo")
        or ""
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


def _has_strong_prop_evidence(item: dict) -> bool:
    evidence = _prompt_text(
        item.get("evidence_text")
        or item.get("evidencia")
        or item.get("evidência")
        or item.get("narrative_importance")
        or item.get("importance")
        or item.get("importancia")
        or item.get("importância")
        or ""
    )
    normalized = _ascii_lower(evidence)
    return bool(
        re.search(
            r"\b("
            r"pega|segura|entrega|recebe|abre|fecha|le|lê|esconde|revela|"
            r"encontra|guarda|carrega|mostra|usa|quebra|rasga|queima|"
            r"prova|pista|payoff|segredo|revelacao|revelação|chave"
            r")\b",
            normalized,
        )
    )


def _invalid_visual_item(target_kind: str, item: dict) -> bool:
    name = _visual_item_name(item)
    if _looks_like_screenplay_marker_name(name):
        return True
    if target_kind == "location" and _looks_like_temporal_location_name(name):
        return True
    if target_kind == "prop":
        normalized_name = re.sub(r"\s+", " ", _ascii_lower(name)).strip()
        if normalized_name in WEAK_SET_DRESSING_PROP_NAMES and not _has_strong_prop_evidence(
            item
        ):
            return True
    return False


def _visual_merge_key(target_kind: str, item: dict) -> str:
    key = _visual_key(item.get("id") or item.get("permanent_id"))
    if key:
        return key
    name = _visual_item_name(item)
    if target_kind == "prop":
        return _visual_key(_clean_visual_prop_name(name))
    if target_kind != "character":
        return _visual_key(name)
    tokens = _ascii_lower(name).split()
    while len(tokens) > 1 and tokens[0].strip(".") in VISUAL_CHARACTER_HONORIFIC_PREFIXES:
        tokens.pop(0)
    return _visual_key(" ".join(tokens) or name)


def _prefer_visual_item(candidate: dict, existing: dict) -> bool:
    candidate_name = _visual_item_name(candidate)
    existing_name = _visual_item_name(existing)
    candidate_score = len(candidate_name) + (10 if candidate.get("evidence_text") else 0)
    existing_score = len(existing_name) + (10 if existing.get("evidence_text") else 0)
    return candidate_score > existing_score


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
    elif target_kind == "location" and _looks_like_temporal_location_name(name):
        errors.append(f"name temporal em vez de local: {name}")
    if profile.get("asset_kind") != target_kind:
        errors.append(f"asset_kind deve ser {target_kind}")
    if not str(profile.get("canonical_prompt") or "").strip():
        errors.append("canonical_prompt vazio")

    if target_kind == "character":
        for key in ("role", "gender", "hair", "base_outfit", "palette"):
            if profile.get(key) in (None, "", [], {}):
                errors.append(f"{key} vazio")
        if _ascii_lower(profile.get("gender")) in {
            "péssoa",
            "personagem",
            "indefinido",
            "indefinida",
        }:
            errors.append("gender sem leitura visual masculina ou feminina")
    elif target_kind == "location":
        for key in ("description", "layout", "lighting"):
            if profile.get(key) in (None, "", [], {}):
                errors.append(f"{key} vazio")
    elif target_kind == "prop":
        for key in ("narrative_importance", "material", "color"):
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

from app.visual_bible.script_profiles import (  # noqa: E402,F401
    SCENE_LOCATION_RE,
    SCRIPT_CHARACTER_EXCLUSIONS,
    SCRIPT_PROP_KEYWORDS,
    _clean_script_entity_name,
    _is_placeholder_profile_name,
    _repair_missing_character_names,
    _script_character_names,
    _script_character_profiles,
    _script_location_profiles,
    _script_prop_profiles,
)

