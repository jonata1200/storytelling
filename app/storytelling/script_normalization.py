import json
import re
import unicodedata

from app.storytelling.normalization_common import (
    GenerationOutputError,
    _coerce_positive_int,
    _first_non_empty,
)
from app.storytelling.script_contracts import expected_script_scene_count


def _script_block_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(text for item in value if (text := _script_block_to_text(item)))
    if not isinstance(value, dict):
        return str(value).strip() if value is not None else ""

    label_order = [
        "scene_number",
        "number",
        "title",
        "heading",
        "duration_seconds",
        "summary",
        "objective",
        "characters",
        "location",
        "setting",
        "action",
        "narration",
        "narration_text",
        "dialogue",
        "dialogue_text",
        "storyboard",
        "storyboard_direction",
        "video",
        "video_direction",
        "camera_movement",
    ]
    labels = {
        "scene_number": "Cena",
        "number": "Numero",
        "title": "Titulo",
        "heading": "Cabecalho",
        "duration_seconds": "Duracao",
        "summary": "Resumo",
        "objective": "Objetivo dramatico",
        "characters": "Personagens",
        "location": "Local",
        "setting": "Ambiente",
        "action": "Acao",
        "narration": "Narracao",
        "narration_text": "Narracao",
        "dialogue": "Dialogo",
        "dialogue_text": "Dialogo",
        "storyboard": "Indicacao para storyboard",
        "storyboard_direction": "Indicacao para storyboard",
        "video": "Indicacao para video",
        "video_direction": "Indicacao para video",
        "camera_movement": "Movimento de camera",
    }
    lines: list[str] = []
    for key in label_order:
        if key not in value:
            continue
        text = _script_block_to_text(value[key])
        if text:
            lines.append(f"{labels[key]}: {text}")
    return "\n".join(lines)


def _json_mapping_from_text(value: object) -> dict | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    payload_keys = {
        "content",
        "script",
        "roteiro",
        "scenes",
        "cenas",
        "acts",
        "atos",
        "beats",
    }
    decoder = json.JSONDecoder()
    candidates = [0] if text.startswith("{") else []
    candidates.extend(index for index, char in enumerate(text) if char == "{" and index != 0)
    for index in candidates:
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and payload_keys.intersection(parsed):
            return parsed
    content_match = re.search(r'"content"\s*:\s*"', text)
    if content_match is None:
        return None
    raw_content = text[content_match.end() :]
    content_chars: list[str] = []
    escaped = False
    for index, char in enumerate(raw_content):
        if escaped:
            content_chars.append(f"\\{char}")
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            tail = raw_content[index + 1 :].lstrip()
            if not tail or tail.startswith((",", "}")):
                break
        content_chars.append(char)
    serialized_content = "".join(content_chars).strip()
    serialized_content = re.sub(r"\n\s*FADE OUT\.\s*$", "", serialized_content).strip()
    try:
        content = json.loads(f'"{serialized_content}"')
    except json.JSONDecodeError:
        content = (
            serialized_content.replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
        )
    text_key = str(content or "").upper()
    if "FADE IN" in text_key and "CENA" in text_key and any(
        marker in text_key for marker in ("INT.", "EXT.", "INT/EXT.")
    ):
        return {"content": str(content)}
    return None


SCRIPT_TECHNICAL_LABEL_RE = re.compile(
    r"(?im)^\s*(?:"
    r"número|n[uú]mero|cabeçalho|cabe[cç]alho|resumo|"
    r"objetivo(?: dram[aá]tico)?|personagens?|local|ambiente|"
    r"objetos?|a[cç][aã]o|narra[cç][aã]o|di[aá]logo|"
    r"dura[cç][aã]o|indicacao para (?:storyboard|video)|"
    r"indica[cç][aã]o para (?:storyboard|v[ií]deo)|"
    r"storyboard|video|v[ií]deo|camera|c[aâ]mera|"
    r"visual_composition|camera_movement|duration_seconds|"
    r"narration_text|dialogue_text"
    r")\s*:"
)


