import hashlib
import json
import math
import re
from typing import Any
from uuid import UUID

from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import VibesPromptCompiler
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.continuous import (
    _ABSTRACT_SEGMENT_TERMS,
    _FRAGILE_SEGMENT_END_WORDS,
    CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
    CONTINUOUS_VIDEO_DEFAULT_MODEL,
    CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    CONTINUOUS_VIDEO_NEGATIVE_PROMPT,
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    continuous_video_request_fingerprint,
)
from app.video_generation.models import ContinuousVideoSegment
from app.video_generation.schemas import ContinuousVideoSegmentCreate

CONTINUOUS_VIDEO_PROMPT_VERSION = "cinematic_v3"


def _last_word(text: str) -> str:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    return words[-1] if words else ""


def _ends_with_numeric_value(text: str) -> bool:
    return bool(re.search(r"\d+(?:[,.]\d+)?\s*%?\s*(?:[.!?]|$)\s*$", text))


def _segment_action_has_fragile_ending(text: str) -> bool:
    if _ends_with_numeric_value(text):
        return False
    return _last_word(text) in _FRAGILE_SEGMENT_END_WORDS


def _prompt_is_too_generic(prompt: str) -> bool:
    words = re.findall(r"[^\W\d_]+", prompt, flags=re.UNICODE)
    if len(words) >= 4:
        return False
    quoted_parts = re.findall(r'"([^"]{8,})"', prompt)
    return not any(
        len(re.findall(r"[^\W\d_]+", part, flags=re.UNICODE)) >= 3 for part in quoted_parts
    )


def _normalize_segment_action(source_text: str) -> str:
    action = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not action:
        action = "acao visual principal do roteiro"
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


