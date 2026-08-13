import re
import unicodedata
from dataclasses import dataclass

PLACEHOLDER_PROFILE_NAMES = {"", "item", "personagem", "protagonista"}

SCENE_LOCATION_RE = re.compile(
    r"(?im)^\s*(?:INT|EXT|INT/EXT|INTERIOR|EXTERIOR)\.?\s+(?P<location>.+?)\s*$"
)
SCENE_MARKER_RE = re.compile(
    r"(?im)^\s*CENA\s+0*(?P<number>\d+)(?:\s*[-:]\s*(?P<title>.+?))?\s*$"
)


@dataclass(frozen=True)
class ScriptScene:
    scene_number: int
    heading: str
    location: str
    period: str
    block: str
    action_lines: tuple[str, ...]
    dialogue_cues: tuple[str, ...]


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
    "madrugada",
    "amanhecer",
    "meia-noite",
    "meio-dia",
    "fim de tarde",
    "mais tarde",
    "noite seguinte",
    "dia seguinte",
    "manha seguinte",
    "manhã seguinte",
    "continuacao",
    "continuação",
    "flashback",
    "imagem final",
}


TEMPORAL_LOCATION_PREFIX_RE = re.compile(
    r"^(?:alguns?\s+)?(?:momentos?\s+depois|instantes?\s+depois|mais\s+tarde|"
    r"logo\s+depois|em\s+seguida|depois)\b",
    re.IGNORECASE,
)


FEMININE_LOCATION_PARENTS = {"casa", "cidade", "cozinha", "escola", "sala"}


def _clean_script_location_name(value: str) -> str:
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
        value = re.sub(r"(?i)^\s*(?:INT|EXT|INT/EXT|INTERIOR|EXTERIOR)\.?\s+", "", value)
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
    name = _clean_script_entity_name(location_parts[0] if location_parts else value)
    return "" if TEMPORAL_LOCATION_PREFIX_RE.search(_ascii_lower(name)) else name


def _script_heading_period(value: str) -> str:
    parts = [
        re.sub(r"\([^)]*\)", "", part).strip(" .:-")
        for part in re.split(r"\s+-\s+", value)
    ]
    for part in reversed(parts):
        if _ascii_lower(part) in SCENE_LOCATION_CONTEXT_MARKERS:
            return part.upper()
    return ""


def _looks_like_dialogue_cue(line: str) -> bool:
    text = re.sub(r"\([^)]*\)", "", line).strip(" .:-")
    if not text or len(text) > 48:
        return False
    if not re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{2,}", text):
        return False
    return not (_looks_like_non_character_name(text) or text.startswith(("INT", "EXT")))


def _parse_script_scenes(script_content: str) -> list[ScriptScene]:
    text = str(script_content or "").strip()
    if not text:
        return []
    matches = list(SCENE_MARKER_RE.finditer(text))
    if not matches:
        matches = []
    scenes: list[ScriptScene] = []
    scene_blocks: list[tuple[int, str]] = []
    if matches:
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            scene_blocks.append((int(match.group("number")), text[start:end].strip()))
    else:
        heading_matches = list(SCENE_LOCATION_RE.finditer(text))
        if heading_matches:
            for index, heading_match in enumerate(heading_matches):
                start = heading_match.start()
                end = (
                    heading_matches[index + 1].start()
                    if index + 1 < len(heading_matches)
                    else len(text)
                )
                scene_blocks.append((index + 1, text[start:end].strip()))
        else:
            scene_blocks.append((1, text))
    for scene_number, block in scene_blocks:
        parsed_heading_match = SCENE_LOCATION_RE.search(block)
        heading = parsed_heading_match.group(0).strip() if parsed_heading_match else ""
        raw_location = parsed_heading_match.group("location") if parsed_heading_match else ""
        location = _clean_script_location_name(raw_location) if raw_location else ""
        period = _script_heading_period(raw_location) if raw_location else ""
        action_lines: list[str] = []
        dialogue_cues: list[str] = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line == heading or SCENE_LOCATION_RE.match(line):
                continue
            if _looks_like_dialogue_cue(line):
                dialogue_cues.append(_clean_script_entity_name(line))
                continue
            if line.startswith("(") and line.endswith(")"):
                continue
            action_lines.append(line)
        scenes.append(
            ScriptScene(
                scene_number=scene_number,
                heading=heading,
                location=location,
                period=period,
                block=block,
                action_lines=tuple(action_lines),
                dialogue_cues=tuple(dialogue_cues),
            )
        )
    return scenes


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


