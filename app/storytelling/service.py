import re
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, DependencyKind, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.models import Artifact, ArtifactVersion
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.storytelling.models import (
    Briefing,
    Scene,
    Script,
    ScriptVersion,
    Shot,
    StoryBible,
    StoryIdea,
)
from app.storytelling.schemas import BriefingCreate
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    VIDEO_CLIP_TARGET_SECONDS,
    format_clip_durations,
    validate_video_clip_duration,
    video_clip_durations,
)
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import advance_project_status


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


def _looks_like_screenplay(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"(?im)^\s*FADE IN\s*:?", text)
        and SCREENPLAY_SLUGLINE_RE.search(text)
        and not SCRIPT_TECHNICAL_LABEL_RE.search(text)
    )


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
            fallback=f"Cena {index}",
        )
        period = _first_non_empty(scene, "period", "periodo", "time", fallback="DIA")
        kind = str(scene.get("kind") or scene.get("tipo") or "").strip().upper()
        kind = kind if kind in {"INT", "EXT", "INT/EXT", "EXT/INT"} else ""
        parsed_kind, location, parsed_period = _screenplay_heading_parts(
            scene_title,
            fallback_location=f"CENA {index}",
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
        if _looks_like_screenplay(text):
            return text

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
            if _looks_like_screenplay(text):
                return text
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


async def _create_artifact(
    session: AsyncSession,
    project_id: UUID,
    artifact_type: ArtifactType,
    name: str,
    payload: dict,
    status: ArtifactStatus = ArtifactStatus.READY_FOR_REVIEW,
) -> Artifact:
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        name=name,
        status=status,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            payload=payload,
            change_note="Generated by phase 3 storytelling workflow",
        )
    )
    await session.flush()
    return artifact


async def _add_dependency(
    session: AsyncSession,
    upstream_artifact_id: UUID,
    downstream_artifact_id: UUID,
    kind: DependencyKind = DependencyKind.DERIVED_FROM,
) -> None:
    session.add(
        ArtifactDependency(
            upstream_artifact_id=upstream_artifact_id,
            downstream_artifact_id=downstream_artifact_id,
            dependency_kind=kind,
        )
    )


def _briefing_payload(data: BriefingCreate) -> dict:
    return data.model_dump(mode="json")


async def create_briefing(
    session: AsyncSession, project_id: UUID, data: BriefingCreate
) -> Briefing | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None

    payload = _briefing_payload(data)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.BRIEFING,
        "Briefing",
        payload,
        ArtifactStatus.APPROVED,
    )
    briefing = Briefing(
        project_id=project_id,
        artifact_id=artifact.id,
        theme=data.theme,
        audience=data.audience,
        genre=data.genre,
        primary_emotion=data.primary_emotion,
        emotional_intensity=data.emotional_intensity,
        ending_type=data.ending_type,
        language=data.language,
        country_context=data.country_context,
        desired_duration_minutes=data.desired_duration_minutes,
        has_narrator=data.has_narrator,
        visual_style=data.visual_style,
        content_objective=data.content_objective,
        call_to_action=data.call_to_action,
        constraints=data.constraints,
    )
    advance_project_status(project, ProjectStatus.IDEA_GENERATION)
    session.add(briefing)
    await session.commit()
    await session.refresh(briefing)
    return briefing


async def get_latest_briefing(session: AsyncSession, project_id: UUID) -> Briefing | None:
    result = await session.execute(
        select(Briefing)
        .where(Briefing.project_id == project_id)
        .order_by(Briefing.created_at.desc())
    )
    return result.scalars().first()


STORY_IDEA_REQUIRED_TEXT_FIELDS = (
    "title",
    "genre",
    "primary_emotion",
    "hook",
    "premise",
    "protagonist",
    "conflict",
    "twist",
    "payoff",
    "resolution",
)


def normalize_story_idea_payload(
    payload: dict, default_duration_minutes: float = 5.0
) -> dict:
    normalized = dict(payload)
    title = _required_str(normalized, "title", "story_idea")
    normalized.setdefault("genre", "Drama")
    normalized.setdefault("primary_emotion", normalized.get("final_emotion") or "Curiosidade")
    normalized.setdefault("hook", normalized.get("premise") or title)
    normalized.setdefault("premise", normalized.get("hook") or title)
    normalized.setdefault("protagonist", "Protagonista a definir")
    if normalized.get("payoff") in (None, "", [], {}) and normalized.get("resolution") not in (
        None,
        "",
        [],
        {},
    ):
        normalized["payoff"] = normalized["resolution"]
    if normalized.get("resolution") in (None, "", [], {}) and normalized.get("payoff") not in (
        None,
        "",
        [],
        {},
    ):
        normalized["resolution"] = normalized["payoff"]
    normalized["duration_minutes"] = coerce_duration_minutes(
        normalized.get("duration_minutes"), default_duration_minutes
    )
    normalized["retention_potential"] = _coerce_score(
        normalized.get("retention_potential"), 75
    )
    normalized["cliche_risk"] = _coerce_score(normalized.get("cliche_risk"), 25)
    normalized["production_complexity"] = _coerce_score(
        normalized.get("production_complexity"), 35
    )
    normalized["title"] = title
    return normalized


