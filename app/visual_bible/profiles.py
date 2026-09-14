import hashlib
import json
import re

from app.generation.prompt_language import ensure_portuguese_prompt_text
from app.visual_bible.character_profiles import (  # noqa: F401
    _character_gender,
    _character_gender_guardrail,
    _character_profile,
    _character_visual_defaults,
)
from app.visual_bible.prompt_balance import (
    LOCATION_PROMPT_MAX_WORDS,
    balanced_visual_prompt,
    concise_prompt_fragment,
)
from app.visual_bible.stable_choice import stable_choice

# Reexportação dos helpers de texto movidos para text_helpers (INC-05): o
# módulo character_profiles deixou de importar este arquivo, então a
# importação no topo não ativa mais o ciclo estrutural que existia antes.
# Os nomes continuam resolúveis como app.visual_bible.profiles._x para os
# consumidores existentes (service, upsert, profile_validation, testes).
from app.visual_bible.text_helpers import (  # noqa: F401
    _ascii_lower,
    _clean_prompt_fragment,
    _first_value,
    _humanize_identifier,
    _profile_mapping,
    _prompt_text,
    _role_display_name,
    _short_text,
)


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
        "distinctive_features",
        "caracteristicas_marcantes",
        "características_marcantes",
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
        "weight_kg",
        "peso_kg",
        "peso",
        "footwear",
        "calcados",
        "calçados",
        "sapatos",
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


def _short_scalar_item(value: object) -> bool:
    if value in (None, "", [], {}):
        return False
    return len(str(value).strip()) <= 90


def _is_internal_field_scalar(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return _is_profile_detail_key(text)


PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}


def _story_idea_protagonist_name(value: object) -> str:
    raw = value
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("nome") or ""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("{"):
        # O Idea Lab grava o protagonista como dict serializado em string
        # (ex.: "{'name': 'Elias', 'age': 55, ...}"); extrai o campo de nome.
        match = re.search(r"['\"](?:name|nome)['\"]\s*:\s*['\"]([^'\"]+)['\"]", text)
        text = match.group(1).strip() if match else ""
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


def _seeded_choice(seed: str, options: list[str], offset: int = 0) -> str:
    return stable_choice(seed, options, offset)


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
    """Return true only for two names that describe the same physical space.

    Word-order variants and descriptive qualifiers of the same space are merged
    (e.g. "Galpão" and "Galpão Abandonado"), while distinct sub-areas of one
    building remain separate continuity targets (e.g. "Hospital - Corredor" and
    "Hospital - Quarto 203").
    """
    name1 = str(loc1.get("name") or "")
    name2 = str(loc2.get("name") or "")

    tokens1 = _location_significant_token_set(name1)
    tokens2 = _location_significant_token_set(name2)
    if not tokens1 or not tokens2:
        return False
    if tokens1 == tokens2:
        return True
    smaller, larger = (tokens1, tokens2) if tokens1 < tokens2 else (tokens2, tokens1)
    if not smaller.issubset(larger):
        return False
    extra = larger - smaller
    return not any(token in LOCATION_SUBAREA_KEYWORDS for token in extra)