SCREENPLAY_SLUGLINE_RE = re.compile(r"(?im)^\s*(?:INT|EXT|INT/EXT|EXT/INT)\.\s+.+")


SCREENPLAY_HEADING_RE = re.compile(
    r"(?i)^\s*(?P<kind>INT|EXT|INT/EXT|EXT/INT)\.\s+"
    r"(?P<location>.+?)(?:\s*-\s*(?P<period>[^-\n]+))?\s*$"
)


INLINE_SCENE_HEADING_RE = re.compile(
    r"(?im)^\s*CENA\s+0*(?P<number>\d+)\s*[-:]\s*"
    r"(?P<heading>(?:INT|EXT|INT/EXT|EXT/INT)\.\s+.+?)\s*$"
)


INLINE_NUMBERED_SLUGLINE_RE = re.compile(
    r"(?i)(?<!CENA\s)\b\d{1,2}\.\s*(?:INT|EXT|INT/EXT|EXT/INT)\."
)


INLINE_NUMBERED_SLUGLINE_DETAIL_RE = re.compile(
    r"(?i)(?<!CENA\s)\b(?P<number>\d{1,2})\.\s*"
    r"(?P<heading>(?:INT|EXT|INT/EXT|EXT/INT)\.\s+[^.\n]*?\s+-\s*"
    r"(?:DIA|NOITE|MANH[ÃA]|TARDE|MADRUGADA|AMANHECER|ANOITECER|"
    r"CREP[ÚU]SCULO|FIM DE TARDE|MAIS TARDE|CONT[IÍ]NUO))\b"
)


PLACEHOLDER_SCENE_SLUGLINE_RE = re.compile(
    r"(?im)^\s*(?:INT|EXT|INT/EXT|EXT/INT)\.\s*CENA\s+\d+\s*-\s*"
    r"(?:DIA|NOITE|MANHA|MANHÃ|TARDE|MADRUGADA|AMANHECER)\s*$"
)


FADE_IN_WITH_INLINE_TEXT_RE = re.compile(r"(?im)^\s*FADE IN\s*:?[^\S\r\n]+\S")


SCREENPLAY_PARENTHETICAL_LINE_RE = re.compile(r"^\s*\([^()\n]{1,120}\)\s*$")


SCREENPLAY_INLINE_PARENTHETICAL_RE = re.compile(r"\s*\([^()\n]{1,120}\)")


SCREENPLAY_DIALOGUE_CUE_SUFFIX_RE = re.compile(r"\s+\([^()\n]{1,60}\)\s*$")


LOCATION_DIALOGUE_CUE_TERMS = {
    "AMBIENTE",
    "APARTAMENTO",
    "BAR",
    "CASA",
    "CENARIO",
    "COZINHA",
    "CORREDOR",
    "ESCOLA",
    "ESCRITORIO",
    "ESTUDIO",
    "FACHADA",
    "FAZENDA",
    "HOSPITAL",
    "IGREJA",
    "JANELA",
    "LOCAL",
    "MERCADO",
    "PRAIA",
    "PRACA",
    "QUARTO",
    "RESTAURANTE",
    "RUA",
    "SALA",
}


NON_DIALOGUE_CUE_RE = re.compile(
    r"(?i)^(?:"
    r"CENA\b|FADE\b|FADE IN\b|FADE OUT\b|CORTE PARA\b|CORTA PARA\b|"
    r"INT\.|EXT\.|INT/EXT\.|EXT/INT\.|TITULO:|T[IÍ]TULO:|FIM\b"
    r")"
)


def _looks_like_screenplay(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"(?im)^\s*FADE IN\s*:?", text)
        and SCREENPLAY_SLUGLINE_RE.search(text)
        and not SCRIPT_TECHNICAL_LABEL_RE.search(text)
    )