def story_idea_validation_errors(payload: dict) -> list[str]:
    errors: list[str] = []
    for field in STORY_IDEA_REQUIRED_TEXT_FIELDS:
        if not str(payload.get(field) or "").strip():
            errors.append(f"campo obrigatorio vazio: {field}")

    duration = coerce_duration_minutes(payload.get("duration_minutes"))
    if not 5 <= duration <= 25:
        errors.append("duration_minutes deve ficar entre 5 e 25")

    for field in ("retention_potential", "cliche_risk", "production_complexity"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            errors.append(f"{field} deve ser inteiro entre 0 e 100")

    obstacles = payload.get("obstacles")
    if obstacles is not None and (
        not isinstance(obstacles, list)
        or not any(str(item).strip() for item in obstacles)
    ):
        errors.append("obstacles deve ser uma lista nao vazia quando informado")

    if payload.get("hook") == payload.get("premise"):
        errors.append("hook e premise precisam ter funcoes narrativas diferentes")

    return errors


def _story_idea_retry_guidance(errors: list[str]) -> str:
    return (
        "A resposta anterior nao serve para o pipeline. Corrija estes pontos e retorne "
        "novamente somente JSON, mantendo exatamente a chave ideas: "
        f"{'; '.join(errors)}. "
    )


def _normalize_generated_story_ideas(
    content: dict, default_duration_minutes: float
) -> list[dict]:
    items: list[dict] = []
    errors: list[str] = []
    raw_ideas = _required_list(content, "ideas", "generate_story_ideas")
    for index, raw_item in enumerate(raw_ideas, 1):
        context = f"generate_story_ideas.ideas[{index}]"
        try:
            item = normalize_story_idea_payload(
                _required_mapping(raw_item, context),
                default_duration_minutes=default_duration_minutes,
            )
        except GenerationOutputError as exc:
            errors.append(str(exc))
            continue
        item_errors = story_idea_validation_errors(item)
        if item_errors:
            errors.extend(f"{context}: {error}" for error in item_errors)
            continue
        items.append(item)
    if len(items) < 3:
        errors.append("generate_story_ideas: esperado pelo menos 3 ideias validas")
    if errors:
        raise GenerationOutputError("; ".join(errors))
    return items


STORY_BIBLE_DETAIL_PREFIXES = (
    "arc_",
    "arco_",
    "palette_",
    "paleta_",
    "personality_",
    "personalidade_",
)


def _story_bible_slug(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9áéíóúâêôãõç]+", "_", text)
    text = text.strip("_")
    return text or fallback


def _story_bible_text(value: object, fallback: str = "") -> str:
    if value in (None, "", [], {}):
        return fallback
    if isinstance(value, list):
        text = ", ".join(
            item_text for item in value if (item_text := _story_bible_text(item))
        )
        return text or fallback
    if isinstance(value, dict):
        parts = [
            f"{str(key).replace('_', ' ')}: {_story_bible_text(item)}"
            for key, item in value.items()
            if _story_bible_text(item)
        ]
        return "; ".join(parts) or fallback
    return str(value).strip() or fallback


def _story_bible_string_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [_story_bible_text(item) for item in value]
    elif value in (None, "", [], {}):
        items = []
    else:
        items = [_story_bible_text(value)]
    clean_items = [item for item in items if item]
    return clean_items or fallback


def _story_bible_profile_items(value: object) -> list[dict]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        items: list[dict] = []
        for raw_item in value:
            if isinstance(raw_item, str) and raw_item.lower().startswith(
                STORY_BIBLE_DETAIL_PREFIXES
            ):
                continue
            if isinstance(raw_item, dict):
                items.append(dict(raw_item))
            elif str(raw_item).strip():
                items.append({"name": str(raw_item).strip()})
        return items
    if isinstance(value, dict):
        if any(key in value for key in ("name", "nome", "title", "titulo", "role", "funcao")):
            return [dict(value)]
        return [
            (dict(raw_item) | {"name": str(key).replace("_", " ").title()})
            if isinstance(raw_item, dict)
            else {"name": str(key).replace("_", " ").title(), "description": raw_item}
            for key, raw_item in value.items()
        ]
    return [{"name": str(value).strip()}]


def _story_bible_outfit(value: object) -> dict:
    if isinstance(value, dict):
        return {
            "main_piece": _story_bible_text(
                value.get("main_piece")
                or value.get("peca_principal")
                or value.get("peça_principal"),
                "figurino principal definido pela historia",
            ),
            "color": _story_bible_text(value.get("color") or value.get("cor"), "cor marcante"),
            "fabric": _story_bible_text(
                value.get("fabric") or value.get("tecido"), "tecido realista"
            ),
            "texture": _story_bible_text(
                value.get("texture") or value.get("textura"), "textura visivel"
            ),
            "wear_marks": _story_bible_text(
                value.get("wear_marks") or value.get("desgaste"), "marcas coerentes de uso"
            ),
            "accessories": _story_bible_string_list(
                value.get("accessories") or value.get("acessorios") or value.get("acessórios"),
                [],
            ),
        }
    text = _story_bible_text(value, "figurino principal definido pela historia")
    return {
        "main_piece": text,
        "color": "cor marcante e exclusiva",
        "fabric": "tecido realista",
        "texture": "textura visivel",
        "wear_marks": "marcas coerentes de uso",
        "accessories": [],
    }


def _normalize_story_bible_characters(payload: dict, idea_payload: dict | None) -> list[dict]:
    raw_items = (
        payload.get("characters")
        or payload.get("personagens")
        or payload.get("cast")
        or payload.get("personas")
    )
    items = _story_bible_profile_items(raw_items)
    if not items:
        protagonist = _story_bible_text(
            (idea_payload or {}).get("protagonist"), "Protagonista"
        )
        items = [{"name": protagonist, "role": "protagonista"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        default_name = (
            _story_bible_text((idea_payload or {}).get("protagonist"), "")
            if index == 1
            else ""
        ) or f"Personagem {index}"
        name = _story_bible_text(
            item.get("name") or item.get("nome") or item.get("title") or item.get("titulo"),
            default_name,
        )
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"char_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "role": _story_bible_text(item.get("role") or item.get("funcao"), "personagem"),
                "apparent_age": _story_bible_text(
                    item.get("apparent_age") or item.get("idade_aparente") or item.get("idade"),
                    "idade aparente definida",
                ),
                "gender": _story_bible_text(item.get("gender") or item.get("genero"), "pessoa"),
                "origin": _story_bible_text(item.get("origin") or item.get("origem"), "brasileira"),
                "height_cm": _story_bible_text(item.get("height_cm") or item.get("altura"), "165"),
                "body_type": _story_bible_text(
                    item.get("body_type") or item.get("tipo_fisico") or item.get("corpo"),
                    "porte fisico coerente com a historia",
                ),
                "face_shape": _story_bible_text(
                    item.get("face_shape") or item.get("formato_rosto") or item.get("rosto"),
                    "rosto memoravel",
                ),
                "skin_tone": _story_bible_text(
                    item.get("skin_tone") or item.get("tom_de_pele") or item.get("pele"),
                    "tom de pele natural",
                ),
                "eyes": _story_bible_text(
                    item.get("eyes") or item.get("olhos"), "olhos expressivos"
                ),
                "hair": _story_bible_text(
                    item.get("hair") or item.get("cabelo"), "cabelo consistente com o perfil"
                ),
                "base_outfit": _story_bible_outfit(
                    item.get("base_outfit") or item.get("figurino_base") or item.get("figurino")
                ),
                "palette": _story_bible_string_list(
                    item.get("palette") or item.get("paleta"),
                    ["cor principal", "cor secundaria", "neutro de apoio"],
                ),
                "personality": _story_bible_text(
                    item.get("personality") or item.get("personalidade"),
                    "personalidade especifica",
                ),
                "desire": _story_bible_text(
                    item.get("desire") or item.get("desejo"), "desejo claro"
                ),
                "fear": _story_bible_text(item.get("fear") or item.get("medo"), "medo interno"),
                "secret": _story_bible_text(item.get("secret") or item.get("segredo"), ""),
                "arc": _story_bible_text(
                    item.get("arc") or item.get("arco"), "arco emocional claro"
                ),
            }
        )
    return normalized


def _normalize_story_bible_locations(payload: dict) -> list[dict]:
    items = _story_bible_profile_items(
        payload.get("locations")
        or payload.get("locais")
        or payload.get("lugares")
        or payload.get("cenarios")
        or payload.get("cenários")
    )
    if not items:
        items = [{"name": "Local principal", "description": "ambiente central da historia"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        name = _story_bible_text(item.get("name") or item.get("nome"), f"Local {index}")
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"loc_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "description": _story_bible_text(
                    item.get("description") or item.get("descricao") or item.get("mood"),
                    "local importante para a historia",
                ),
                "layout": _story_bible_text(
                    item.get("layout") or item.get("planta"), "layout definido"
                ),
                "materials": _story_bible_string_list(
                    item.get("materials") or item.get("materiais"),
                    ["paredes", "piso", "objetos de cena"],
                ),
                "palette": _story_bible_string_list(
                    item.get("palette") or item.get("paleta"),
                    ["neutros", "cor de destaque", "sombra suave"],
                ),
                "lighting": _story_bible_text(
                    item.get("lighting") or item.get("iluminacao") or item.get("luz"),
                    "iluminacao cinematografica coerente",
                ),
                "props_in_scene": _story_bible_string_list(item.get("props_in_scene"), []),
                "spatial_rules": _story_bible_string_list(
                    item.get("spatial_rules"), ["manter geografia consistente"]
                ),
                "forbidden_elements": _story_bible_string_list(
                    item.get("forbidden_elements"), ["pessoas", "multidoes", "silhuetas humanas"]
                ),
            }
        )
    return normalized