def _compact_segment_action(
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


def _segment_action_guidance(action: str) -> str:
    normalized = action.casefold()
    if any(term in normalized for term in _ABSTRACT_SEGMENT_TERMS):
        return "Mostre a emocao apenas por gestos, olhar, postura e interacao fisica."
    return "Mostre apenas a acao visivel, sem narracao, legendas ou texto na tela."


def _clip_prompt_detail(text: str, *, max_chars: int = 120) -> str:
    detail = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(detail) <= max_chars:
        return detail
    clipped = detail[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped.rstrip(",:;") or detail[:max_chars].strip()


def _visual_prompt_details(
    *,
    names: list[str] | None,
    visual_items: list[dict[str, str]],
    fallback_from_text: str,
    max_items: int = 3,
) -> list[str]:
    selected_names = [str(name or "").strip() for name in names or [] if str(name or "").strip()]
    if not selected_names:
        selected_names = _names_present(fallback_from_text, visual_items)
    selected_keys = {name.casefold() for name in selected_names}
    selected_items = [
        item
        for item in visual_items
        if str(item.get("name") or "").strip().casefold() in selected_keys
    ]
    if not selected_items and visual_items:
        selected_items = visual_items[:max_items]
    details: list[str] = []
    seen_text: set[str] = set()
    for item in selected_items[:max_items]:
        name = str(item.get("name") or "").strip()
        raw_prompt = str(item.get("prompt") or "").strip()
        # Remove o nome duplicado do inicio do prompt
        # Ex: "Estacao Espacial, Estrutura orbital..." → "Estrutura orbital..."
        prompt_text = _strip_leading_name(raw_prompt, name)
        prompt = _clip_prompt_detail(prompt_text)
        if name and prompt:
            detail = f"{name}: {prompt}"
        elif name:
            detail = name
        elif prompt:
            detail = prompt
        else:
            continue
        # Deduplicar textos identicos ou muito similares
        normalized = detail.casefold()
        if normalized in seen_text:
            continue
        seen_text.add(normalized)
        details.append(detail)
    return details


def _strip_leading_name(text: str, name: str) -> str:
    """Remove o nome do item do inicio do texto se ele comeca com o nome."""
    if not name or not text:
        return text
    normalized_text = text.strip()
    name_lower = name.casefold()
    if normalized_text.casefold().startswith(name_lower):
        remainder = normalized_text[len(name) :].lstrip(", ;:-")
        return remainder if remainder else text
    return text


def _append_prompt_detail_line(lines: list[str], label: str, details: list[str]) -> None:
    if details:
        lines.append(f"{label}: {'; '.join(details)}.")


def continuous_video_segment_validation_errors(segment: ContinuousVideoSegment) -> list[str]:
    errors: list[str] = []
    prompt = str(segment.prompt or "").strip()
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    action = str(metadata.get("action") or "").strip()
    if segment.segment_number <= 0:
        errors.append("numero de segmento invalido")
    if segment.duration_seconds <= 0:
        errors.append("duracao invalida")
    if _prompt_is_too_generic(prompt):
        errors.append("prompt generico demais")
    if not action:
        errors.append("acao principal ausente")
    elif _segment_action_has_fragile_ending(action):
        errors.append("acao principal termina em frase incompleta")
    # NOTE: The prompt-level fragile-sentence check was removed because it
    # produced false positives: Portuguese sentences frequently end with
    # prepositions/conjunctions ("de", "com", "para", "que", "sem", "em")
    # that are perfectly valid sentence-final words. The action-level check
    # above already catches genuinely truncated actions.
    if not metadata.get("continuity"):
        errors.append("continuidade ausente")
    return errors


def _profile_prompt(profile: dict) -> str:
    for key in (
        "canonical_prompt",
        "description",
        "narrative_profile",
        "visual_profile",
        "name",
    ):
        value = profile.get(key)
        if isinstance(value, dict):
            text = ", ".join(
                str(item).strip()
                for item in value.values()
                if isinstance(item, str) and item.strip()
            )
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _visual_items_summary(items: list[Any], *, label: str, limit: int = 6) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for item in items[:limit]:
        profile = getattr(item, "canonical_profile", {}) or {}
        name = str(getattr(item, "name", "") or profile.get("name") or "").strip()
        if not name:
            continue
        prompt = _profile_prompt(profile)
        summaries.append({"name": name, "label": label, "prompt": prompt})
    return summaries


def continuous_video_visual_context(
    characters: list[Any],
    locations: list[Any],
) -> dict[str, list[dict[str, str]]]:
    return {
        "characters": _visual_items_summary(characters, label="personagem"),
        "locations": _visual_items_summary(locations, label="local"),
    }


def continuous_video_visual_fingerprint(visual_context: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(visual_context, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _names_present(text: str, visual_items: list[dict[str, str]]) -> list[str]:
    normalized = text.casefold()
    found = [
        item["name"]
        for item in visual_items
        if item.get("name") and item["name"].casefold() in normalized
    ]
    return found or [item["name"] for item in visual_items[:3] if item.get("name")]


def _chunk_text_fallback(content: str, segment_count: int) -> list[dict]:
    """Retorna chunks do texto do roteiro como dicts com campos padrao."""
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

    # Se a quantidade de frases/unidades de ação for menor ou igual à meta de segmentos,
    # cada frase/unidade torna-se um segmento próprio e único, sem duplicar o último.
    if len(action_units) <= segment_count:
        return [
            {"text": unit, "camera_movement": "", "emotion": "", "visual_composition": ""}
            for unit in action_units
        ]

    # Se houver mais unidades que a meta de segmentos, particiona de forma equilibrada
    # por contagem de palavras, preservando as frases inteiras e sem repetição.
    n = len(action_units)
    cum = [0]
    for u in action_units:
        cum.append(cum[-1] + max(1, len(u.split())))
    total = cum[-1]

    split_indices = [0]
    curr_idx = 0
    for i in range(1, segment_count):
        target = (i * total) / segment_count
        min_idx = curr_idx + 1
        max_idx = n - (segment_count - i)
        best_idx = min_idx
        best_diff = abs(cum[min_idx] - target)
        for idx in range(min_idx + 1, max_idx + 1):
            diff = abs(cum[idx] - target)
            if diff < best_diff:
                best_diff = diff
                best_idx = idx
        split_indices.append(best_idx)
        curr_idx = best_idx
    split_indices.append(n)

    chunks: list[dict] = []
    for i in range(segment_count):
        start = split_indices[i]
        end = split_indices[i + 1]
        chunk_text = " ".join(action_units[start:end]).strip()
        chunks.append(
            {
                "text": chunk_text,
                "camera_movement": "",
                "emotion": "",
                "visual_composition": "",
            }
        )

    return chunks


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
            continue
        units.extend(_split_segment_sentences(action_line))
    action_text = " ".join(action_lines)
    return units or ([action_text.strip()] if action_text.strip() else [])


def _is_transition_marker(text: str) -> bool:
    normalized = text.strip().casefold().rstrip(":.")
    return normalized in {"fade in", "fade out", "corta para", "cut to"}


def _is_scene_marker(text: str) -> bool:
    return re.match(r"(?i)^cena\s+\d+\b", text.strip()) is not None


def _is_slugline(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized.startswith(("int.", "ext.", "int/ext.", "int./ext."))


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


def _ordered_shot_units(scenes: list[Scene], shots_by_scene: dict[UUID, list[Shot]]) -> list[dict]:
    units: list[dict] = []
    for scene in sorted(scenes, key=lambda item: int(item.scene_number or 0)):
        shots = sorted(
            shots_by_scene.get(scene.id, []),
            key=lambda item: int(item.shot_number or 0),
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
                    "camera_movement": str(shot.camera_movement or "").strip(),
                    "emotion": str(shot.emotion or "").strip(),
                    "visual_composition": str(shot.visual_composition or "").strip(),
                }
            )
    return units


def _segment_sources(
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
        chunks = _chunk_text_fallback(script.content, segment_count)
        return [
            {
                "text": chunk["text"],
                "scene_numbers": [],
                "shot_numbers": [],
                "camera_movement": chunk["camera_movement"],
                "emotion": chunk["emotion"],
                "visual_composition": chunk["visual_composition"],
            }
            for chunk in chunks
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
    for unit in shot_units:
        unit_duration = max(1, int(unit["duration"] or segment_duration_seconds))
        if current and current_duration + unit_duration > segment_duration_seconds:
            # Ao mesclar, usa o camera/emotion/composition do ultimo shot
            last_unit = current[-1]
            segments.append(
                {
                    "text": " ".join(str(item["text"]) for item in current),
                    "scene_numbers": [item["scene_number"] for item in current],
                    "shot_numbers": [
                        shot_number for item in current for shot_number in item["shot_numbers"]
                    ],
                    "camera_movement": str(last_unit.get("camera_movement") or "").strip(),
                    "emotion": str(last_unit.get("emotion") or "").strip(),
                    "visual_composition": str(last_unit.get("visual_composition") or "").strip(),
                }
            )
            current = []
            current_duration = 0
        current.append(unit)
        current_duration += unit_duration
    if current:
        last_unit = current[-1]
        segments.append(
            {
                "text": " ".join(str(item["text"]) for item in current),
                "scene_numbers": [item["scene_number"] for item in current],
                "shot_numbers": [
                    shot_number for item in current for shot_number in item["shot_numbers"]
                ],
                "camera_movement": str(last_unit.get("camera_movement") or "").strip(),
                "emotion": str(last_unit.get("emotion") or "").strip(),
                "visual_composition": str(last_unit.get("visual_composition") or "").strip(),
            }
        )
    return segments


def _segment_prompt(
    *,
    source_text: str,
    action: str | None = None,
    continuity: str | None = None,
    characters: list[str] | None = None,
    locations: list[str] | None = None,
    visual_context: dict[str, list[dict[str, str]]] | None = None,
    segment_number: int | None = None,
    duration_seconds: int | None = None,
    segment_type: str = "scene_start",
    shot_camera: str = "",
    shot_emotion: str = "",
    shot_visual_composition: str = "",
) -> str:
    """Gera prompt cinematografico para o seedance.

    Estrutura em 3 blocos:
    1. GERAÇÃO: o que o video deve criar (ação + câmera + atmosfera + diálogo)
    2. REFERÊNCIAS VISUAIS: personagens e locais (condicional ao tipo de segmento)
    3. RESTRIÇÕES: o que NÃO deve aparecer
    """
    action_text = _normalize_segment_action(action or _compact_segment_action(source_text))
    context = visual_context or {}

    # Personagens e locais do contexto visual
    character_details = _visual_prompt_details(
        names=characters,
        visual_items=context.get("characters", []),
        fallback_from_text=source_text,
        max_items=2,
    )
    location_details = _visual_prompt_details(
        names=locations,
        visual_items=context.get("locations", []),
        fallback_from_text=source_text,
        max_items=2,
    )

    # Continuidade
    continuity_text = str(continuity or "").strip() or (
        "mantenha o mesmo estado visual, emocional e espacial do segmento anterior"
    )

    # Diálogo
    dialogue = str((visual_context or {}).get("dialogue", "") or "").strip()
    if not dialogue:
        dialogue = _extract_dialogue_from_source(source_text)

    # --- BLOCO 1: GERAÇÃO ---
    geracao_lines: list[str] = []

    # Composição da cena (quando relevante)
    scene_parts: list[str] = []
    if character_details:
        scene_parts.append(_scene_composition(character_details))
    if location_details:
        scene_parts.append(_scene_composition(location_details))
    if scene_parts:
        geracao_lines.append(f"Cena: {'. '.join(scene_parts)}.")

    # Ação principal
    geracao_lines.append(f"Ação: {action_text}")

    # Composição visual do Shot (se disponível)
    if shot_visual_composition and len(shot_visual_composition) >= 10:
        geracao_lines.append(f"Composição: {shot_visual_composition}.")

    # Câmera: usa dados do Shot se disponíveis, senão infere
    camera = _infer_camera_movement(action_text, shot_camera)
    geracao_lines.append(f"Câmera: {camera}.")

    # Atmosfera: usa dados do Shot se disponíveis, senão infere
    atmosphere = _infer_atmosphere(action_text, continuity_text, shot_emotion)
    geracao_lines.append(f"Atmosfera: {atmosphere}.")

    # Continuidade (apenas para segmentos que não são início)
    if continuity_text and continuity_text != "comece estabelecendo o momento inicial da historia":
        geracao_lines.append(f"Continuidade: {continuity_text}.")

    # Diálogo (se houver)
    if dialogue:
        geracao_lines.append(f"Diálogo: {dialogue}")

    # --- BLOCO 2: REFERÊNCIAS VISUAIS (condicional) ---
    ref_lines: list[str] = []
    if _should_include_references(segment_type):
        ref_parts: list[str] = []
        if character_details:
            ref_parts.extend(character_details)
        if location_details:
            ref_parts.extend(location_details)
        if ref_parts:
            ref_lines.append(f"Referências visuais: {'; '.join(ref_parts)}.")

    # --- BLOCO 3: RESTRIÇÕES ---
    restricoes = (
        "Sem legendas, logos, texto na tela, morphing, distorções anatômicas, "
        "mudança de figurino ou cortes abruptos."
    )

    # Montagem final
    all_lines = geracao_lines + ref_lines + [restricoes]
    return "\n".join(all_lines)


def _scene_composition(details: list[str]) -> str:
    """Extrai nomes e contextos curtos para a composicao da cena.

    Transforma "Clara: jovem determinada, casaco vermelho" em
    "Clara present" (nome + contexto minimo para posicionar na cena).
    """
    parts: list[str] = []
    for detail in details:
        name, _, _ = detail.partition(":")
        name = name.strip()
        if not name:
            continue
        # Pega apenas a primeira frase curta como contexto posicional
        rest = detail.partition(":")[2].strip().rstrip(".")
        first_clause = rest.split(",")[0].strip() if rest else ""
        if first_clause and len(first_clause) < 60:
            parts.append(f"{name} ({first_clause})")
        else:
            parts.append(name)
    return ", ".join(parts)


def _extract_dialogue_from_source(source_text: str) -> str:
    """Extrai dialogos do texto fonte para inclusao no prompt.

    Suporta dois formatos:
    1. Formato bruto de roteiro: ARTHUR\nO resgate leva...
    2. Formato ja processado: Dialogo falado por ARTHUR: "O resgate..."
    """
    import re

    dialogues: list[str] = []
    # Detectar formato ja processado: "Dialogo falado por SPEAKER: \"text\""
    processed = re.findall(
        r'Dialogo falado por ([^:]+):\s*"([^"]+)"',
        str(source_text or ""),
    )
    if processed:
        for speaker, text in processed:
            clean = speaker.strip()
            dialogues.append(f'{clean}: "{text}"')
        return "; ".join(dialogues)
    # Formato bruto: deteccao de dialogue cues
    pending_speaker = ""
    for line in str(source_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _is_dialogue_cue(line):
            pending_speaker = line
            continue
        if pending_speaker:
            clean_speaker = re.sub(r"\s+", " ", str(pending_speaker)).strip(" .:-")
            if line.startswith('"') or line.startswith("\u201c"):
                dialogue_text = line
            else:
                dialogue_text = f'"{line}"'
            dialogues.append(f"{clean_speaker}: {dialogue_text}")
            pending_speaker = ""
    return "; ".join(dialogues) if dialogues else ""


def _infer_camera_movement(action_text: str, shot_camera: str = "") -> str:
    """Retorna camera do Shot se disponivel, senao infere pela acao."""
    shot_value = str(shot_camera or "").strip()
    if shot_value and len(shot_value) >= 5:
        return shot_value
    normalized = action_text.casefold()
    if any(w in normalized for w in ("entra", "entra em", "chega", "chega ao", "caminha")):
        return "camera acompanha o personagem com movimento fluido"
    if any(w in normalized for w in ("olha", "observa", "encara", "fitou")):
        return "plano medio com leve aproximacao"
    if any(w in normalized for w in ("corre", "sai correndo", "foge", "agarra")):
        return "camera acompanha a acao com movimento dinamico"
    if any(w in normalized for w in ("abre", "fecha", "levantou", "segura")):
        return "plano fechado nas maos com movimento sutil"
    if any(w in normalized for w in ("tenta", "consegue", "falha")):
        return "camera fixa com leve tensao"
    return "camera fluida e imersiva"


def _infer_atmosphere(action_text: str, continuity_text: str, shot_emotion: str = "") -> str:
    """Retorna atmosfera do Shot se disponivel, senao infere pela acao."""
    shot_value = str(shot_emotion or "").strip()
    if shot_value and len(shot_value) >= 5:
        return f"atmosfera de {shot_value}"
    normalized = action_text.casefold()
    if any(w in normalized for w in ("medo", "sombras", "escuridao", "tremendo")):
        return "luz dramatica com sombras acentuadas"
    if any(w in normalized for w in ("esperanca", "alivio", "sorriso", "abraça")):
        return "luz suave e calorosa"
    if any(w in normalized for w in ("raiva", "grita", "confronto")):
        return "luz intensa com contrastes fortes"
    if any(w in normalized for w in ("tristeza", "choro", "lamenta", "saudade")):
        return "luz neutra com tons frios"
    if "comece" in str(continuity_text).casefold():
        return "iluminacao natural e coerente com o cenario"
    return "iluminacao coerente com a cena anterior"


def _classify_segment_type(
    segment_index: int,
    scene_numbers: list[int],
    prev_scene_numbers: list[int] | None,
    characters: list[str],
    prev_characters: list[str] | None,
) -> str:
    """Classifica o tipo do segmento para adaptar o prompt.

    Tipos:
    - scene_start: inicio de cena nova (primeiro segmento ou cenas mudaram)
    - continuity: continuacao na mesma cena (mesmas cenas e mesma entidade)
    - transition: transicao entre cenas ou entidades
    """
    if segment_index <= 1:
        return "scene_start"
    if prev_scene_numbers is not None and scene_numbers != prev_scene_numbers:
        return "scene_start"
    if prev_characters is not None and characters != prev_characters:
        return "transition"
    return "continuity"


def _should_include_references(segment_type: str) -> bool:
    """Determina se o segmento deve incluir referencias visuais detalhadas.

    - scene_start: sempre inclui (estabelece o cenario)
    - transition: inclui (nova entidade)
    - continuity: omit (o video ja tem continuidade visual pelo frame anterior)
    """
    return segment_type != "continuity"


def build_continuous_video_segment_payloads(
    *,
    project_id: UUID,
    script: Script,
    scenes: list[Scene],
    shots_by_scene: dict[UUID, list[Shot]],
    visual_context: dict[str, list[dict[str, str]]],
    segment_duration_seconds: int = CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    provider: str = CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
    model: str = CONTINUOUS_VIDEO_DEFAULT_MODEL,
) -> list[ContinuousVideoSegmentCreate]:
    script_fingerprint = hashlib.sha256(
        f"{script.id}:{script.updated_at}:{script.content}".encode()
    ).hexdigest()
    visual_fingerprint = continuous_video_visual_fingerprint(visual_context)
    sources = _segment_sources(
        script,
        scenes,
        shots_by_scene,
        segment_duration_seconds=segment_duration_seconds,
    )
    payloads: list[ContinuousVideoSegmentCreate] = []
    previous_segment_id: UUID | None = None
    previous_segment_fingerprint = ""
    prev_scene_numbers: list[int] | None = None
    prev_characters: list[str] | None = None
    for index, source in enumerate(sources, 1):
        shot_duration = max(1, int(source.get("duration") or segment_duration_seconds))
        source_text = str(source.get("text") or "").strip()
        action = _normalize_segment_action(_compact_segment_action(source_text))
        continuity_break = bool(source.get("continuity_break"))
        continuity = (
            "comece estabelecendo o momento inicial da historia"
            if index == 1 or continuity_break
            else "continue diretamente o movimento e o estado emocional do segmento anterior"
        )
        characters = _names_present(source_text, visual_context.get("characters", []))
        locations = _names_present(source_text, visual_context.get("locations", []))
        source_shot = source.get("shot")
        if isinstance(source_shot, Shot):
            source_payload = dict(source_shot.payload or {})
            configured_characters = source_payload.get("characters")
            if not isinstance(configured_characters, list):
                configured_characters = []
            characters = list(
                dict.fromkeys(
                    [*characters, *(str(item) for item in configured_characters)]
                )
            )
            configured_location = str(source_payload.get("location") or "").strip()
            if configured_location and configured_location not in locations:
                locations.append(configured_location)
        scene_numbers = source.get("scene_numbers", [])

        # Classificar tipo do segmento
        segment_type = _classify_segment_type(
            index,
            scene_numbers,
            prev_scene_numbers,
            characters,
            prev_characters,
        )

        # Dados do Shot para o prompt
        shot_camera = str(source.get("camera_movement") or "").strip()
        shot_emotion = str(source.get("emotion") or "").strip()
        shot_visual_composition = str(source.get("visual_composition") or "").strip()

        prompt = _segment_prompt(
            source_text=source_text,
            action=action,
            continuity=continuity,
            characters=characters,
            locations=locations,
            visual_context=visual_context,
            segment_number=index,
            duration_seconds=segment_duration_seconds,
            segment_type=segment_type,
            shot_camera=shot_camera,
            shot_emotion=shot_emotion,
            shot_visual_composition=shot_visual_composition,
        )
        shot = source_shot
        scene = source.get("scene")
        shot_spec: ShotGenerationSpec | None = None
        compiler_version = CONTINUOUS_VIDEO_PROMPT_VERSION
        if isinstance(shot, Shot) and isinstance(scene, Scene):
            shot_payload = dict(shot.payload or {})
            raw_states = shot_payload.get("character_states")
            character_states = raw_states if isinstance(raw_states, dict) else {}
            shot_spec = ShotGenerationSpec(
                shot_id=shot.id,
                scene_id=scene.id,
                scene_title=scene.title,
                scene_summary=scene.summary,
                duration_seconds=float(shot_duration),
                characters=characters,
                location=locations[0] if locations else None,
                props=[str(item) for item in shot_payload.get("props", [])],
                action=shot.action,
                emotion=shot.emotion,
                camera=shot.camera_movement,
                camera_movement=shot.camera_movement,
                visual_composition=shot.visual_composition,
                lighting=str(shot_payload.get("lighting") or ""),
                character_states=character_states,
                continuity={
                    **dict(shot_payload.get("continuity") or {}),
                    "continuity_break": continuity_break,
                    "spatial_orientation": shot_payload.get("spatial_continuity") or "",
                },
                visual_references=["approved"] if characters or locations else [],
            )
            compiled = VibesPromptCompiler().compile(shot_spec)
            prompt = compiled.prompt
            compiler_version = compiled.compiler_version

        prev_scene_numbers = scene_numbers
        prev_characters = characters
        metadata = {
            "shot_id": str(source["shot_id"]) if source.get("shot_id") else None,
            "continuity_break": continuity_break,
            "action": action,
            "characters": characters,
            "locations": locations,
            "continuity": continuity,
            "negative_prompt": CONTINUOUS_VIDEO_NEGATIVE_PROMPT,
            "source_text": source_text,
            "source_scene_numbers": source.get("scene_numbers", []),
            "source_shot_numbers": source.get("shot_numbers", []),
            "visual_context": visual_context,
            "script_fingerprint": script_fingerprint,
            "visual_fingerprint": visual_fingerprint,
            "previous_segment_fingerprint": previous_segment_fingerprint,
            "custom_prompt": False,
            "prompt_version": CONTINUOUS_VIDEO_PROMPT_VERSION,
            "prompt_compiler_version": compiler_version,
            "shot_generation_spec": (
                shot_spec.model_dump(mode="json") if shot_spec is not None else None
            ),
        }
        fingerprint = continuous_video_request_fingerprint(
            project_id=project_id,
            segment_number=index,
            prompt=prompt,
            duration_seconds=shot_duration,
            provider=provider,
            model=model,
            script_fingerprint=script_fingerprint,
            visual_fingerprint=visual_fingerprint,
            source_segment_id=previous_segment_id,
            metadata=metadata,
        )
        payloads.append(
            ContinuousVideoSegmentCreate(
                script_id=script.id,
                shot_id=source.get("shot_id"),
                segment_number=index,
                title=f"Segmento {index:02d}",
                prompt=prompt,
                duration_seconds=shot_duration,
                provider=provider,
                model=model,
                review_status=CONTINUOUS_VIDEO_REVIEW_PENDING,
                source_segment_id=previous_segment_id,
                request_fingerprint=fingerprint,
                metadata_json=metadata,
            )
        )
        previous_segment_fingerprint = fingerprint
    return payloads
