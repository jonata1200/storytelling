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
    "descriÃ§Ã£o",
)
PROFILE_DETAIL_KEYS = frozenset(
    {
        "id",
        "role",
        "funcao",
        "funÃ§Ã£o",
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
        "genero",
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
        "disposiÃ§Ã£o",
        "materials",
        "materiais",
        "lighting",
        "iluminacao",
        "iluminaÃ§Ã£o",
        "luz",
        "props_in_scene",
        "spatial_rules",
        "dimensions",
        "dimensoes",
        "dimensÃµes",
        "tamanho",
        "material",
        "color",
        "cor",
        "cores",
        "state",
        "estado",
        "condicao",
        "condiÃ§Ã£o",
        "owner",
        "dono",
        "proprietario",
        "proprietÃ¡rio",
        "importance",
        "importancia",
        "importÃ¢ncia",
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
                _first_value(normalized, "role", "funcao", "funÃ§Ã£o", fallback="")
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


def _character_gender(raw_gender: object, name: str, role: object) -> str:
    explicit = _ascii_lower(raw_gender).strip()
    if explicit and explicit not in {"pessoa", "personagem", "indefinido", "indefinida"}:
        if any(term in explicit for term in ("fem", "mulher", "female", "woman")):
            return "personagem feminino"
        if any(term in explicit for term in ("masc", "homem", "male", "man")):
            return "personagem masculino"
        return f"genero visual definido: {_prompt_text(raw_gender)}"

    combined = f"{_ascii_lower(name)} {_ascii_lower(role)}"
    female_terms = {
        "dona",
        "senhora",
        "mae",
        "filha",
        "irma",
        "tia",
        "esposa",
        "viuva",
        "mulher",
        "menina",
        "garota",
        "neta",
        "professora",
        "medica",
    }
    male_terms = {
        "senhor",
        "pai",
        "filho",
        "irmao",
        "tio",
        "marido",
        "viuvo",
        "homem",
        "menino",
        "garoto",
        "neto",
        "professor",
        "medico",
    }
    female_names = {
        "clara",
        "marta",
        "maria",
        "ana",
        "helena",
        "lourdes",
        "celia",
        "beatriz",
        "julia",
        "sofia",
        "laura",
        "luiza",
        "alice",
        "mariana",
        "teresa",
        "rosa",
        "cristina",
    }
    male_names = {
        "lucas",
        "pedro",
        "joao",
        "jose",
        "antonio",
        "carlos",
        "miguel",
        "rafael",
        "gabriel",
        "mateus",
        "daniel",
        "paulo",
        "marcos",
        "andre",
        "luiz",
    }
    tokens = set(re.findall(r"[a-z]+", combined))
    first_name = next(iter(re.findall(r"[a-z]+", _ascii_lower(name))), "")
    if tokens & female_terms or first_name in female_names:
        return "personagem feminino"
    if tokens & male_terms or first_name in male_names:
        return "personagem masculino"
    if first_name.endswith("a"):
        return "personagem feminino"
    if first_name.endswith(("o", "os", "el")):
        return "personagem masculino"
    return _seeded_choice(name, ["personagem feminino", "personagem masculino"], 5)


def _character_gender_guardrail(gender: object) -> str:
    normalized = _ascii_lower(gender)
    if "fem" in normalized or "mulher" in normalized:
        return "Genero visual obrigatorio: feminino; nao masculinizar."
    if "masc" in normalized or "homem" in normalized:
        return "Genero visual obrigatorio: masculino; nao feminilizar."
    return f"Genero visual obrigatorio: {_prompt_text(gender)}."


def _character_visual_defaults(name: str) -> dict[str, object]:
    outfit_layers = [
        "casaco de linho verde musgo sobre camisa creme amarrotada",
        "jaqueta jeans clara com costuras aparentes e camiseta vinho",
        "cardiga azul petroleo com vestido floral discreto",
        "blazer cinza gasto, camisa branca sem gravata e calca escura",
        "sueter mostarda texturizado com saia preta simples",
        "camisa de algodao terracota com suspensorio marrom envelhecido",
        "vestido azul escuro com xale de la rustico",
        "jaqueta de couro caramelo marcada pelo uso e blusa neutra",
    ]
    hair_styles = [
        "cabelo castanho curto com franja irregular",
        "cabelo grisalho preso em coque baixo",
        "cabelo preto ondulado na altura dos ombros",
        "cabelo ruivo cacheado preso de lado",
        "cabelo raspado nas laterais com topo natural",
        "cabelo loiro escuro comprido, levemente despenteado",
        "tranÃ§as finas presas para tras",
        "cabelo branco curto, bem alinhado",
    ]
    eye_details = [
        "olhos cansados com olhar atento e sobrancelhas marcantes",
        "olhos pequenos e intensos, expressao desconfiada",
        "olhos grandes e melancolicos, brilho contido",
        "olhos claros, postura emocional reservada",
        "olhos escuros, olhar caloroso mas firme",
    ]
    body_types = [
        "silhueta alta e magra, postura levemente curvada",
        "corpo baixo e compacto, gestos precisos",
        "porte medio, ombros relaxados e presenca discreta",
        "corpo robusto, postura protetora",
        "silhueta delicada, movimentos contidos",
    ]
    palettes = [
        ["verde musgo", "creme envelhecido", "marrom quente"],
        ["azul petroleo", "vinho profundo", "cinza frio"],
        ["mostarda", "preto fosco", "branco antigo"],
        ["terracota", "caramelo", "azul desbotado"],
        ["lilas queimado", "grafite", "dourado suave"],
    ]
    origins = [
        "brasileira",
        "brasileira do interior",
        "brasileira urbana",
        "brasileira litoranea",
        "brasileira de origem nordestina",
    ]
    height_cm = 155 + (
        int(hashlib.sha1(f"{name}:height".encode()).hexdigest()[:8], 16) % 36
    )
    return {
        "origin": _seeded_choice(name, origins, 0),
        "height_cm": height_cm,
        "hair": _seeded_choice(name, hair_styles, 1),
        "eyes": _seeded_choice(name, eye_details, 2),
        "body_type": _seeded_choice(name, body_types, 3),
        "base_outfit": _seeded_choice(name, outfit_layers, 4),
        "palette": palettes[int(hashlib.sha1(name.encode()).hexdigest()[:8], 16) % len(palettes)],
    }


def _character_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Personagem")
    defaults = _character_visual_defaults(name)
    role = _short_text(_first_value(raw, "role", "funcao", "funÃ§Ã£o"), "personagem", 120)
    gender = _character_gender(
        _first_value(raw, "gender", "genero", "sexo", fallback=""),
        name,
        role,
    )
    origin = _first_value(raw, "origin", "origem", "nacionalidade", fallback=defaults["origin"])
    height_cm = _first_value(
        raw, "height_cm", "altura_cm", "altura", fallback=defaults["height_cm"]
    )
    apparent_age = _first_value(
        raw, "apparent_age", "idade_aparente", "idade", fallback="adulto de idade visual definida"
    )
    body_type = _first_value(
        raw, "body_type", "tipo_fisico", "corpo", fallback=defaults["body_type"]
    )
    face_shape = _first_value(
        raw,
        "face_shape",
        "formato_rosto",
        "rosto",
        fallback="rosto com estrutura clara e memoravel",
    )
    skin_tone = _first_value(
        raw, "skin_tone", "tom_de_pele", "pele", fallback="tom de pele natural sob luz cinematica"
    )
    eyes = _first_value(raw, "eyes", "olhos", fallback=defaults["eyes"])
    hair = _first_value(raw, "hair", "cabelo", fallback=defaults["hair"])
    base_outfit = _first_value(
        raw, "base_outfit", "figurino_base", "roupa", "figurino", fallback=defaults["base_outfit"]
    )
    palette = _first_value(
        raw, "palette", "paleta", "paleta_de_cores", fallback=defaults["palette"]
    )
    personality = _first_value(
        raw,
        "personality",
        "personalidade",
        fallback="personalidade especifica e coerente com a historia",
    )
    narrative_profile = {
        "name": name,
        "role": role,
        "personality": personality,
        "arc": _first_value(raw, "arc", "arco", fallback=""),
        "voice": raw.get("voice", "voz humana calorosa"),
    }
    visual_profile = {
        "gender": gender,
        "origin": origin,
        "height_cm": height_cm,
        "apparent_age": apparent_age,
        "body_type": body_type,
        "face_shape": face_shape,
        "skin_tone": skin_tone,
        "eyes": eyes,
        "hair": hair,
        "base_outfit": base_outfit,
        "palette": palette,
    }
    return {
        "permanent_id": raw.get("id", f"char_{hashlib.sha1(name.encode()).hexdigest()[:8]}"),
        "name": name,
        "role": role,
        "gender": gender,
        "origin": origin,
        "height_cm": height_cm,
        "apparent_age": apparent_age,
        "body_type": body_type,
        "face_shape": face_shape,
        "skin_tone": skin_tone,
        "eyes": eyes,
        "hair": hair,
        "base_outfit": base_outfit,
        "palette": palette,
        "voice": raw.get("voice", "voz humana calorosa"),
        "personality": personality,
        "arc": narrative_profile["arc"],
        "narrative_profile": narrative_profile,
        "visual_profile": visual_profile,
        "asset_kind": "character",
        "visual_constraints": [
            "manter idade aparente",
            "manter cabelo",
            "manter figurino base exclusivo deste personagem",
            "nao reutilizar roupa de outro personagem",
        ],
        "canonical_prompt": (
            "Fotorrealista, referencia de elenco, uma unica pessoa. "
            f"{_character_gender_guardrail(gender)} "
            f"{_prompt_text(gender).capitalize()} {_prompt_text(origin)}, "
            f"{_prompt_text(apparent_age)}, "
            f"{_prompt_text(body_type)}, {_prompt_text(height_cm)}cm. "
            f"Rosto {_prompt_text(face_shape)}, pele {_prompt_text(skin_tone)}, "
            f"olhos {_prompt_text(eyes)}, cabelo {_prompt_text(hair)}. "
            f"Papel: {_prompt_text(role)}. "
            f"Figurino base exclusivo: {_prompt_text(base_outfit)}. "
            f"Paleta: {_prompt_text(palette)}. "
            "Manter mesmo rosto, cabelo, corpo, figurino e paleta."
        ),
    }


def _location_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Local")
    description = _first_value(
        raw,
        "description",
        "descricao",
        "descriÃ§Ã£o",
        "mood",
        "atmosfera",
        fallback="local emocional da historia",
    )
    layout = _first_value(
        raw,
        "layout",
        "planta",
        "disposicao",
        "disposiÃ§Ã£o",
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
        "iluminacao",
        "iluminaÃ§Ã£o",
        "luz",
        fallback="luz natural suave com contraste cinematografico",
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
            "Objetos em posicoes consistentes. Nenhuma pessoa, sem multidao, sem silhuetas. "
            "Local especifico, filmavel, com textura realista."
        ),
    }


def _prop_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Objeto")
    dimensions = _first_value(
        raw,
        "dimensions",
        "dimensoes",
        "dimensÃµes",
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
        raw, "state", "estado", "condicao", "condiÃ§Ã£o", fallback="usado mas preservado"
    )
    owner = _first_value(
        raw, "owner", "dono", "proprietario", "proprietÃ¡rio", fallback="protagonista"
    )
    narrative_importance = _short_text(
        _first_value(raw, "importance", "narrative_importance", "importancia", "importÃ¢ncia"),
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
        "narrative_profile": narrative_profile,
        "visual_profile": visual_profile,
        "asset_kind": "prop",
        "canonical_prompt": (
            f"Fotorrealista, fotografia de produto. Um unico {name}, inteiro e centralizado. "
            f"Importancia: {_prompt_text(narrative_importance)}. "
            f"Dimensoes: {_prompt_text(dimensions)}. Material: {_prompt_text(material)}. "
            f"Cor: {_prompt_text(color)}. Estado: {_prompt_text(state)}. "
            f"Relacao narrativa: {_prompt_text(owner)}. "
            "Silhueta clara, textura realista, detalhes legiveis. "
            "Sem maos, sem pessoas, sem cenario, sem outros objetos."
        ),
    }


GENERIC_VISUAL_NAMES = {
    "character": {"", "item", "personagem", "personagem 1", "protagonista"},
    "location": {"", "item", "local", "local 1", "local principal", "cenario", "cenÃ¡rio"},
    "prop": {"", "item", "objeto", "objeto 1", "objeto de revelacao", "objeto de revelaÃ§Ã£o"},
}


def visual_profile_validation_errors(target_kind: str, profile: dict) -> list[str]:
    errors: list[str] = []
    name = str(profile.get("name") or "").strip()
    normalized_name = name.lower()
    if not name:
        errors.append("name vazio")
    elif normalized_name in GENERIC_VISUAL_NAMES.get(target_kind, set()):
        errors.append(f"name generico: {name}")
    if profile.get("asset_kind") != target_kind:
        errors.append(f"asset_kind deve ser {target_kind}")
    if not str(profile.get("canonical_prompt") or "").strip():
        errors.append("canonical_prompt vazio")

    if target_kind == "character":
        for key in ("role", "gender", "hair", "base_outfit", "palette"):
            if profile.get(key) in (None, "", [], {}):
                errors.append(f"{key} vazio")
        if _ascii_lower(profile.get("gender")) in {
            "pessoa",
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
        errors.append(f"target_kind invalido: {target_kind}")
    return errors


def _generic_visual_item(target_kind: str, item: dict) -> bool:
    name = str(item.get("name") or item.get("nome") or "").strip().lower()
    return name in GENERIC_VISUAL_NAMES.get(target_kind, set())


def _merge_profile_items(target_kind: str, primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged = [
        item
        for item in primary
        if not fallback or not _generic_visual_item(target_kind, item)
    ]
    seen = {
        _visual_key(item.get("id") or item.get("permanent_id") or item.get("name"))
        for item in merged
    }
    for item in fallback:
        key = _visual_key(item.get("id") or item.get("permanent_id") or item.get("name"))
        if not key or key in seen:
            continue
        merged.append(item)
        seen.add(key)
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
        if not re.fullmatch(r"[A-ZÃÃ‰ÃÃ“ÃšÃ‚ÃŠÃ”ÃƒÃ•Ã‡ ]{2,}", line):
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
            role = _first_value(profile, "role", "funcao", "funÃ§Ã£o", fallback="")
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
            role_name = _role_display_name(_first_value(profile, "role", "funcao", "funÃ§Ã£o"))
            if role_name and role_name.lower() != key:
                profile["name"] = role_name
                key = role_name.lower()
        if key:
            used_names.add(key)
        repaired.append(profile)
    return repaired