def _candidate_importance(count: int, first_scene_number: int) -> str:
    if first_scene_number <= 2 or count >= 3:
        return "principal"
    if count == 2:
        return "recorrente"
    return "pontual"


def _append_metadata(item: dict, scene_number: int | None, evidence_text: str) -> None:
    if scene_number is not None:
        scene_numbers = item.setdefault("scene_numbers", [])
        if scene_number not in scene_numbers:
            scene_numbers.append(scene_number)
        item["importance"] = _candidate_importance(len(scene_numbers), min(scene_numbers))
    if evidence_text:
        evidences = item.setdefault("evidence_text", [])
        if evidence_text not in evidences:
            evidences.append(evidence_text)


def _script_location_profile(
    name: str, scene_number: int | None = None, evidence_text: str = ""
) -> dict:
    scene_numbers = [scene_number] if scene_number is not None else []
    return {
        "name": name,
        "description": f"Ambiente extraido do roteiro: {name}",
        "layout": "geografia definida pelas acoes e entradas descritas no roteiro",
        "materials": "materiais, moveis e objetos visiveis no texto da cena",
        "lighting": "luz coerente com o periodo da slugline e o tom dramatico",
        "scene_numbers": scene_numbers,
        "evidence_text": [evidence_text] if evidence_text else [],
        "importance": _candidate_importance(1, scene_number or 999),
    }


def _append_script_location_profile(
    profiles: list[dict],
    seen: set[str],
    name: str,
    scene_number: int | None = None,
    evidence_text: str = "",
) -> None:
    key = _entity_key(name)
    if not key or key in seen:
        for item in profiles:
            if _entity_key(item.get("name")) == key:
                _append_metadata(item, scene_number, evidence_text)
                break
        return
    for index, item in enumerate(profiles):
        existing_name = str(item.get("name") or "")
        existing_key = _entity_key(existing_name)
        if not _same_location_family(name, existing_name):
            continue
        if existing_key in key and len(key) > len(existing_key):
            seen.discard(existing_key)
            seen.add(key)
            profile = _script_location_profile(name, scene_number, evidence_text)
            for old_scene_number in item.get("scene_numbers", []):
                _append_metadata(profile, old_scene_number, "")
            for old_evidence in item.get("evidence_text", []):
                _append_metadata(profile, None, str(old_evidence))
            profiles[index] = profile
            return
        if key in existing_key:
            _append_metadata(item, scene_number, evidence_text)
            return
    seen.add(key)
    profiles.append(_script_location_profile(name, scene_number, evidence_text))


def _script_location_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    scenes = _parse_script_scenes(script_content)
    if scenes:
        for scene in scenes:
            name = scene.location
            if not name:
                continue
            _append_script_location_profile(
                profiles,
                seen,
                name,
                scene.scene_number,
                scene.heading,
            )
            if len(profiles) >= 12:
                break
        return profiles
    for match in SCENE_LOCATION_RE.finditer(script_content):
        name = _clean_script_location_name(match.group("location"))
        if not name:
            continue
        _append_script_location_profile(profiles, seen, name, None, match.group(0).strip())
        if len(profiles) >= 12:
            break
    return profiles