def _normalize_story_bible_props(payload: dict) -> list[dict]:
    items = _story_bible_profile_items(
        payload.get("props")
        or payload.get("objetos")
        or payload.get("objects")
        or payload.get("itens")
        or payload.get("items")
    )
    if not items:
        items = [{"name": "Objeto de revelacao", "narrative_importance": "payoff narrativo"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        name = _story_bible_text(item.get("name") or item.get("nome"), f"Objeto {index}")
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"prop_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "dimensions": _story_bible_text(
                    item.get("dimensions") or item.get("dimensoes") or item.get("tamanho"),
                    "escala definida",
                ),
                "material": _story_bible_text(item.get("material"), "material reconhecivel"),
                "color": _story_bible_text(item.get("color") or item.get("cor"), "cor definida"),
                "state": _story_bible_text(
                    item.get("state") or item.get("estado"), "estado definido"
                ),
                "owner": _story_bible_text(
                    item.get("owner") or item.get("dono"), "personagem ligado ao objeto"
                ),
                "narrative_importance": _story_bible_text(
                    item.get("narrative_importance") or item.get("importance"),
                    "objeto com funcao narrativa clara",
                ),
                "first_appearance": _story_bible_text(item.get("first_appearance"), "primeiro ato"),
                "visual_rules": _story_bible_string_list(
                    item.get("visual_rules"), ["aparecer isolado e reconhecivel"]
                ),
            }
        )
    return normalized


