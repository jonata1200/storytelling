# ruff: noqa: E402

import re

from app.storytelling.models import Briefing, StoryIdea
from app.video_generation.durations import validate_video_clip_duration, video_clip_durations


class GenerationOutputError(RuntimeError):
    pass


def _required_mapping(payload: object, context: str) -> dict:
    if not isinstance(payload, dict):
        raise GenerationOutputError(f"{context}: expected JSON object")
    return payload


def _required_list(payload: dict, key: str, context: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise GenerationOutputError(f"{context}: missing non-empty list '{key}'")
    return value


def _required_str(payload: dict, key: str, context: str) -> str:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing field '{key}'")
    text = str(value).strip()
    if not text:
        raise GenerationOutputError(f"{context}: empty field '{key}'")
    return text


def _bounded_required_str(payload: dict, key: str, context: str, max_length: int) -> str:
    text = _required_str(payload, key, context)
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3].rstrip()}..."


def _story_idea_db_text(payload: dict, key: str, context: str, max_length: int = 220) -> str:
    return _bounded_required_str(payload, key, context, max_length)


def _shot_narration_text(payload: dict, context: str) -> str:
    narration = str(payload.get("narration_text") or "").strip()
    if narration:
        return narration
    dialogue = str(payload.get("dialogue_text") or "").strip()
    if dialogue:
        return dialogue
    return _required_str(payload, "action", context)


def _first_non_empty(payload: dict, *keys: str, fallback: object = "") -> object:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return fallback


def _required_int(payload: dict, key: str, context: str) -> int:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing integer field '{key}'")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationOutputError(f"{context}: invalid integer field '{key}'") from exc


def _coerce_score(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(round(value))))
    text = str(value).strip().lower()
    if not text:
        return default
    labels = {
        "baixo": 25,
        "baixa": 25,
        "low": 25,
        "medio": 50,
        "médio": 50,
        "media": 50,
        "média": 50,
        "medium": 50,
        "alto": 80,
        "alta": 80,
        "high": 80,
    }
    if text in labels:
        return labels[text]
    match = re.search(r"-?\d+(?:[,.]\d+)?", text)
    if match is None:
        return default
    number = float(match.group(0).replace(",", "."))
    if "/" in text and number <= 10:
        number *= 10
    return max(0, min(100, int(round(number))))