from app.visual_bible.script_prop_profiles import (  # noqa: E402,F401
    SCRIPT_PROP_KEYWORDS,
    _clean_script_prop_name,
    _prop_evidence_text,
    _prop_family_key,
    _prop_search_blocks,
    _script_prop_profile,
    _script_prop_profiles,
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

TEMPORAL_CHARACTER_MARKERS = {
    "crianca",
    "criança",
    "jovem",
    "adolescente",
    "adulto",
    "adulta",
    "velho",
    "velha",
    "idoso",
    "idosa",
    "futuro",
    "futura",
    "passado",
    "passada",
}

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
    "observador",
    "observadora",
    "inteligencia artificial",
    "inteligência artificial",
    "voz off",
)

NON_CORPOREAL_CHARACTER_WORDS = ("ia", "voz")

# Coletivos, equipes e grupos de pessoas que nao devem virar personagens.
# Os termos estao em forma ascii-lower pois a comparacao usa _ascii_lower().
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
    if any(
        re.search(rf"\b{re.escape(word)}\b", normalized) for word in NON_CORPOREAL_CHARACTER_WORDS
    ):
        return True
    if any(
        re.search(rf"\b{re.escape(word)}\b", normalized) for word in GROUP_CHARACTER_WORDS
    ):
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
    candidate_temporal = bool(set(candidate_norm.split()) & TEMPORAL_CHARACTER_MARKERS)
    existing_temporal = bool(set(existing_norm.split()) & TEMPORAL_CHARACTER_MARKERS)
    if candidate_temporal != existing_temporal:
        return False
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
    names: list[str] = []
    seen: set[str] = set()
    scenes = _parse_script_scenes(script_content)
    lines = (
        [line for scene in scenes for line in scene.block.splitlines()]
        if scenes
        else script_content.splitlines()
    )
    for raw_line in lines:
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


def _script_character_candidate_profiles(script_content: str) -> list[dict]:
    profiles: list[dict] = []
    names: list[str] = []
    seen: set[str] = set()

    def append(raw_name: str, scene_number: int | None, evidence_text: str) -> None:
        before = list(names)
        _append_script_character_name(names, seen, raw_name)
        if names == before:
            for item in profiles:
                item_name = _ascii_lower(item.get("name"))
                raw_clean_name = _ascii_lower(_clean_script_entity_name(raw_name))
                if item_name == raw_clean_name:
                    _append_metadata(item, scene_number, evidence_text)
                    break
            return
        current_names = {_ascii_lower(name) for name in names}
        profiles[:] = [
            item for item in profiles if _ascii_lower(item.get("name")) in current_names
        ]
        new_name = names[-1]
        profiles.append(
            {
                "name": new_name,
                "role": "personagem extraido do roteiro",
                "scene_numbers": [scene_number] if scene_number is not None else [],
                "evidence_text": [evidence_text] if evidence_text else [],
                "importance": _candidate_importance(1, scene_number or 999),
            }
        )

    scenes = _parse_script_scenes(script_content)
    if scenes:
        for scene in scenes:
            for raw_line in scene.block.splitlines():
                line = raw_line.strip()
                for match in re.finditer(
                    r"\b(?P<name>(?:(?:SR|SRA|DR|DRA)\.\s*)?"
                    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{1,48})\s*\(",
                    line,
                ):
                    append(match.group("name"), scene.scene_number, line)
                if _looks_like_dialogue_cue(line):
                    append(line, scene.scene_number, line)
        return profiles

    for raw_line in script_content.splitlines():
        line = raw_line.strip()
        for match in re.finditer(
            r"\b(?P<name>(?:(?:SR|SRA|DR|DRA)\.\s*)?"
            r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{1,48})\s*\(",
            line,
        ):
            append(match.group("name"), None, line)
        if _looks_like_dialogue_cue(line):
            append(line, None, line)
    return profiles


def _script_character_profiles(script_content: str) -> list[dict]:
    return _script_character_candidate_profiles(script_content)


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