STORY_BIBLE_DEFAULT_MARKERS = {
    "",
    "desejo claro",
    "arco emocional claro",
    "figurino principal definido pela historia",
    "local importante para a historia",
    "ambiente central da historia",
    "layout definido",
    "iluminacao cinematografica coerente",
    "objeto com funcao narrativa clara",
    "Objeto de revelacao",
    "Qual escolha emocional define a historia?",
    "realismo emocional",
    "manter continuidade de figurino e objetos",
}


def _story_bible_meaningful_text(value: object) -> bool:
    text = _story_bible_text(value).strip()
    return bool(text and text not in STORY_BIBLE_DEFAULT_MARKERS)


def story_bible_quality_report(payload: dict) -> dict:
    missing_fields: list[str] = []
    risk_flags: list[str] = []
    checks: list[bool] = []

    raw_characters = payload.get("characters")
    raw_locations = payload.get("locations")
    raw_props = payload.get("props")
    raw_story_engine = payload.get("story_engine")
    raw_continuity_rules = payload.get("continuity_rules")
    characters = cast(list, raw_characters) if isinstance(raw_characters, list) else []
    locations = cast(list, raw_locations) if isinstance(raw_locations, list) else []
    props = cast(list, raw_props) if isinstance(raw_props, list) else []
    story_engine = (
        cast(dict, raw_story_engine) if isinstance(raw_story_engine, dict) else {}
    )
    continuity_rules = (
        cast(list, raw_continuity_rules) if isinstance(raw_continuity_rules, list) else []
    )

    character_ready = bool(characters) and any(
        isinstance(character, dict)
        and _story_bible_meaningful_text(character.get("name"))
        and _story_bible_meaningful_text(character.get("role"))
        and _story_bible_meaningful_text(character.get("desire"))
        and _story_bible_meaningful_text(character.get("arc"))
        and isinstance(character.get("base_outfit"), dict)
        and _story_bible_meaningful_text(character["base_outfit"].get("main_piece"))
        for character in characters
    )
    checks.append(character_ready)
    if not character_ready:
        missing_fields.append("characters[].name/role/desire/arc/base_outfit")

    location_ready = bool(locations) and any(
        isinstance(location, dict)
        and _story_bible_meaningful_text(location.get("name"))
        and _story_bible_meaningful_text(location.get("description"))
        and _story_bible_meaningful_text(location.get("lighting"))
        for location in locations
    )
    checks.append(location_ready)
    if not location_ready:
        missing_fields.append("locations[].name/description/lighting")

    prop_ready = bool(props) and any(
        isinstance(prop, dict)
        and _story_bible_meaningful_text(prop.get("name"))
        and _story_bible_meaningful_text(prop.get("narrative_importance"))
        for prop in props
    )
    checks.append(prop_ready)
    if not prop_ready:
        missing_fields.append("props[].name/narrative_importance")

    required_engine_keys = ("inciting_incident", "midpoint_turn", "climax", "ending_image")
    missing_engine = [
        key
        for key in required_engine_keys
        if not _story_bible_meaningful_text(story_engine.get(key))
    ]
    engine_ready = not missing_engine
    checks.append(engine_ready)
    if not engine_ready:
        missing_fields.extend(f"story_engine.{key}" for key in missing_engine)

    continuity_ready = bool(continuity_rules) and any(
        _story_bible_meaningful_text(rule) for rule in continuity_rules
    )
    checks.append(continuity_ready)
    if not continuity_ready:
        missing_fields.append("continuity_rules")

    visual_contract_ready = bool(payload.get("visual_contract"))
    checks.append(visual_contract_ready)
    if not visual_contract_ready:
        risk_flags.append("visual_contract ausente")

    script_contract_ready = bool(payload.get("script_contract"))
    checks.append(script_contract_ready)
    if not script_contract_ready:
        risk_flags.append("script_contract ausente")

    score = int(round((sum(1 for check in checks if check) / len(checks)) * 100))
    if score < 80:
        risk_flags.append("Story Bible incompleta para roteiro e producao visual")
    return {
        "completeness_score": score,
        "missing_fields": missing_fields,
        "risk_flags": risk_flags,
    }


