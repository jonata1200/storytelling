import hashlib
import json
import re
from typing import Any
from uuid import UUID

from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import VibesPromptCompiler
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.continuous import (
    _ABSTRACT_SEGMENT_TERMS,
    _FRAGILE_SEGMENT_END_WORDS,
    _MOTION_VERBS_BEFORE_PARA,
    CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
    CONTINUOUS_VIDEO_DEFAULT_MODEL,
    CONTINUOUS_VIDEO_DEFAULT_SEGMENT_SECONDS,
    CONTINUOUS_VIDEO_NEGATIVE_PROMPT,
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    continuous_video_request_fingerprint,
)
from app.video_generation.continuous_sources import _is_dialogue_cue
from app.video_generation.continuous_sources import (
    compact_segment_action as _compact_segment_action,
)
from app.video_generation.continuous_sources import (
    normalize_segment_action as _normalize_segment_action,
)
from app.video_generation.continuous_sources import (
    segment_sources as _segment_sources,
)
from app.video_generation.models import ContinuousVideoSegment
from app.video_generation.schemas import ContinuousVideoSegmentCreate

CONTINUOUS_VIDEO_PROMPT_VERSION = "human_v14_action_only"


def _last_word(text: str) -> str:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    return words[-1] if words else ""


def _ends_with_numeric_value(text: str) -> bool:
    return bool(re.search(r"\d+(?:[,.]\d+)?\s*%?\s*(?:[.!?]|$)\s*$", text))


def _segment_action_has_fragile_ending(text: str) -> bool:
    if _ends_with_numeric_value(text):
        return False
    words = re.findall(r"[^\W\d_]+", text.casefold())
    if not words:
        return False
    last = words[-1]
    if last != "para":
        return last in _FRAGILE_SEGMENT_END_WORDS
    # "para" é ambíguo: verbo "parar" fecha a frase ("...a música para."),
    # preposição só aparece APÓS verbo de movimento ("...corre para" = truncado).
    preceded_by_motion_verb = len(words) >= 2 and words[-2] in _MOTION_VERBS_BEFORE_PARA
    return preceded_by_motion_verb


def _starts_with_lowercase_word(text: str) -> bool:
    first_letter = next((char for char in str(text or "") if char.isalpha()), "")
    return bool(first_letter and first_letter.islower())


def _legacy_shot_action_context(
    shot: Shot,
    scene_shots: list[Shot],
) -> tuple[str, str, str]:
    """Recover complete sentences and scene state from legacy fragmented Shots."""
    ordered = sorted(scene_shots, key=lambda item: (item.shot_number, str(item.id)))
    actions = [str(item.action or "").strip() for item in ordered]
    try:
        shot_index = next(index for index, item in enumerate(ordered) if item.id == shot.id)
    except StopIteration:
        shot_index = 0

    start = shot_index
    while start > 0 and (
        _starts_with_lowercase_word(actions[start])
        or _segment_action_has_fragile_ending(actions[start - 1])
    ):
        start -= 1
    end = shot_index
    candidate = " ".join(actions[start : end + 1]).strip()
    while end + 1 < len(actions) and _segment_action_has_fragile_ending(candidate):
        end += 1
        candidate = " ".join(actions[start : end + 1]).strip()

    complete_action = _normalize_segment_action(_compact_segment_action(candidate or shot.action))
    scene_context = " ".join(
        part
        for part in [str(getattr(shot, "narration_text", "") or "").strip(), *actions]
        if part
    ).strip()
    previous_action = (
        actions[shot_index - 1]
        if shot_index > 0
        else f"Estado inicial estabelecido pela cena: {scene_context}"
    )
    return complete_action, scene_context, previous_action


def _derived_character_states(
    characters: list[str], scene_context: str
) -> dict[str, dict[str, str]]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", scene_context)
        if sentence.strip()
    ]
    states: dict[str, dict[str, str]] = {}
    for character in characters:
        relevant = [
            sentence for sentence in sentences if character.casefold() in sentence.casefold()
        ]
        notes = " ".join(relevant) or (
            f"Preserve a aparência, a postura e a posição de {character} conforme o frame inicial."
        )
        states[character] = {
            "continuity_notes": notes[:700],
            "condition": (relevant[-1] if relevant else notes)[:300],
        }
    return states


def _prompt_is_too_generic(prompt: str) -> bool:
    words = re.findall(r"[^\W\d_]+", prompt, flags=re.UNICODE)
    if len(words) >= 4:
        return False
    quoted_parts = re.findall(r'"([^"]{8,})"', prompt)
    return not any(
        len(re.findall(r"[^\W\d_]+", part, flags=re.UNICODE)) >= 3 for part in quoted_parts
    )


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
    if segment.duration_seconds != 8:
        errors.append("todo segmento deve ter exatamente 8 segundos")
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
    shot_spec = metadata.get("shot_generation_spec")
    if isinstance(shot_spec, dict):
        if not str(shot_spec.get("scene_context") or "").strip():
            errors.append("contexto narrativo da cena ausente")
        if shot_spec.get("characters") and not shot_spec.get("character_states"):
            errors.append("estado de continuidade dos personagens ausente")
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
    return found


# Períodos que o LLM coloca no fim do location/title ("Rua do Bairro - Amanhecer").
_LOCATION_PERIOD_TAIL_RE = re.compile(
    r"\s*[-\u2013]\s*(?:DIA|NOITE|TARDE|MANH[ÃA]|MADRUGADA|AMANHECER|ENTARDECER|"
    r"MEIO[- ]?DIA|ANOITECER|FIM DE TARDE|IN[IÍ]CIO DA NOITE|ALTA NOITE|"
    r"CREP[UÚ]SCULO|CONT[IÍ]NUO)\s*$",
    flags=re.IGNORECASE,
)