def _ensure_screenplay_scene_markers(content: str) -> str:
    text = str(content or "").strip()
    if not text or re.search(r"(?im)^\s*CENA\s+0*1\b", text):
        return text
    if not SCREENPLAY_SLUGLINE_RE.search(text):
        return text

    lines = text.splitlines()
    repaired: list[str] = []
    scene_number = 1
    for line in lines:
        if SCREENPLAY_SLUGLINE_RE.match(line):
            previous = next((item for item in reversed(repaired) if item.strip()), "")
            if not re.match(r"(?i)^\s*CENA\s+\d+\b", previous):
                if repaired and repaired[-1].strip():
                    repaired.append("")
                repaired.append(f"CENA {scene_number:02d}")
                scene_number += 1
        repaired.append(line)
    return "\n".join(repaired).strip()


def _normalize_inline_scene_headings(content: str) -> str:
    text = re.sub(
        r"(?im)^\s*FADE IN\s*:?[^\S\r\n]+(?=\d{1,2}\.\s*(?:INT|EXT|INT/EXT|EXT/INT)\.)",
        "FADE IN:\n\n",
        str(content or "").strip(),
    )

    def replace(match: re.Match[str]) -> str:
        scene_number = int(match.group("number"))
        heading = match.group("heading").strip()
        return f"CENA {scene_number:02d}\n{heading}"

    text = INLINE_SCENE_HEADING_RE.sub(replace, text)

    def replace_numbered_slugline(match: re.Match[str]) -> str:
        scene_number = int(match.group("number"))
        heading = match.group("heading").strip()
        return f"\n\nCENA {scene_number:02d}\n{heading}\n\n"

    text = INLINE_NUMBERED_SLUGLINE_DETAIL_RE.sub(replace_numbered_slugline, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _ascii_upper_key(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().upper()
    return re.sub(r"\s+", " ", text)


def _is_uppercase_dialogue_candidate(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 80 or NON_DIALOGUE_CUE_RE.match(text):
        return False
    if ":" in text or text.startswith("(") or text.endswith(")"):
        return False
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", text)
    return bool(letters) and text == text.upper()


def _remove_screenplay_parentheticals(content: str) -> str:
    cleaned: list[str] = []
    for raw_line in str(content or "").splitlines():
        line = raw_line.rstrip()
        if SCREENPLAY_PARENTHETICAL_LINE_RE.match(line):
            continue
        without_cue_suffix = SCREENPLAY_DIALOGUE_CUE_SUFFIX_RE.sub("", line).rstrip()
        if without_cue_suffix != line and _is_uppercase_dialogue_candidate(
            without_cue_suffix.strip()
        ):
            line = without_cue_suffix
        line = SCREENPLAY_INLINE_PARENTHETICAL_RE.sub("", line).rstrip()
        line = re.sub(r" {2,}", " ", line)
        if line.strip():
            cleaned.append(line)
        elif cleaned and cleaned[-1].strip():
            cleaned.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _next_dialogue_text_line(lines: list[str], index: int) -> str:
    skipped_parenthetical = False
    for candidate in lines[index + 1 : index + 4]:
        text = candidate.strip()
        if not text:
            continue
        if text.startswith("(") and text.endswith(")") and not skipped_parenthetical:
            skipped_parenthetical = True
            continue
        if NON_DIALOGUE_CUE_RE.match(text) or SCREENPLAY_SLUGLINE_RE.match(text):
            return ""
        if _is_uppercase_dialogue_candidate(text):
            return ""
        return text
    return ""


def _location_key_from_slugline(line: str) -> str:
    match = SCREENPLAY_HEADING_RE.match(line.strip())
    if match is None:
        return ""
    location = _clean_screenplay_location(match.group("location"), "")
    return _ascii_upper_key(location)


def _looks_like_location_dialogue_cue(cue_key: str, location_keys: set[str]) -> bool:
    if not cue_key:
        return False
    if cue_key in location_keys:
        return True
    tokens = set(cue_key.split())
    if "DE" in tokens:
        tokens.remove("DE")
    has_location_term = bool(tokens & LOCATION_DIALOGUE_CUE_TERMS)
    if has_location_term and len(cue_key.split()) <= 5:
        return True
    return False


def _location_dialogue_cue_errors(content: str) -> list[str]:
    lines = str(content or "").splitlines()
    location_keys = {
        key for line in lines if (key := _location_key_from_slugline(line.strip()))
    }
    errors: list[str] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not _is_uppercase_dialogue_candidate(line):
            continue
        if not _next_dialogue_text_line(lines, index):
            continue
        cue_key = _ascii_upper_key(line)
        if _looks_like_location_dialogue_cue(cue_key, location_keys):
            errors.append(f"cue de dialogo usa nome de local: {line[:60]}")
    return errors


def screenplay_validation_errors(content: str) -> list[str]:
    text = str(content or "").strip()
    errors: list[str] = []
    if not text:
        return ["content vazio"]
    if not re.search(r"(?im)^\s*FADE IN\s*:?", text):
        errors.append("faltou FADE IN")
    if not re.search(r"(?im)^\s*CENA\s+0*1\b", text):
        errors.append("faltou marcador CENA 01")
    if not SCREENPLAY_SLUGLINE_RE.search(text):
        errors.append("faltou slugline INT./EXT.")
    if SCRIPT_TECHNICAL_LABEL_RE.search(text):
        errors.append("conteúdo contem rotulos tecnicos")
    if re.search(r"(?i)\bCENA\s+\d+\s*[-:]\s*(?:INT|EXT|INT/EXT|EXT/INT)\.", text):
        errors.append("cenas e sluglines precisam ficar em linhas separadas")
    if FADE_IN_WITH_INLINE_TEXT_RE.search(text):
        errors.append("FADE IN precisa ficar em linha propria")
    if INLINE_NUMBERED_SLUGLINE_RE.search(text):
        errors.append("sluglines numeradas não podem ficar dentro de parágrafos")
    if PLACEHOLDER_SCENE_SLUGLINE_RE.search(text):
        errors.append("slugline generica INT. CENA precisa ser substituida por local real")
    errors.extend(_location_dialogue_cue_errors(text))
    if len(text.split()) < 12:
        errors.append("conteúdo curto demais para roteiro")
    return errors


def validate_screenplay_content(content: str, context: str) -> None:
    errors = screenplay_validation_errors(content)
    if errors:
        details = "; ".join(errors)
        raise GenerationOutputError(f"{context}: roteiro fora do formato de filme ({details})")


def _clean_screenplay_location(value: object, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(value or fallback)).strip(" .:-")
    text = re.sub(r"(?i)^(?:int|ext|int/ext|ext/int)\.\s*", "", text)
    if re.fullmatch(r"(?i)cena\s+\d+", text):
        text = fallback
    text = re.sub(
        r"\s*-\s*(?:dia|noite|manha|manh[aã]|tarde|madrugada|amanhecer).*$",
        "",
        text,
        flags=re.I,
    )
    return text.upper()[:80] or fallback.upper()


def _screenplay_heading_parts(
    value: object, *, fallback_location: str, fallback_period: str
) -> tuple[str, str, str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = SCREENPLAY_HEADING_RE.match(text)
    if match:
        kind = match.group("kind").upper()
        location = _clean_screenplay_location(match.group("location"), fallback_location)
        period = str(match.group("period") or fallback_period).strip().upper()[:30]
        return kind, location, period or fallback_period.upper()
    return (
        "INT",
        _clean_screenplay_location(text, fallback_location),
        fallback_period.upper()[:30],
    )


def _dialogue_blocks(value: object) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            blocks.append(("PERSONAGEM", text))
        return blocks
    if isinstance(value, list):
        for item in value:
            blocks.extend(_dialogue_blocks(item))
        return blocks
    if isinstance(value, dict):
        speaker = str(
            value.get("character")
            or value.get("personagem")
            or value.get("speaker")
            or value.get("name")
            or "PERSONAGEM"
        ).strip()
        line = str(
            value.get("line")
            or value.get("fala")
            or value.get("text")
            or value.get("dialogue")
            or value.get("dialogo")
            or ""
        ).strip()
        if line:
            blocks.append((speaker.upper()[:40], line))
    return blocks


def _action_text_from_mapping(value: dict, fallback: str) -> str:
    parts: list[str] = []
    for key in (
        "action",
        "acao",
        "summary",
        "resumo",
        "description",
        "descricao",
        "narration_text",
        "narration",
    ):
        text = _script_block_to_text(value.get(key))
        if text:
            parts.append(text)
    for shot in value.get("shots") or value.get("planos") or []:
        if isinstance(shot, dict):
            shot_text = _script_block_to_text(
                shot.get("action")
                or shot.get("acao")
                or shot.get("narration_text")
                or shot.get("summary")
            )
            if shot_text:
                parts.append(shot_text)
    if not parts:
        parts.append(fallback)
    text = " ".join(parts)
    text = re.sub(SCRIPT_TECHNICAL_LABEL_RE, "", text)
    return re.sub(r"\s+", " ", text).strip()[:1200] or fallback


def _screenplay_content_from_scene_items(
    raw_scenes: list,
    *,
    title: str,
    target_duration_seconds: int,
) -> str:
    _ = target_duration_seconds
    lines = [f"TITULO: {title}", "", "FADE IN:"]
    for index, raw_scene in enumerate(raw_scenes[:8], 1):
        scene = raw_scene if isinstance(raw_scene, dict) else {"action": raw_scene}
        scene_title = _first_non_empty(
            scene,
            "heading",
            "slugline",
            "location",
            "local",
            "setting",
            "title",
            fallback="AMBIENTE PRINCIPAL",
        )
        period = _first_non_empty(scene, "period", "periodo", "time", fallback="DIA")
        kind = str(scene.get("kind") or scene.get("tipo") or "").strip().upper()
        kind = kind if kind in {"INT", "EXT", "INT/EXT", "EXT/INT"} else ""
        parsed_kind, location, parsed_period = _screenplay_heading_parts(
            scene_title,
            fallback_location="AMBIENTE PRINCIPAL",
            fallback_period=str(period),
        )
        heading_kind = kind or parsed_kind
        action = _action_text_from_mapping(
            scene,
            "O personagem atravessa o espaco em silencio, revelando uma escolha emocional.",
        )

        lines.extend(
            [
                "",
                f"CENA {index:02d}",
                f"{heading_kind}. {location} - {parsed_period}",
                "",
                action,
            ]
        )
        dialogues = _dialogue_blocks(scene.get("dialogue") or scene.get("dialogo"))
        for shot in scene.get("shots") or scene.get("planos") or []:
            if isinstance(shot, dict):
                dialogues.extend(_dialogue_blocks(shot.get("dialogue") or shot.get("dialogo")))
                dialogue_text = str(shot.get("dialogue_text") or "").strip()
                if dialogue_text:
                    dialogues.append(("PERSONAGEM", dialogue_text))
        for speaker, line in dialogues[:3]:
            lines.extend(["", speaker, line])
    lines.extend(["", "FADE OUT."])
    return "\n".join(lines)


def _script_content_from_payload(
    payload: dict, *, default_title: str, target_duration_seconds: int, _depth: int = 0
) -> str:
    direct_content = (
        payload.get("content")
        or payload.get("script")
        or payload.get("roteiro")
        or payload.get("message")
        or payload.get("answer")
        or payload.get("response")
        or payload.get("output")
        or payload.get("text")
        or payload.get("texto")
    )
    if _depth < 2 and (nested_payload := _json_mapping_from_text(direct_content)):
        nested_text = _script_content_from_payload(
            nested_payload,
            default_title=str(nested_payload.get("title") or default_title),
            target_duration_seconds=target_duration_seconds,
            _depth=_depth + 1,
        )
        if nested_text:
            return nested_text
    if text := _script_block_to_text(direct_content):
        text = _normalize_inline_scene_headings(text)
        if _looks_like_screenplay(text):
            return _ensure_screenplay_scene_markers(text)

    for key in (
        "scenes",
        "cenas",
        "acts",
        "atos",
        "beats",
        "sequencias",
        "sequences",
        "structure",
        "outline",
        "roteiro_cenas",
    ):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return _screenplay_content_from_scene_items(
                value,
                title=str(payload.get("title") or payload.get("titulo") or default_title),
                target_duration_seconds=target_duration_seconds,
            )
        if value and (text := _script_block_to_text(value)):
            text = _normalize_inline_scene_headings(text)
            if _looks_like_screenplay(text):
                return _ensure_screenplay_scene_markers(text)
    if text := _script_block_to_text(direct_content):
        return _screenplay_content_from_scene_items(
            [{"action": text}],
            title=str(payload.get("title") or payload.get("titulo") or default_title),
            target_duration_seconds=target_duration_seconds,
        )
    return ""


def _production_plan_candidate(payload: dict) -> object:
    for key in (
        "production_plan",
        "scene_plan",
        "technical_plan",
        "plano_produção",
        "plano_de_produção",
        "cenas_e_planos",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalize_embedded_production_plan(
    payload: dict, *, target_duration_seconds: int, script_content: str
) -> dict | None:
    candidate = _production_plan_candidate(payload)
    if isinstance(candidate, list):
        candidate = {"scenes": candidate}
    if not isinstance(candidate, dict):
        return None
    from app.storytelling.scene_plan_normalization import normalize_scene_plan_payload_from_script

    return normalize_scene_plan_payload_from_script(
        candidate,
        target_duration_seconds,
        script_content,
    )


def _fallback_script_content_from_bible(
    story_bible_payload: dict, title: str, target_duration_seconds: int
) -> str:
    logline = str(story_bible_payload.get("logline") or "").strip()
    protagonist = "A PROTAGONISTA"
    if isinstance(story_bible_payload.get("characters"), list):
        first_character = (
            story_bible_payload["characters"][0] if story_bible_payload["characters"] else {}
        )
        if isinstance(first_character, dict):
            protagonist = str(first_character.get("name") or "A PROTAGONISTA").upper()
    location = "CASA DA FAMILIA"
    if isinstance(story_bible_payload.get("locations"), list):
        first_location = (
            story_bible_payload["locations"][0] if story_bible_payload["locations"] else {}
        )
        if isinstance(first_location, dict):
            location = _clean_screenplay_location(first_location.get("name"), location)
    prop = "objeto de revelacao"
    if isinstance(story_bible_payload.get("props"), list):
        first_prop = story_bible_payload["props"][0] if story_bible_payload["props"] else {}
        if isinstance(first_prop, dict):
            prop = str(first_prop.get("name") or prop)
    return "\n\n".join(
        [
            f"TITULO: {title}",
            "FADE IN:",
            (
                "CENA 01\n"
                f"INT. {location} - FIM DE TARDE\n\n"
                f"{protagonist} permanece diante de uma mesa coberta por marcas do passado. "
                f"O {prop} aparece onde não deveria estar. Ela toca o objeto como se a "
                "casa inteira prendesse a respiracao.\n\n"
                f"{protagonist}\n"
                "Eu achei que essa historia tinha acabado."
            ),
            (
                "CENA 02\n"
                f"INT. {location} - NOITE\n\n"
                "A luz do corredor corta a sala em duas metades. Fotografias antigas, "
                f"cartas e pequenos sinais da vida familiar cercam {protagonist}. "
                f"Ela relê cada pista ate entender que {logline or 'a verdade sempre esteve ali'}."
            ),
            (
                "CENA 03\n"
                "EXT. RUA DIANTE DA CASA - MADRUGADA\n\n"
                f"{protagonist} sai para a rua vazia com o {prop} contra o peito. "
                "O silencio deixa claro que a próxima escolha não podera ser escondida."
            ),
            (
                "CENA 04\n"
                f"INT. {location} - AMANHECER\n\n"
                "A primeira luz revela poeira suspensa no ar. "
                f"{protagonist} coloca o {prop} no centro da mesa e encara a consequencia "
                "do que descobriu.\n\n"
                f"{protagonist}\n"
                "A verdade vai doer. Mas a mentira ja doeu por tempo demais."
            ),
            (
                "CENA 05\n"
                "EXT. FRENTE DA CASA - MANHA\n\n"
                f"{protagonist} fecha a porta sem tranca-la. Pela primeira vez, ela atravessa "
                "a luz da manha sem esconder o passado.\n\n"
                "FADE OUT."
            ),
        ]
    )












def _fallback_script_content_from_idea(
    idea_payload: dict, title: str, target_duration_seconds: int
) -> str:
    premise = str(idea_payload.get("premise") or "").strip()
    hook = str(idea_payload.get("hook") or "").strip()
    protagonist = str(idea_payload.get("protagonist") or "Clara").strip() or "Clara"
    protagonist_upper = protagonist.split(",", 1)[0].strip().upper() or "CLARA"
    conflict = str(idea_payload.get("conflict") or premise or "a verdade chega tarde demais")
    payoff = str(idea_payload.get("payoff") or idea_payload.get("resolution") or "").strip()
    scene_count = expected_script_scene_count(target_duration_seconds)
    base_beats = [
        (
            "INT. CASA DA FAMILIA - FIM DE TARDE",
            f"{protagonist_upper} percebe um detalhe fora do lugar. "
            f"{hook or 'Uma pista simples muda o péso da casa inteira.'}\n\n"
            f"{protagonist_upper}\n"
            "Isso não podia estar aqui.",
        ),
        (
            "INT. CORREDOR DA CASA - NOITE",
            f"A busca transforma cada fotografia em suspeita. {conflict}. "
            "A duvida avanca mais rapido do que a coragem.",
        ),
        (
            "INT. SALA DA FAMILIA - MADRUGADA",
            f"{protagonist_upper} junta as pistas e entende que a historia escondida "
            "não era sobre culpa simples. Era sobre uma escolha que feriu todos ao redor.",
        ),
        (
            "EXT. RUA DIANTE DA CASA - AMANHECER",
            f"{protagonist_upper} atravessa a primeira luz do dia decidido a contar "
            f"a verdade. {payoff or 'A reparacao não apaga a dor, mas abre uma porta.'}",
        ),
    ]
    expanded_beats: list[str] = []
    for index in range(scene_count):
        slugline, action = base_beats[index % len(base_beats)]
        turn = (
            "O conflito ganha nova camada, com uma escolha concreta que empurra "
            "a historia para a próxima virada."
            if index >= len(base_beats)
            else ""
        )
        ending = "\n\nFADE OUT." if index == scene_count - 1 else ""
        expanded_beats.append(
            f"CENA {index + 1:02d}\n{slugline}\n\n{action}"
            + (f"\n\n{turn}" if turn else "")
            + ending
        )
    return "\n\n".join(
        [
            f"TITULO: {title}",
            "FADE IN:",
            *expanded_beats,
        ]
    )


def normalize_script_payload(
    payload: dict,
    *,
    default_title: str,
    language: str,
    target_duration_seconds: int,
) -> dict:
    normalized = dict(payload)
    normalized.setdefault("title", default_title)
    normalized.setdefault("language", language)
    normalized["target_duration_seconds"] = target_duration_seconds
    normalized["content"] = _remove_screenplay_parentheticals(
        _script_content_from_payload(
            normalized,
            default_title=default_title,
            target_duration_seconds=target_duration_seconds,
        )
    )
    validate_screenplay_content(normalized["content"], "generate_script")
    try:
        production_plan = _normalize_embedded_production_plan(
            normalized,
            target_duration_seconds=target_duration_seconds,
            script_content=normalized["content"],
        )
    except GenerationOutputError as exc:
        normalized.pop("production_plan", None)
        normalized["production_plan_error"] = str(exc)
    else:
        if production_plan is not None:
            normalized["production_plan"] = production_plan
    content_word_count = len(normalized["content"].split())
    normalized["word_count"] = max(
        _coerce_positive_int(normalized.get("word_count"), content_word_count),
        content_word_count,
    )
    return normalized