def story_bible_validation_errors(payload: dict) -> list[str]:
    report = story_bible_quality_report(payload)
    errors = list(report["missing_fields"])
    if int(report["completeness_score"]) < 80:
        errors.append(f"completeness_score abaixo de 80 ({report['completeness_score']})")
    return errors


def validate_story_bible_payload(payload: dict, context: str) -> None:
    errors = story_bible_validation_errors(payload)
    if errors:
        raise GenerationOutputError(
            f"{context}: Story Bible incompleta ({'; '.join(errors)})"
        )


def normalize_story_bible_payload(
    payload: dict,
    idea_payload: dict | None = None,
    briefing: Briefing | None = None,
) -> dict:
    title = _required_str(payload, "title", "generate_story_bible")
    logline = _required_str(payload, "logline", "generate_story_bible")
    raw_export_profile = payload.get("export_profile")
    export_profile_payload = raw_export_profile if isinstance(raw_export_profile, dict) else {}
    raw_story_engine = payload.get("story_engine")
    story_engine_payload = raw_story_engine if isinstance(raw_story_engine, dict) else {}
    normalized = {
        "title": title,
        "logline": logline,
        "theme": _story_bible_text(payload.get("theme"), getattr(briefing, "theme", "")),
        "genre": _story_bible_text(payload.get("genre"), getattr(briefing, "genre", "")),
        "tone": _story_bible_text(payload.get("tone"), "cinematografico e emocional"),
        "target_emotion": _story_bible_text(
            payload.get("target_emotion"), getattr(briefing, "primary_emotion", "")
        ),
        "audience": _story_bible_text(payload.get("audience"), getattr(briefing, "audience", "")),
        "story_engine": {
            "dramatic_question": _story_bible_text(
                story_engine_payload.get("dramatic_question") or payload.get("dramatic_question"),
                "Qual escolha emocional define a historia?",
            ),
            "central_conflict": _story_bible_text(
                story_engine_payload.get("central_conflict") or payload.get("central_conflict"),
                logline,
            ),
            "emotional_promise": _story_bible_text(
                story_engine_payload.get("emotional_promise") or payload.get("emotional_promise"),
                logline,
            ),
            "inciting_incident": _story_bible_text(
                story_engine_payload.get("inciting_incident") or payload.get("inciting_incident"),
                "",
            ),
            "midpoint_turn": _story_bible_text(
                story_engine_payload.get("midpoint_turn") or payload.get("midpoint_turn"),
                "",
            ),
            "climax": _story_bible_text(
                story_engine_payload.get("climax") or payload.get("climax"),
                "",
            ),
            "ending_image": _story_bible_text(
                story_engine_payload.get("ending_image") or payload.get("ending_image"),
                "",
            ),
        },
        "world_rules": _story_bible_string_list(payload.get("world_rules"), ["realismo emocional"]),
        "visual_style": payload.get("visual_style")
        if isinstance(payload.get("visual_style"), dict)
        else {"description": _story_bible_text(payload.get("visual_style"), "cinematico realista")},
        "narrative_rules": _story_bible_string_list(
            payload.get("narrative_rules"), ["gancho claro", "payoff emocional"]
        ),
        "forbidden_elements": _story_bible_string_list(
            payload.get("forbidden_elements"), ["exposicao longa", "reviravolta aleatoria"]
        ),
        "characters": _normalize_story_bible_characters(payload, idea_payload),
        "locations": _normalize_story_bible_locations(payload),
        "props": _normalize_story_bible_props(payload),
        "timeline": _story_bible_profile_items(payload.get("timeline")),
        "relationships": _story_bible_profile_items(payload.get("relationships")),
        "continuity_rules": _story_bible_string_list(
            payload.get("continuity_rules"), ["manter continuidade de figurino e objetos"]
        ),
        "audio_style": payload.get("audio_style")
        if isinstance(payload.get("audio_style"), dict)
        else {"description": _story_bible_text(payload.get("audio_style"), "audio discreto")},
        "export_profile": export_profile_payload,
    }
    normalized["export_profile"] = {
        "aspect_ratio": str(export_profile_payload.get("aspect_ratio") or "9:16"),
        "resolution": str(export_profile_payload.get("resolution") or "1080x1920"),
        "language": str(export_profile_payload.get("language") or "pt-BR"),
    }
    normalized["script_contract"] = _story_bible_script_contract(normalized)
    normalized["visual_contract"] = _story_bible_visual_contract(normalized)
    normalized["quality_report"] = story_bible_quality_report(normalized)
    return normalized