def _clean_location_name(value: object) -> str:
    """Local canônico: sem prefixo INT./EXT. e sem período do dia no fim.

    O LLM da decupagem às vezes devolve a slugline inteira como location
    ("Rua do Bairro - Amanhecer", "EXT. Rua do Bairro - Amanhecer"); isso
    duplicava o local nos prompts de frame ("Rua Do Bairro e Rua do Bairro -
    Amanhecer") e poluía a citação de referências.
    """
    name = str(value or "").strip()
    name = re.sub(r"(?i)^(?:INT|EXT|INT/EXT|EXT/INT)\.?\s*", "", name)
    # Repete porque o LLM pode anexar mais de um período ("... - DIA - TARDE").
    while True:
        stripped = _LOCATION_PERIOD_TAIL_RE.sub("", name).strip(" -–")
        if stripped == name:
            break
        name = stripped
    return re.sub(r"\s+", " ", name).strip()


def _unique_names(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


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
    shot_emotion: str = "",
) -> str:
    """Gera prompt cinematográfico para o provider de vídeo.

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

    # v12: sem composição/planos e sem linha de câmera — o modelo de vídeo
    # define cobertura e movimento sozinho; direções viravam ruído genérico.

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
        # Source Shots can still contain legacy durations. The continuous-video
        # contract always emits complete eight-second segments.
        shot_duration = int(segment_duration_seconds)
        source_text = str(source.get("text") or "").strip()
        action_source = str(source.get("storyboard_action") or source_text).strip()
        action = _normalize_segment_action(_compact_segment_action(action_source))
        storyboard_action = action
        continuity_break = bool(source.get("continuity_break"))
        continuity = (
            "comece estabelecendo o momento inicial da historia"
            if index == 1 or continuity_break
            else "continue diretamente o movimento e o estado emocional do segmento anterior"
        )
        characters = _names_present(source_text, visual_context.get("characters", []))
        locations = _names_present(source_text, visual_context.get("locations", []))
        source_shot = source.get("shot")
        scene = source.get("scene")
        if isinstance(source_shot, Shot):
            source_payload = dict(source_shot.payload or {})
            configured_characters = source_payload.get("characters")
            if not isinstance(configured_characters, list):
                configured_characters = []
            # A decupagem LLM às vezes grava como "personagem" algo que NÃO está
            # na Bíblia Visual (ex.: "Voz Distorcida", um efeito sonoro). Só um
            # nome presente na Bíblia Visual é personagem de verdade — nomes
            # estranhos ao contexto visual são descartados aqui, para não
            # virarem "X também está em cena" no prompt de vídeo.
            bible_character_names = {
                str(item.get("name") or "").strip().casefold()
                for item in visual_context.get("characters", [])
                if str(item.get("name") or "").strip()
            }
            characters = _unique_names(
                [
                    *characters,
                    *(
                        str(item)
                        for item in configured_characters
                        if str(item).strip().casefold() in bible_character_names
                    ),
                ]
            )
            configured_location = _clean_location_name(source_payload.get("location"))
            locations = _unique_names([*locations, configured_location])
            if isinstance(scene, Scene):
                legacy_action, legacy_context, legacy_previous_action = (
                    _legacy_shot_action_context(
                        source_shot,
                        list(shots_by_scene.get(scene.id, [])),
                    )
                )
                raw_shot_action = str(source_shot.action or "").strip()
                if (
                    _segment_action_has_fragile_ending(raw_shot_action)
                    or _starts_with_lowercase_word(raw_shot_action)
                    or _segment_action_has_fragile_ending(action)
                    or _starts_with_lowercase_word(action)
                ):
                    action = legacy_action
                    storyboard_action = legacy_action
                    source_text = legacy_action
                    characters = _unique_names(
                        [
                            *characters,
                            *_names_present(
                                source_text, visual_context.get("characters", [])
                            ),
                        ]
                    )
                    locations = _unique_names(
                        [
                            *locations,
                            *_names_present(
                                source_text, visual_context.get("locations", [])
                            ),
                        ]
                    )
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
        shot_emotion = str(source.get("emotion") or "").strip()

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
            shot_emotion=shot_emotion,
        )
        shot = source_shot
        shot_spec: ShotGenerationSpec | None = None
        compiler_version = CONTINUOUS_VIDEO_PROMPT_VERSION
        if isinstance(shot, Shot) and isinstance(scene, Scene):
            shot_payload = dict(shot.payload or {})
            raw_states = shot_payload.get("character_states")
            scene_context = str(
                shot_payload.get("scene_context") or legacy_context or scene.summary
            ).strip()
            character_states = raw_states if isinstance(raw_states, dict) else {}
            if not character_states:
                character_states = _derived_character_states(characters, scene_context)
            continuity_state = str(
                shot_payload.get("continuity_state") or legacy_previous_action
            ).strip()
            shot_spec = ShotGenerationSpec(
                shot_id=shot.id,
                scene_id=scene.id,
                scene_title=scene.title,
                scene_summary=scene.summary,
                scene_context=scene_context,
                continuity_state=continuity_state,
                duration_seconds=float(shot_duration),
                characters=characters,
                location=locations[0] if locations else None,
                props=[str(item) for item in shot_payload.get("props", [])],
                action=action,
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
            "storyboard_action": storyboard_action,
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
            "duration_seconds": shot_duration,
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