def coerce_duration_minutes(value: object, default: float = 5.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        duration = float(str(value).replace(",", "."))
    except ValueError:
        return default
    return max(5.0, min(25.0, duration))


def _script_block_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(
            text for item in value if (text := _script_block_to_text(item))
        )
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


SCRIPT_TECHNICAL_LABEL_RE = re.compile(
    r"(?im)^\s*(?:"
    r"numero|n[uú]mero|cabecalho|cabe[cç]alho|resumo|"
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
PLACEHOLDER_SCENE_SLUGLINE_RE = re.compile(
    r"(?im)^\s*(?:INT|EXT|INT/EXT|EXT/INT)\.\s*CENA\s+\d+\s*-\s*"
    r"(?:DIA|NOITE|MANHA|MANHÃ|TARDE|MADRUGADA|AMANHECER)\s*$"
)
FADE_IN_WITH_INLINE_TEXT_RE = re.compile(r"(?im)^\s*FADE IN\s*:?[^\S\r\n]+\S")


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
    def replace(match: re.Match[str]) -> str:
        scene_number = int(match.group("number"))
        heading = match.group("heading").strip()
        return f"CENA {scene_number:02d}\n{heading}"

    return INLINE_SCENE_HEADING_RE.sub(replace, str(content or "").strip())


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
        errors.append("conteudo contem rotulos tecnicos")
    if re.search(r"(?i)\bCENA\s+\d+\s*[-:]\s*(?:INT|EXT|INT/EXT|EXT/INT)\.", text):
        errors.append("cenas e sluglines precisam ficar em linhas separadas")
    if FADE_IN_WITH_INLINE_TEXT_RE.search(text):
        errors.append("FADE IN precisa ficar em linha propria")
    if INLINE_NUMBERED_SLUGLINE_RE.search(text):
        errors.append("sluglines numeradas nao podem ficar dentro de paragrafos")
    if PLACEHOLDER_SCENE_SLUGLINE_RE.search(text):
        errors.append("slugline generica INT. CENA precisa ser substituida por local real")
    if len(text.split()) < 12:
        errors.append("conteudo curto demais para roteiro")
    return errors


def validate_screenplay_content(content: str, context: str) -> None:
    errors = screenplay_validation_errors(content)
    if errors:
        details = "; ".join(errors)
        raise GenerationOutputError(
            f"{context}: roteiro fora do formato de filme ({details})"
        )


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
    payload: dict, *, default_title: str, target_duration_seconds: int
) -> str:
    direct_content = (
        payload.get("content")
        or payload.get("script")
        or payload.get("roteiro")
        or payload.get("text")
        or payload.get("texto")
    )
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
        "plano_producao",
        "plano_de_producao",
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
            story_bible_payload["characters"][0]
            if story_bible_payload["characters"]
            else {}
        )
        if isinstance(first_character, dict):
            protagonist = str(first_character.get("name") or "A PROTAGONISTA").upper()
    location = "CASA DA FAMILIA"
    if isinstance(story_bible_payload.get("locations"), list):
        first_location = (
            story_bible_payload["locations"][0]
            if story_bible_payload["locations"]
            else {}
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
                f"O {prop} aparece onde nao deveria estar. Ela toca o objeto como se a "
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
                "O silencio deixa claro que a proxima escolha nao podera ser escondida."
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


def _compact_named_items(items: object, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(items, list):
        return []
    compacted: list[dict] = []
    for item in items[:8]:
        if isinstance(item, dict):
            compacted.append(
                {
                    key: item[key]
                    for key in keys
                    if key in item and item[key] not in (None, "", [], {})
                }
            )
        elif str(item).strip():
            compacted.append({"name": str(item).strip()})
    return compacted


def _story_bible_script_contract(story_bible_payload: dict) -> dict:
    return {
        "title": story_bible_payload.get("title"),
        "logline": story_bible_payload.get("logline"),
        "theme": story_bible_payload.get("theme"),
        "genre": story_bible_payload.get("genre"),
        "tone": story_bible_payload.get("tone"),
        "target_emotion": story_bible_payload.get("target_emotion"),
        "story_engine": story_bible_payload.get("story_engine"),
        "characters": _compact_named_items(
            story_bible_payload.get("characters"),
            ("id", "name", "role", "desire", "fear", "secret", "arc", "base_outfit"),
        ),
        "locations": _compact_named_items(
            story_bible_payload.get("locations"),
            ("id", "name", "description", "layout", "lighting", "props_in_scene"),
        ),
        "props": _compact_named_items(
            story_bible_payload.get("props"),
            ("id", "name", "owner", "narrative_importance", "first_appearance"),
        ),
        "narrative_rules": story_bible_payload.get("narrative_rules"),
        "continuity_rules": story_bible_payload.get("continuity_rules"),
        "forbidden_elements": story_bible_payload.get("forbidden_elements"),
        "visual_style": story_bible_payload.get("visual_style"),
        "audio_style": story_bible_payload.get("audio_style"),
    }


def _story_bible_visual_contract(story_bible_payload: dict) -> dict:
    return {
        "visual_style": story_bible_payload.get("visual_style"),
        "characters": _compact_named_items(
            story_bible_payload.get("characters"),
            (
                "id",
                "name",
                "role",
                "apparent_age",
                "gender",
                "height_cm",
                "body_type",
                "face_shape",
                "skin_tone",
                "eyes",
                "hair",
                "base_outfit",
                "palette",
            ),
        ),
        "locations": _compact_named_items(
            story_bible_payload.get("locations"),
            (
                "id",
                "name",
                "description",
                "layout",
                "materials",
                "palette",
                "lighting",
                "spatial_rules",
                "forbidden_elements",
            ),
        ),
        "props": _compact_named_items(
            story_bible_payload.get("props"),
            (
                "id",
                "name",
                "dimensions",
                "material",
                "color",
                "state",
                "owner",
                "visual_rules",
            ),
        ),
        "continuity_rules": story_bible_payload.get("continuity_rules"),
    }


def _idea_script_contract(idea: StoryIdea, briefing: Briefing) -> dict:
    payload = idea.payload or {}
    return {
        "title": idea.title,
        "logline": payload.get("premise") or idea.premise,
        "theme": payload.get("theme") or briefing.theme,
        "genre": payload.get("genre") or briefing.genre,
        "tone": payload.get("tone") or "cinematografico e emocional",
        "target_emotion": payload.get("primary_emotion") or briefing.primary_emotion,
        "audience": briefing.audience,
        "story_engine": {
            "dramatic_question": payload.get("dramatic_question")
            or payload.get("conflict")
            or "Qual escolha emocional define a historia?",
            "central_conflict": payload.get("conflict") or idea.premise,
            "emotional_promise": payload.get("payoff") or idea.hook,
            "inciting_incident": payload.get("hook") or idea.hook,
            "midpoint_turn": payload.get("twist") or payload.get("obstacles"),
            "climax": payload.get("climax"),
            "ending_image": payload.get("resolution") or payload.get("payoff"),
        },
        "characters": [
            {
                "name": idea.protagonist,
                "role": "protagonista",
                "desire": payload.get("protagonist_desire") or payload.get("stakes"),
                "fear": payload.get("fear") or payload.get("obstacles"),
                "arc": payload.get("emotional_need") or payload.get("resolution"),
            }
        ],
        "locations": payload.get("locations") or payload.get("locais") or [],
        "props": payload.get("props") or payload.get("objetos") or [],
        "narrative_rules": [
            "gancho visual imediato",
            "microviradas ao longo das cenas",
            "payoff emocional claro",
        ],
        "continuity_rules": [
            "manter continuidade de personagens, locais e objetos extraidos do roteiro"
        ],
        "forbidden_elements": briefing.constraints,
        "visual_style": briefing.visual_style,
        "audio_style": {"description": "audio discreto a servico da emocao"},
    }


def expected_script_scene_count(target_duration_seconds: int) -> int:
    target_minutes = max(1, target_duration_seconds / 60)
    return max(5, min(24, int(round(target_minutes * 0.8))))


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
            f"{hook or 'Uma pista simples muda o peso da casa inteira.'}\n\n"
            f"{protagonist_upper}\n"
            "Isso nao podia estar aqui.",
        ),
        (
            "INT. CORREDOR DA CASA - NOITE",
            f"A busca transforma cada fotografia em suspeita. {conflict}. "
            "A duvida avanca mais rapido do que a coragem.",
        ),
        (
            "INT. SALA DA FAMILIA - MADRUGADA",
            f"{protagonist_upper} junta as pistas e entende que a historia escondida "
            "nao era sobre culpa simples. Era sobre uma escolha que feriu todos ao redor.",
        ),
        (
            "EXT. RUA DIANTE DA CASA - AMANHECER",
            f"{protagonist_upper} atravessa a primeira luz do dia decidido a contar "
            f"a verdade. {payoff or 'A reparacao nao apaga a dor, mas abre uma porta.'}",
        ),
    ]
    expanded_beats: list[str] = []
    for index in range(scene_count):
        slugline, action = base_beats[index % len(base_beats)]
        turn = (
            "O conflito ganha nova camada, com uma escolha concreta que empurra "
            "a historia para a proxima virada."
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
    normalized["content"] = _script_content_from_payload(
        normalized,
        default_title=default_title,
        target_duration_seconds=target_duration_seconds,
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


def _script_scene_sections(script_content: str) -> list[dict]:
    text = str(script_content or "")
    pattern = re.compile(
        r"(?im)^\s*CENA\s+0*(?P<number>\d+)(?:\s*[-:]\s*(?P<title>.+?))?\s*$"
    )
    matches = list(pattern.finditer(text))
    sections: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        title = str(match.group("title") or "").strip()
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not title:
            title = next(
                (
                    line
                    for line in lines
                    if not re.match(r"(?i)^(duracao|dura[cç][aã]o|objetivo)\s*:", line)
                ),
                f"Cena {index + 1}",
            )
        duration_match = re.search(r"(?i)\bdura[cç][aã]o\s*:\s*(\d+)\s*s", block)
        summary_match = re.search(
            r"(?ims)^\s*(?:objetivo(?: dramatico)?|a[cç][aã]o|narracao)\s*:\s*"
            r"(.+?)(?:\n[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]+\s*:|\Z)",
            block,
        )
        summary = (
            re.sub(r"\s+", " ", summary_match.group(1)).strip()
            if summary_match
            else _script_block_to_text(lines[:3])
        )
        sections.append(
            {
                "scene_number": int(match.group("number") or index + 1),
                "title": title[:180],
                "summary": summary[:500] or title,
                "duration_seconds": int(duration_match.group(1)) if duration_match else None,
                "block": block,
            }
        )
    return sections


def _clip_groups_for_script_sections(
    clip_durations: list[int], sections: list[dict]
) -> list[list[int]]:
    parsed_durations = [
        int(section["duration_seconds"])
        for section in sections
        if section.get("duration_seconds") is not None
    ]
    if len(parsed_durations) != len(sections) or sum(parsed_durations) <= 0:
        groups: list[list[int]] = [[] for _section in sections]
        for index, duration in enumerate(clip_durations):
            scene_index = min((index * len(sections)) // len(clip_durations), len(sections) - 1)
            groups[scene_index].append(duration)
        return groups

    groups = []
    clip_index = 0
    for section_index, wanted_duration in enumerate(parsed_durations):
        remaining_sections = len(sections) - section_index - 1
        if section_index == len(sections) - 1:
            groups.append(clip_durations[clip_index:])
            break
        group: list[int] = []
        current = 0
        while clip_index < len(clip_durations) - remaining_sections:
            next_duration = clip_durations[clip_index]
            if group and current >= wanted_duration:
                break
            group.append(next_duration)
            current += next_duration
            clip_index += 1
        groups.append(group)
    return groups


def _scene_plan_from_script_sections(
    sections: list[dict], target_duration_seconds: int
) -> dict:
    clip_durations = video_clip_durations(target_duration_seconds)
    clip_groups = _clip_groups_for_script_sections(clip_durations, sections)
    scenes: list[dict] = []
    for scene_number, (section, durations) in enumerate(zip(sections, clip_groups, strict=True), 1):
        shots = [
            {
                "shot_number": shot_number,
                "duration_seconds": duration,
                "narration_text": section["summary"],
                "dialogue_text": "",
                "action": section["summary"],
                "emotion": "progressao dramatica",
                "visual_composition": (
                    "Composicao vertical 9:16 baseada nesta cena do roteiro, "
                    "com sujeito principal, local, objeto narrativo e luz consistentes."
                ),
                "camera_movement": "movimento curto e realista",
                "generation_type": "IMAGE_TO_VIDEO",
            }
            for shot_number, duration in enumerate(durations, 1)
        ]
        scenes.append(
            {
                "scene_number": scene_number,
                "title": section["title"],
                "summary": section["summary"],
                "duration_seconds": sum(durations),
                "shots": shots,
            }
        )
    return {"scenes": scenes}


def scene_plan_payload_from_script_content(
    script_content: str, target_duration_seconds: int
) -> dict | None:
    sections = _script_scene_sections(script_content)
    if not sections:
        return None
    return _scene_plan_from_script_sections(sections, target_duration_seconds)


def normalize_scene_plan_payload(payload: dict, target_duration_seconds: int) -> dict:
    return normalize_scene_plan_payload_from_script(payload, target_duration_seconds, "")


def normalize_scene_plan_payload_from_script(
    payload: dict, target_duration_seconds: int, script_content: str
) -> dict:
    content = _required_mapping(payload, "generate_scenes_and_shots")
    raw_scenes = _required_list(content, "scenes", "generate_scenes_and_shots")
    script_sections = _script_scene_sections(script_content)
    if len(script_sections) > len(raw_scenes):
        return _scene_plan_from_script_sections(script_sections, target_duration_seconds)
    clip_durations = video_clip_durations(target_duration_seconds)
    flattened: list[tuple[dict, dict]] = []

    for scene_index, raw_scene in enumerate(raw_scenes, 1):
        scene = dict(
            _required_mapping(raw_scene, f"generate_scenes_and_shots.scenes[{scene_index}]")
        )
        for shot_index, raw_shot in enumerate(
            _required_list(scene, "shots", f"generate_scenes_and_shots.scenes[{scene_index}]"),
            1,
        ):
            shot = dict(
                _required_mapping(
                    raw_shot,
                    f"generate_scenes_and_shots.scenes[{scene_index}].shots[{shot_index}]",
                )
            )
            flattened.append((scene, shot))

    if not flattened:
        raise GenerationOutputError("generate_scenes_and_shots: missing shots")

    if len(flattened) < len(clip_durations):
        last_scene, last_shot = flattened[-1]
        for _index in range(len(clip_durations) - len(flattened)):
            continuation = dict(last_shot)
            continuation["narration_text"] = (
                str(continuation.get("narration_text") or continuation.get("action") or "")
                + " Continuidade visual do momento anterior."
            ).strip()
            continuation["action"] = (
                str(continuation.get("action") or "A acao continua em nova tomada curta.")
                + " A emocao evolui sem quebrar a continuidade."
            ).strip()
            flattened.append((last_scene, continuation))
    elif len(flattened) > len(clip_durations):
        selected = flattened[: len(clip_durations)]
        extras = flattened[len(clip_durations) :]
        _last_scene, last_shot = selected[-1]
        extra_actions = [
            str(extra_shot.get("action") or "").strip()
            for _extra_scene, extra_shot in extras
            if str(extra_shot.get("action") or "").strip()
        ]
        if extra_actions:
            last_shot["action"] = (
                str(last_shot.get("action") or "").strip()
                + " "
                + " ".join(extra_actions)
            ).strip()
        flattened = selected

    groups: list[tuple[dict, list[dict]]] = []
    for (scene, shot), duration in zip(flattened, clip_durations, strict=True):
        validate_video_clip_duration(duration)
        if not groups or groups[-1][0] is not scene:
            groups.append((scene, []))
        shot["duration_seconds"] = duration
        shot["shot_number"] = len(groups[-1][1]) + 1
        shot.setdefault("narration_text", str(shot.get("action") or "Acao visual do plano."))
        shot.setdefault("dialogue_text", "")
        shot.setdefault("action", str(shot.get("narration_text") or "Acao visual do plano."))
        shot.setdefault("emotion", "tensao emocional")
        shot.setdefault(
            "visual_composition",
            "Composicao vertical 9:16 com sujeito principal, ambiente e luz definidos.",
        )
        shot.setdefault("camera_movement", "movimento suave e realista")
        shot.setdefault("generation_type", "IMAGE_TO_VIDEO")
        groups[-1][1].append(shot)

    normalized_scenes: list[dict] = []
    for scene_number, (scene, shots) in enumerate(groups, 1):
        scene = dict(scene)
        scene["scene_number"] = scene_number
        scene.setdefault("title", f"Cena {scene_number}")
        scene.setdefault("summary", _shot_narration_text(shots[0], f"scene[{scene_number}]"))
        scene["shots"] = shots
        scene["duration_seconds"] = sum(int(shot["duration_seconds"]) for shot in shots)
        normalized_scenes.append(scene)

    total = sum(
        int(shot["duration_seconds"])
        for scene in normalized_scenes
        for shot in scene["shots"]
    )
    if total != target_duration_seconds:
        raise GenerationOutputError(
            "generate_scenes_and_shots: shot durations do not match target duration"
        )
    return {"scenes": normalized_scenes}


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return max(1, default)
    try:
        number = int(float(str(value).replace(",", ".")))
    except ValueError:
        return max(1, default)
    return max(1, number)

from app.storytelling.story_bible_normalization import (  # noqa: F401
    STORY_BIBLE_DEFAULT_MARKERS,
    STORY_BIBLE_DETAIL_PREFIXES,
    _normalize_story_bible_characters,
    _normalize_story_bible_locations,
    _normalize_story_bible_props,
    _story_bible_meaningful_text,
    _story_bible_outfit,
    _story_bible_profile_items,
    _story_bible_slug,
    _story_bible_string_list,
    _story_bible_text,
    normalize_story_bible_payload,
    story_bible_quality_report,
    story_bible_validation_errors,
    validate_story_bible_payload,
)
from app.storytelling.story_idea_normalization import (  # noqa: F401
    STORY_IDEA_REQUIRED_TEXT_FIELDS,
    _idea_protagonist_identity,
    _idea_similarity_key,
    _normalize_generated_story_ideas,
    _story_idea_retry_guidance,
    normalize_story_idea_payload,
    story_idea_diversity_errors,
    story_idea_validation_errors,
)