async def create_story_idea_from_payload(
    session: AsyncSession, project_id: UUID, payload: dict
) -> StoryIdea | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    item = normalize_story_idea_payload(payload)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.STORY_IDEA,
        _required_str(item, "title", "story_idea"),
        item,
    )
    await _add_dependency(session, briefing.artifact_id, artifact.id)
    idea = StoryIdea(
        project_id=project_id,
        artifact_id=artifact.id,
        title=_required_str(item, "title", "story_idea"),
        hook=_required_str(item, "hook", "story_idea"),
        premise=_required_str(item, "premise", "story_idea"),
        protagonist=_required_str(item, "protagonist", "story_idea"),
        retention_potential=_required_int(item, "retention_potential", "story_idea"),
        cliche_risk=_required_int(item, "cliche_risk", "story_idea"),
        production_complexity=_required_int(item, "production_complexity", "story_idea"),
        payload=item,
    )
    session.add(idea)
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    await session.refresh(idea)
    return idea


async def generate_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea] | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    variables = {
        "theme": briefing.theme,
        "audience": briefing.audience,
        "primary_emotion": briefing.primary_emotion,
        "genre": briefing.genre,
        "target_duration_minutes": float(briefing.desired_duration_minutes),
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_ideas")
    normalized_items: list[dict] | None = None
    last_error: GenerationOutputError | None = None
    for attempt in range(2):
        result, execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_story_ideas",
            variables,
            model=model,
            fallback_on_runtime_error=True,
        )
        try:
            content = _required_mapping(result.content, "generate_story_ideas")
            normalized_items = _normalize_generated_story_ideas(
                content, float(briefing.desired_duration_minutes)
            )
            execution.response = result.content
            break
        except GenerationOutputError as exc:
            last_error = exc
            if attempt == 0:
                variables["retry_guidance"] = _story_idea_retry_guidance([str(exc)])
                continue
            raise
    if normalized_items is None:
        if last_error is not None:
            raise last_error
        raise GenerationOutputError("generate_story_ideas: resposta vazia")

    ideas: list[StoryIdea] = []
    for index, item in enumerate(normalized_items, 1):
        artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.STORY_IDEA,
            _required_str(item, "title", f"generate_story_ideas.ideas[{index}]"),
            item,
        )
        await _add_dependency(session, briefing.artifact_id, artifact.id)
        idea = StoryIdea(
            project_id=project_id,
            artifact_id=artifact.id,
            title=_required_str(item, "title", f"generate_story_ideas.ideas[{index}]"),
            hook=_required_str(item, "hook", f"generate_story_ideas.ideas[{index}]"),
            premise=_required_str(item, "premise", f"generate_story_ideas.ideas[{index}]"),
            protagonist=_required_str(
                item, "protagonist", f"generate_story_ideas.ideas[{index}]"
            ),
            retention_potential=_required_int(
                item, "retention_potential", f"generate_story_ideas.ideas[{index}]"
            ),
            cliche_risk=_required_int(item, "cliche_risk", f"generate_story_ideas.ideas[{index}]"),
            production_complexity=_required_int(
                item, "production_complexity", f"generate_story_ideas.ideas[{index}]"
            ),
            payload=item,
        )
        session.add(idea)
        ideas.append(idea)
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    for idea in ideas:
        await session.refresh(idea)
    return ideas


async def list_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return []
    result = await session.execute(
        select(StoryIdea).where(StoryIdea.project_id == project_id).order_by(StoryIdea.created_at)
    )
    return list(result.scalars())