def _semantic_deduplicate_locations(locations: list[dict]) -> list[dict]:
    """Deduplicate locations that are semantically the same space.

    Word-order variants of the same space are merged, while distinct sub-areas of
    one building remain separate continuity targets.
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


def _location_visual_defaults(name: str) -> dict[str, object]:
    key = _ascii_lower(name)
    presets: tuple[tuple[tuple[str, ...], dict[str, object]], ...] = (
        (
            ("cozinha",),
            {
                "description": "uma cozinha residencial compacta, funcional e com sinais de uso",
                "layout": "uma bancada junto à parede, pia sob a janela e mesa pequena ao centro",
                "materials": ["azulejos antigos", "granito gasto", "madeira clara"],
                "palette": ["bege", "verde desbotado", "marrom"],
                "lighting": "luz natural lateral entrando pela janela",
                "key_objects": ["fogão de quatro bocas", "geladeira branca", "panelas usadas"],
            },
        ),
        (
            ("oficina", "garagem"),
            {
                "description": "uma oficina mecânica ampla, usada e marcada por graxa",
                "layout": (
                    "um vão central para veículos, bancadas nas laterais e ferramentas na parede"
                ),
                "materials": ["concreto manchado", "metal escuro", "madeira gasta"],
                "palette": ["cinza", "azul-petróleo", "ferrugem"],
                "lighting": "luz branca de luminárias industriais no teto",
                "key_objects": ["elevador automotivo", "caixa de ferramentas", "peças de motor"],
            },
        ),
        (
            ("hospital", "clinica", "consultorio"),
            {
                "description": (
                    "um ambiente hospitalar limpo, organizado e de aparência contemporânea"
                ),
                "layout": (
                    "um corredor central largo com portas alinhadas e balcão de atendimento "
                    "ao fundo"
                ),
                "materials": ["piso vinílico claro", "paredes brancas laváveis", "metal escovado"],
                "palette": ["branco", "verde-claro", "cinza"],
                "lighting": "luz branca uniforme de painéis embutidos no teto",
                "key_objects": ["cadeiras azuis", "carrinho médico", "placas sem texto legível"],
            },
        ),
        (
            ("rua", "avenida", "beco"),
            {
                "description": (
                    "uma via urbana brasileira com fachadas usadas e detalhes cotidianos"
                ),
                "layout": (
                    "calçada estreita dos dois lados, pista central e construções próximas à rua"
                ),
                "materials": ["asfalto remendado", "concreto", "tijolos pintados"],
                "palette": ["cinza", "ocre", "verde apagado"],
                "lighting": "luz natural suave atravessando as fachadas lateralmente",
                "key_objects": ["postes de concreto", "portões metálicos", "árvores pequenas"],
            },
        ),
        (
            ("casa", "apartamento", "sala", "quarto"),
            {
                "description": (
                    "um ambiente residencial brasileiro vivido, organizado e com marcas "
                    "discretas de uso"
                ),
                "layout": (
                    "móveis distribuídos junto às paredes e área central livre para circulação"
                ),
                "materials": ["piso de madeira", "paredes pintadas", "tecidos de algodão"],
                "palette": ["bege", "azul acinzentado", "madeira natural"],
                "lighting": "luz natural suave entrando por uma janela lateral",
                "key_objects": ["sofá de tecido", "mesa de madeira", "cortinas claras"],
            },
        ),
    )
    for markers, preset in presets:
        if any(marker in key for marker in markers):
            return dict(preset)
    return {
        "description": _seeded_choice(
            name,
            [
                "um ambiente amplo, usado e com detalhes arquitetônicos bem definidos",
                "um espaço de escala média, organizado e com sinais discretos de uso",
                "um ambiente compacto, funcional e visualmente marcado pelo tempo",
            ],
        ),
        "layout": _seeded_choice(
            name,
            [
                "uma área central livre, acessos laterais e móveis alinhados às paredes",
                "um eixo principal de circulação com volumes distribuídos nos dois lados",
                "um espaço principal aberto conectado a duas áreas menores ao fundo",
            ],
            1,
        ),
        "materials": ["concreto aparente", "madeira escura", "metal fosco"],
        "palette": ["cinza quente", "marrom", "azul apagado"],
        "lighting": "luz natural lateral suave combinada com luminárias de teto",
        "key_objects": ["mesa de madeira", "cadeiras usadas", "armário de metal"],
    }


def _location_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Local")
    defaults = _location_visual_defaults(name)
    description = _first_value(
        raw,
        "description",
        "descricao",
        "descrição",
        "mood",
        "atmosfera",
        fallback=defaults["description"],
    )
    layout = _first_value(
        raw,
        "layout",
        "planta",
        "disposicao",
        "disposição",
        fallback=defaults["layout"],
    )
    materials = _first_value(raw, "materials", "materiais", fallback=defaults["materials"])
    palette = _first_value(
        raw,
        "palette",
        "paleta",
        "paleta_de_cores",
        fallback=defaults["palette"],
    )
    lighting = _first_value(
        raw,
        "lighting",
        "iluminação",
        "iluminação",
        "luz",
        fallback=defaults["lighting"],
    )
    key_objects = _first_value(
        raw,
        "key_objects",
        "objetos_principais",
        "objetos_marcantes",
        "props_in_scene",
        "key_objects",
        "objetos_principais",
        "objetos_marcantes",
        fallback=defaults["key_objects"],
    )
    narrative_profile = {
        "name": name,
        "description": description,
    }
    def _flowing_fragment(value: object, max_words: int) -> str:
        """Fragmento sem pontuação de fim de frase: o prompt é UM período só."""
        text = concise_prompt_fragment(_prompt_text(value), max_words)
        return re.sub(r"\s*[.;:!]+\s*", ", ", text).strip(" ,").strip()

    # O prompt do local é UM ÚNICO PERÍODO: orações ligadas por vírgulas em
    # vez de frases separadas (relato do usuário, 2026-09) — modelos de
    # imagem tratam bem descrições corridas e a pontuação interna das
    # extrações LLM não quebra o texto em várias sentenças.
    clauses = [f"Crie a imagem de {concise_prompt_fragment(name, 10)}"]
    if description:
        clauses[0] += f", {_flowing_fragment(description, 28)}"
    if layout:
        clauses.append(f"o espaço organizado com {_flowing_fragment(layout, 24)}")
    if materials:
        clauses.append(f"materiais visíveis como {_flowing_fragment(materials, 16)}")
    if palette:
        clauses.append(f"cores predominantes em {_flowing_fragment(palette, 12)}")
    if lighting:
        clauses.append(f"iluminação de {_flowing_fragment(lighting, 16)}")
    if key_objects:
        clauses.append(f"objetos como {_flowing_fragment(key_objects, 16)}")
    canonical_prompt = ensure_portuguese_prompt_text(
        balanced_visual_prompt([", ".join(clauses) + "."], max_words=LOCATION_PROMPT_MAX_WORDS)
    )

    return {
        "permanent_id": raw.get(
            "id",
            # SEC-06: sha1 não-criptográfico (derivador determinístico de ID).
            f"loc_{hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()[:8]}",
        ),
        "name": name,
        "description": description,
        "layout": layout,
        "materials": materials,
        "palette": palette,
        "lighting": lighting,
        "key_objects": key_objects,
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
