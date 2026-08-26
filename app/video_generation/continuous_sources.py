"""Source segmentation and screenplay cleanup for continuous-video planning."""

import math
import re
from uuid import UUID

from app.storytelling.models import Scene, Script, Shot


def _is_transition_marker(text: str) -> bool:
    normalized = text.strip().casefold().rstrip(":.")
    return normalized in {"fade in", "fade out", "corta para", "cut to"}


def _is_scene_marker(text: str) -> bool:
    return re.match(r"(?i)^cena\s+\d+\b", text.strip()) is not None


def _is_slugline(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized.startswith(("int.", "ext.", "int/ext.", "int./ext."))


def _is_dialogue_cue(text: str) -> bool:
    cue = re.sub(r"\s+", " ", str(text or "")).strip(" .")
    if not cue or ":" in cue or cue.startswith("(") or cue.endswith(")"):
        return False
    if len(cue) > 48 or len(cue.split()) > 4:
        return False
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", cue)
    return bool(letters) and cue == cue.upper()


def _is_dialogue_prompt_sentence(text: str) -> bool:
    return str(text or "").strip().casefold().startswith("dialogo falado")


def _dialogue_prompt_text(dialogue_text: str, *, speaker: str = "") -> str:
    dialogue = re.sub(r"\s+", " ", str(dialogue_text or "")).strip()
    if not dialogue:
        return ""
    clean_speaker = re.sub(r"\s+", " ", str(speaker or "")).strip(" .:-")
    if clean_speaker:
        return f'Dialogo falado por {clean_speaker}: "{dialogue}"'
    return f'Dialogo falado: "{dialogue}"'


def _split_segment_sentences(text: str) -> list[str]:
    raw_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    sentences: list[str] = []
    pending_dialogue = ""
    for sentence in raw_sentences:
        if pending_dialogue:
            pending_dialogue = f"{pending_dialogue} {sentence}".strip()
            if pending_dialogue.count('"') % 2 == 0:
                sentences.append(pending_dialogue)
                pending_dialogue = ""
            continue
        if _is_dialogue_prompt_sentence(sentence) and sentence.count('"') % 2 == 1:
            pending_dialogue = sentence
            continue
        sentences.append(sentence)
    if pending_dialogue:
        sentences.append(pending_dialogue)
    return sentences


def normalize_segment_action(source_text: str) -> str:
    action = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not action:
        action = "acao visual principal do roteiro"
    # v12: frases de câmera/plano não entram no prompt de vídeo (o modelo
    # decide a cobertura sozinho); remove antes de garantir a pontuação final.
    from app.generation.shot_prompt_compiler import strip_camera_directions

    action = strip_camera_directions(action) or action
    if re.search(r'[.!?]["\']?$', action):
        return action
    return f"{action}."


def _strip_scene_prompt_markers(source_text: str) -> str:
    lines: list[str] = []
    pending_speaker = ""
    for raw_line in str(source_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_transition_marker(line) or _is_scene_marker(line) or _is_slugline(line):
            pending_speaker = ""
            continue
        if _is_dialogue_cue(line):
            pending_speaker = line
            continue
        if pending_speaker:
            lines.append(_dialogue_prompt_text(line, speaker=pending_speaker))
            pending_speaker = ""
            continue
        lines.append(line)
    text = " ".join(lines) if lines else str(source_text or "")
    text = re.sub(r"(?i)\b(?:fade in|fade out|corta para|cut to):?\b", " ", text)
    text = re.sub(r"(?i)\bcena\s+\d+\b[:.]?", " ", text)
    text = re.sub(
        r"(?i)^\s*(?:int|ext|int/ext|int\./ext)\.?\s+.{3,120}?\s+[–-]\s*"
        r"(?:dia|noite|tarde|manha|manh[aã]|madrugada)\b\.?\s*",
        "",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def compact_segment_action(
    source_text: str,
    *,
    max_sentences: int = 4,
    max_chars: int = 900,
) -> str:
    action = _strip_scene_prompt_markers(source_text)
    if not action:
        return "acao visual principal do roteiro"
    sentences = _split_segment_sentences(action)
    if sentences:
        selected_sentences = sentences[:max_sentences]
        selected_keys = {sentence.casefold() for sentence in selected_sentences}
        for sentence in sentences[max_sentences:]:
            if _is_dialogue_prompt_sentence(sentence) and sentence.casefold() not in selected_keys:
                selected_sentences.append(sentence)
                selected_keys.add(sentence.casefold())
        action = " ".join(selected_sentences).strip()
    if len(action) <= max_chars:
        return action
    clipped = action[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped.rstrip(",:;") or action[:max_chars].strip()


def _script_visual_paragraphs(content: str) -> list[str]:
    raw_paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
    paragraphs: list[str] = []
    pending_headers: list[str] = []
    for paragraph in raw_paragraphs:
        if _is_transition_marker(paragraph):
            continue
        if _is_scene_marker(paragraph) or _is_slugline(paragraph):
            pending_headers.append(paragraph)
            continue
        if pending_headers:
            paragraphs.append("\n".join([*pending_headers, paragraph]))
            pending_headers = []
            continue
        paragraphs.append(paragraph)
    return paragraphs


def _script_action_units_for_chunks(paragraphs: list[str]) -> list[str]:
    action_lines: list[str] = []
    pending_speaker = ""
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            clean_line = line.strip()
            if not clean_line:
                continue
            if (
                _is_transition_marker(clean_line)
                or _is_scene_marker(clean_line)
                or _is_slugline(clean_line)
            ):
                pending_speaker = ""
                continue
            if _is_dialogue_cue(clean_line):
                pending_speaker = clean_line
                continue
            if pending_speaker:
                action_lines.append(_dialogue_prompt_text(clean_line, speaker=pending_speaker))
                pending_speaker = ""
                continue
            action_lines.append(clean_line)
    units: list[str] = []
    for action_line in action_lines:
        if _is_dialogue_prompt_sentence(action_line):
            units.append(action_line)
        else:
            units.extend(_split_segment_sentences(action_line))
    action_text = " ".join(action_lines)
    return units or ([action_text.strip()] if action_text.strip() else [])


def _chunk_text_fallback(content: str, segment_count: int) -> list[dict]:
    if segment_count <= 1:
        text = content.strip() or "acao visual principal do roteiro"
        return [{"text": text, "camera_movement": "", "emotion": "", "visual_composition": ""}]
    paragraphs = _script_visual_paragraphs(content)
    if not paragraphs:
        paragraphs = [content.strip()] if content.strip() else []
    action_units = _script_action_units_for_chunks(paragraphs)
    if not action_units:
        return [
            {
                "text": "acao visual principal do roteiro",
                "camera_movement": "",
                "emotion": "",
                "visual_composition": "",
            }
        ]
    if len(action_units) <= segment_count:
        return [
            {"text": unit, "camera_movement": "", "emotion": "", "visual_composition": ""}
            for unit in action_units
        ]
    count = len(action_units)
    cumulative = [0]
    for unit in action_units:
        cumulative.append(cumulative[-1] + max(1, len(unit.split())))
    total = cumulative[-1]
    split_indices = [0]
    current_index = 0
    for index in range(1, segment_count):
        target = (index * total) / segment_count
        minimum = current_index + 1
        maximum = count - (segment_count - index)
        best_index = min(
            range(minimum, maximum + 1), key=lambda item: abs(cumulative[item] - target)
        )
        split_indices.append(best_index)
        current_index = best_index
    split_indices.append(count)
    return [
        {
            "text": " ".join(action_units[split_indices[index] : split_indices[index + 1]]).strip(),
            "camera_movement": "",
            "emotion": "",
            "visual_composition": "",
        }
        for index in range(segment_count)
    ]


def _ordered_shot_units(scenes: list[Scene], shots_by_scene: dict[UUID, list[Shot]]) -> list[dict]:
    units: list[dict] = []
    for scene in sorted(scenes, key=lambda item: int(item.scene_number or 0)):
        shots = sorted(
            shots_by_scene.get(scene.id, []), key=lambda item: int(item.shot_number or 0)
        )
        if not shots:
            units.append(
                {
                    "scene_number": scene.scene_number,
                    "shot_numbers": [],
                    "duration": int(scene.duration_seconds or 0),
                    "text": f"{scene.title}. {scene.summary}",
                    "camera_movement": "",
                    "emotion": "",
                    "visual_composition": "",
                }
            )
            continue
        for shot in shots:
            storyboard_action = " ".join(
                part
                for part in (shot.action, _dialogue_prompt_text(shot.dialogue_text))
                if str(part or "").strip()
            )
            text = " ".join(
                part
                for part in (
                    scene.title,
                    scene.summary,
                    shot.action,
                    _dialogue_prompt_text(shot.dialogue_text),
                    shot.visual_composition,
                    shot.camera_movement,
                )
                if str(part or "").strip()
            )
            units.append(
                {
                    "shot_id": shot.id,
                    "shot": shot,
                    "scene": scene,
                    "continuity_break": bool((shot.payload or {}).get("continuity_break")),
                    "scene_number": scene.scene_number,
                    "shot_numbers": [shot.shot_number],
                    "duration": int(shot.duration_seconds or 0),
                    "text": text,
                    "storyboard_action": storyboard_action,
                    "camera_movement": str(shot.camera_movement or "").strip(),
                    "emotion": str(shot.emotion or "").strip(),
                    "visual_composition": str(shot.visual_composition or "").strip(),
                }
            )
    return units


def segment_sources(
    script: Script,
    scenes: list[Scene],
    shots_by_scene: dict[UUID, list[Shot]],
    *,
    segment_duration_seconds: int,
) -> list[dict]:
    target_duration = max(
        int(script.target_duration_seconds or 0),
        sum(int(getattr(scene, "duration_seconds", 0) or 0) for scene in scenes),
        segment_duration_seconds,
    )
    segment_count = max(1, math.ceil(target_duration / segment_duration_seconds))
    shot_units = _ordered_shot_units(scenes, shots_by_scene)
    if not shot_units:
        return [
            {
                "text": chunk["text"],
                "scene_numbers": [],
                "shot_numbers": [],
                "camera_movement": chunk["camera_movement"],
                "emotion": chunk["emotion"],
                "visual_composition": chunk["visual_composition"],
            }
            for chunk in _chunk_text_fallback(script.content, segment_count)
        ]
    shot_units_with_ids = [unit for unit in shot_units if unit.get("shot_id")]
    if shot_units_with_ids:
        return [
            {
                "shot_id": unit["shot_id"],
                "shot": unit["shot"],
                "scene": unit["scene"],
                "continuity_break": unit["continuity_break"],
                "text": unit["text"],
                "storyboard_action": unit["storyboard_action"],
                "scene_numbers": [unit["scene_number"]],
                "shot_numbers": list(unit["shot_numbers"]),
                "duration": max(1, int(unit["duration"] or segment_duration_seconds)),
                "camera_movement": unit["camera_movement"],
                "emotion": unit["emotion"],
                "visual_composition": unit["visual_composition"],
            }
            for unit in shot_units_with_ids
        ]
    segments: list[dict] = []
    current: list[dict] = []
    current_duration = 0

    def append_current(items: list[dict]) -> None:
        last_unit = items[-1]
        segments.append(
            {
                "text": " ".join(str(item["text"]) for item in items),
                "scene_numbers": [item["scene_number"] for item in items],
                "shot_numbers": [number for item in items for number in item["shot_numbers"]],
                "camera_movement": str(last_unit.get("camera_movement") or "").strip(),
                "emotion": str(last_unit.get("emotion") or "").strip(),
                "visual_composition": str(last_unit.get("visual_composition") or "").strip(),
            }
        )

    for unit in shot_units:
        unit_duration = max(1, int(unit["duration"] or segment_duration_seconds))
        if current and current_duration + unit_duration > segment_duration_seconds:
            append_current(current)
            current = []
            current_duration = 0
        current.append(unit)
        current_duration += unit_duration
    if current:
        append_current(current)
    return segments