async def generate_story_bible(
    session: AsyncSession, project_id: UUID, story_idea_id: UUID
) -> StoryBible | None:
    project = await ProjectRepository(session).get_project(project_id)
    idea = await session.get(StoryIdea, story_idea_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or idea is None or idea.project_id != project_id or briefing is None:
        return None

    variables = _briefing_payload(
        BriefingCreate.model_validate(briefing, from_attributes=True)
    ) | {"idea": idea.payload, "idea_title": idea.title, "retry_guidance": ""}
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_bible")
    payload: dict | None = None
    for attempt in range(2):
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_story_bible",
            variables,
            model=model,
            fallback_on_runtime_error=True,
        )
        try:
            payload = normalize_story_bible_payload(
                _required_mapping(result.content, "generate_story_bible"),
                idea.payload,
                briefing,
            )
            validate_story_bible_payload(payload, "generate_story_bible")
            break
        except GenerationOutputError as exc:
            payload = None
            if attempt == 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque a Story Bible ficou incompleta: "
                f"{exc}. Recrie preenchendo campos narrativos, visuais e contratos "
                "sem usar valores genericos."
            )
    if payload is None:
        return None
    title = _required_str(payload, "title", "generate_story_bible")
    artifact = await _create_artifact(
        session, project_id, ArtifactType.STORY_BIBLE, title, payload
    )
    await _add_dependency(session, idea.artifact_id, artifact.id)
    story_bible = StoryBible(
        project_id=project_id,
        artifact_id=artifact.id,
        story_idea_id=idea.id,
        title=title,
        logline=_required_str(payload, "logline", "generate_story_bible"),
        payload=payload,
    )
    session.add(story_bible)
    advance_project_status(project, ProjectStatus.STORY_APPROVAL)
    await session.commit()
    await session.refresh(story_bible)
    return story_bible


async def generate_script(
    session: AsyncSession, project_id: UUID, story_bible_id: UUID
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    story_bible = await session.get(StoryBible, story_bible_id)
    briefing = await get_latest_briefing(session, project_id)
    if (
        project is None
        or story_bible is None
        or story_bible.project_id != project_id
        or briefing is None
    ):
        return None

    target_duration_seconds = int(briefing.desired_duration_minutes * Decimal("60"))
    clip_durations = video_clip_durations(target_duration_seconds)
    story_bible_contract = story_bible.payload.get("script_contract")
    if not isinstance(story_bible_contract, dict):
        story_bible_contract = _story_bible_script_contract(story_bible.payload)
    variables = {
        "story_bible_contract": story_bible_contract,
        "language": briefing.language,
        "target_duration_seconds": target_duration_seconds,
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "expected_clip_count": len(clip_durations),
        "clip_durations": format_clip_durations(clip_durations),
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    payload: dict | None = None
    for attempt in range(2):
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_script",
            variables,
            model=model,
            fallback_on_runtime_error=True,
        )
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "generate_script"),
                default_title=story_bible.title,
                language=briefing.language,
                target_duration_seconds=target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            if attempt == 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque nao seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo content como roteiro de filme limpo e "
                "production_plan separado."
            )
    if payload is None:
        payload = {
            "title": story_bible.title,
            "language": briefing.language,
            "target_duration_seconds": target_duration_seconds,
            "content": _fallback_script_content_from_bible(
                story_bible.payload,
                story_bible.title,
                target_duration_seconds,
            ),
        }
        payload["word_count"] = len(payload["content"].split())
    title = _required_str(payload, "title", "generate_script")
    if not str(payload.get("content") or "").strip():
        payload["content"] = _fallback_script_content_from_bible(
            story_bible.payload,
            title,
            target_duration_seconds,
        )
        payload["word_count"] = len(payload["content"].split())
    artifact = await _create_artifact(
        session, project_id, ArtifactType.SCRIPT, title, payload
    )
    await _add_dependency(session, story_bible.artifact_id, artifact.id)
    script = Script(
        project_id=project_id,
        artifact_id=artifact.id,
        story_bible_id=story_bible.id,
        title=title,
        language=_required_str(payload, "language", "generate_script"),
        target_duration_seconds=_required_int(
            payload, "target_duration_seconds", "generate_script"
        ),
        word_count=_required_int(payload, "word_count", "generate_script"),
        content=_required_str(payload, "content", "generate_script"),
    )
    session.add(script)
    await session.flush()
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=1,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    advance_project_status(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def revise_script(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    instruction: str,
    project_context: dict | None = None,
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or script is None or script.project_id != project_id or briefing is None:
        return None
    artifact = await session.get(Artifact, script.artifact_id)
    if artifact is None:
        return None

    variables = {
        "title": script.title,
        "language": script.language,
        "target_duration_seconds": script.target_duration_seconds,
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "current_script": script.content,
        "instruction": instruction,
        "project_context": project_context or {},
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "revise_script")
    payload: dict | None = None
    execution = None
    for attempt in range(2):
        result, execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "revise_script",
            variables,
            artifact_id=script.artifact_id,
            model=model,
            fallback_on_runtime_error=True,
        )
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "revise_script"),
                default_title=script.title,
                language=script.language,
                target_duration_seconds=script.target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            if attempt == 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque nao seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo apenas roteiro de filme em content."
            )
    if payload is None or execution is None:
        return None
    title = _required_str(payload, "title", "revise_script")
    content = _required_str(payload, "content", "revise_script")
    script.title = title
    script.language = _required_str(payload, "language", "revise_script")
    script.target_duration_seconds = _required_int(
        payload, "target_duration_seconds", "revise_script"
    )
    script.word_count = _required_int(payload, "word_count", "revise_script")
    script.content = content
    await create_artifact_version(
        session,
        artifact,
        payload,
        change_note=f"Revisao por chat: {instruction[:160]}",
    )
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=artifact.current_version,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    execution.response = result.content
    advance_project_status(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def _script_embedded_production_plan(
    session: AsyncSession, script: Script
) -> dict | None:
    result = await session.execute(
        select(ScriptVersion)
        .where(ScriptVersion.script_id == script.id)
        .order_by(ScriptVersion.version_number.desc())
    )
    version = result.scalars().first()
    if version is None:
        return None
    payload = version.payload if isinstance(version.payload, dict) else {}
    production_plan = payload.get("production_plan")
    return production_plan if isinstance(production_plan, dict) else None


async def generate_scenes_and_shots(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> list[Scene] | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None

    clip_durations = video_clip_durations(script.target_duration_seconds)
    embedded_plan = await _script_embedded_production_plan(session, script)

    scenes: list[Scene] = []
    if embedded_plan is not None:
        try:
            content = normalize_scene_plan_payload_from_script(
                embedded_plan,
                script.target_duration_seconds,
                script.content,
            )
        except GenerationOutputError:
            embedded_plan = None
    if embedded_plan is None:
        provider, model = await llm_provider_for_task(
            session, project_id, "generate_scenes_and_shots"
        )
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_scenes_and_shots",
            {
                "script": script.content,
                "target_duration_seconds": script.target_duration_seconds,
                "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
                "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
                "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
                "expected_clip_count": len(clip_durations),
                "clip_durations": format_clip_durations(clip_durations),
            },
            model=model,
            fallback_on_runtime_error=True,
        )
        content = normalize_scene_plan_payload_from_script(
            _required_mapping(result.content, "generate_scenes_and_shots"),
            script.target_duration_seconds,
            script.content,
        )
    for scene_index, raw_scene_payload in enumerate(
        _required_list(content, "scenes", "generate_scenes_and_shots"), 1
    ):
        scene_payload = _required_mapping(
            raw_scene_payload, f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_title = _required_str(
            scene_payload, "title", f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.SCENE,
            scene_title,
            scene_payload,
        )
        await _add_dependency(session, script.artifact_id, scene_artifact.id)
        scene = Scene(
            project_id=project_id,
            artifact_id=scene_artifact.id,
            script_id=script.id,
            scene_number=_required_int(
                scene_payload, "scene_number", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            title=scene_title,
            summary=_required_str(
                scene_payload, "summary", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            duration_seconds=_required_int(
                scene_payload,
                "duration_seconds",
                f"generate_scenes_and_shots.scenes[{scene_index}]",
            ),
            payload=scene_payload,
        )
        session.add(scene)
        await session.flush()
        for shot_index, raw_shot_payload in enumerate(
            _required_list(
                scene_payload, "shots", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            1,
        ):
            shot_context = (
                f"generate_scenes_and_shots.scenes[{scene_index}].shots[{shot_index}]"
            )
            shot_payload = _required_mapping(raw_shot_payload, shot_context)
            shot_artifact = await _create_artifact(
                session,
                project_id,
                ArtifactType.SHOT,
                f"{scene.title} - Plano {_required_int(shot_payload, 'shot_number', shot_context)}",
                shot_payload,
            )
            await _add_dependency(session, scene_artifact.id, shot_artifact.id)
            session.add(
                Shot(
                    project_id=project_id,
                    artifact_id=shot_artifact.id,
                    scene_id=scene.id,
                    shot_number=_required_int(shot_payload, "shot_number", shot_context),
                    duration_seconds=_required_int(shot_payload, "duration_seconds", shot_context),
                    narration_text=_shot_narration_text(shot_payload, shot_context),
                    dialogue_text=str(shot_payload.get("dialogue_text") or ""),
                    action=_required_str(shot_payload, "action", shot_context),
                    emotion=_bounded_required_str(shot_payload, "emotion", shot_context, 120),
                    visual_composition=_required_str(
                        shot_payload, "visual_composition", shot_context
                    ),
                    camera_movement=_bounded_required_str(
                        shot_payload, "camera_movement", shot_context, 120
                    ),
                    generation_type=_bounded_required_str(
                        shot_payload, "generation_type", shot_context, 80
                    ),
                    payload=shot_payload,
                )
            )
        scenes.append(scene)
    advance_project_status(project, ProjectStatus.VISUAL_BIBLE_GENERATION)
    await session.commit()
    for scene in scenes:
        await session.refresh(scene)
    return scenes
