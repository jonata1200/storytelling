import re

from app.storytelling.normalization_common import (
    GenerationOutputError,
    _required_list,
    _required_mapping,
    _shot_narration_text,
)
from app.storytelling.script_normalization import _script_block_to_text
from app.video_generation.durations import validate_video_clip_duration, video_clip_durations

DEFAULT_SCENE_SPATIAL_LAYOUT = (
    "Mapa espacial da cena: definir posicoes relativas fixas de personagens, "
    "objetos importantes, entradas, mesa, assentos e fundo. Manter eixo de camera "
    "coerente entre planos, permitindo variar enquadramento sem trocar lados da tela."
)
DEFAULT_SHOT_SPATIAL_CONTINUITY = (
    "Continuar o blocking da cena: preservar esquerda/direita, distancia entre "
    "personagens, relacao com objetos e direcao de olhar/movimento estabelecidas "
    "nos planos anteriores, salvo se a acao mostrar deslocamento claro."
)

_SCREENPLAY_TRANSITION_RE = re.compile(
    r"(?i)^(?:FADE\s+(?:IN|OUT)|CUT\s+TO|CORTE\s+PARA|DISSOLVE\s+TO)\b"
)
_SCENE_HEADING_RE = re.compile(r"(?i)^(?:INT|EXT|INT/EXT|INT\./EXT)\.?\b")
_SCRIPT_LABEL_RE = re.compile(
    r"(?i)^(?:dura[cç][aã]o|objetivo(?:\s+dramatico)?|a[cç][aã]o|narra[cç][aã]o)\s*:"
)


def _is_character_cue(value: str) -> bool:
    cue = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()
    if not cue or cue != cue.upper() or len(cue.split()) > 5:
        return False
    # Marcadores estruturais de roteiro (transições e sluglines) NÃO são cues de
    # personagem: já entraram como "Corte Para:" e "Int. Depósito..." na lista
    # de personagens de segmentos reais.
    if _SCREENPLAY_TRANSITION_RE.match(cue) or _SCENE_HEADING_RE.match(cue):
        return False
    # Cabecalho de cena combinado ("CENA 04 - EXT. PRAÇA CENTRAL - DIA") não é
    # cue de personagem, mesmo em variantes curtas com <=5 tokens.
    if re.match(r"(?i)^CENA\s+\d+\s*[-:]", cue):
        return False
    return True


def _screenplay_action_units(block: str) -> list[str]:
    """Extract visual, ordered action sentences while ignoring headings and dialogue."""
    units: list[str] = []
    for raw_paragraph in re.split(r"\n\s*\n", str(block or "")):
        lines = [line.strip() for line in raw_paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0]
        if (
            _SCENE_HEADING_RE.match(first)
            or _SCREENPLAY_TRANSITION_RE.match(first)
            or _is_character_cue(first)
        ):
            continue
        paragraph = " ".join(lines)
        paragraph = _SCRIPT_LABEL_RE.sub("", paragraph).strip()
        units.extend(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph)
            if sentence.strip()
        )
    return units


def _partition_action_units(units: list[str], count: int, fallback: str) -> list[str]:
    if count <= 0:
        return []
    clean_units = [re.sub(r"\s+", " ", unit).strip() for unit in units if unit.strip()]
    if not clean_units:
        clean_units = [re.sub(r"\s+", " ", fallback).strip() or "A acao da cena continua."]

    if len(clean_units) >= count:
        return [
            " ".join(
                clean_units[
                    (index * len(clean_units)) // count : ((index + 1) * len(clean_units)) // count
                ]
            )
            for index in range(count)
        ]

    # Nunca corte uma frase por quantidade de palavras. Quando uma cena possui menos
    # ações que planos, distribua a mesma ação completa em momentos consecutivos.
    assignments = [
        clean_units[min((index * len(clean_units)) // count, len(clean_units) - 1)]
        for index in range(count)
    ]
    return _differentiate_repeated_beats(assignments)


def _differentiate_repeated_beats(beats: list[str]) -> list[str]:
    """Transforma repetições consecutivas do mesmo beat em momentos distintos.

    A distribuição round-robin das frases da cena repete a MESMA ação em
    planos consecutivos ("ELIAS abre os olhos..." nos planos 1 e 2) quando a
    cena tem menos frases que planos. Dois planos idênticos viram dois
    segmentos de storyboard com o mesmo prompt — os frames saem cópias um do
    outro. A reescrita mantém a primeira ocorrência com a frase original do
    roteiro e prefixa as repetições consecutivas como continuação da mesma
    ação, sem inventar conteúdo que não existe no roteiro.
    """
    differentiated = list(beats)
    index = 0
    while index < len(differentiated):
        end = index
        while (
            end + 1 < len(differentiated)
            and differentiated[end + 1] == differentiated[index]
        ):
            end += 1
        run_length = end - index + 1
        if run_length > 1:
            for offset in range(1, run_length):
                differentiated[index + offset] = (
                    f"Continue esta mesma ação, preservando posições e objetos: "
                    f"{differentiated[index + offset]}"
                )
        index = end + 1
    return differentiated


def _section_action_beats(section: dict, count: int) -> list[str]:
    return _partition_action_units(
        _screenplay_action_units(str(section.get("block") or "")),
        count,
        str(section.get("summary") or section.get("title") or ""),
    )


def _section_character_names(block: str) -> list[str]:
    names: list[str] = []
    for raw_line in str(block or "").splitlines():
        line = raw_line.strip()
        if _is_character_cue(line):
            clean = re.sub(r"\s*\([^)]*\)\s*$", "", line).strip().title()
            if clean and clean not in names:
                names.append(clean)
    return names


def _section_location(title: str) -> str:
    location = re.sub(r"(?i)^(?:INT|EXT|INT/EXT|INT\./EXT)\.?\s*", "", str(title or ""))
    location = re.split(
        r"\s+[\-\u2013]\s+(?:DIA|NOITE|TARDE|MANH\u00c3|MADRUGADA)\b",
        location,
        maxsplit=1,
        flags=re.I,
    )[0]
    # Padroniza "SALA DE SEGURANÇA DO MUSEU" (slugline caixa alta) para caixa
    # natural: "Sala de Segurança do Museu", batendo com a Bíblia Visual.
    from app.ui.shared.page_config import standardize_title_case

    return standardize_title_case(re.sub(r"\s+", " ", location).strip(" .-"))


_LIGHTING_PATTERNS = (
    r"(?P<lead>luz(?:es)? [a-zà-ÿ]+(?: de [a-zà-ÿ]+)?)",
    r"(?P<lead>luz [a-zà-ÿ]+(?:\s+[a-zà-ÿ]+){0,3})",
)


def _section_lighting(scene_context: str) -> str:
    """Extrai a primeira menção de iluminação do contexto da cena.

    "A luz azulada de MONITORES DE SEGURANÇA reflete..." →
    "luz azulada de monitores de segurança".
    """
    text = " ".join(str(scene_context or "").split())
    match = re.search(
        r"(?i)\b(luz(?:es)?\s+(?:[a-zà-ÿ]+\s+){0,3}[a-zà-ÿ]+)", text
    )
    if match is None:
        return ""
    lighting = match.group(1).strip().rstrip(".,;:")
    return lighting[:120]


def _shot_visual_composition(
    *, action: str, characters: list[str], location: str, lighting: str
) -> str:
    """Composição visual real do shot, derivada da ação da cena.

    Descreve APENAS o enquadramento (sujeito, ambiente, luz) — sem a frase
    "Enquadramento vertical..." no conteúdo: quem formata o rótulo é o
    compilador de prompt de vídeo, e duplicá-lo aqui fazia o compilador
    prefixar "Enquadramento:" duas vezes e cortar a frase ao meio.
    """

    parts: list[str] = []
    subject = characters[0].strip() if characters else ""
    if subject and subject.casefold() not in action.casefold():
        parts.append(f"Plano centrado em {subject}")
    elif subject:
        parts.append(f"Plano centrado em {subject} durante a ação")
    if location:
        parts.append(f"no ambiente {location}")
    if lighting:
        parts.append(f"com {lighting}")
    if not parts:
        return "Plano cinematográfico vertical seguindo a ação descrita."
    return ", ".join(parts[:3])


_EMOTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("medo", "treme", "suor", "foge", "fugindo", "assust"), "tensão"),
    (("corre", "grita", "confronto", "briga", "empurra", "arranca"), "urgência"),
    (("chora", "chorando", "lágrima", "saudade", "cabeça baixa"), "melancolia"),
    (("sorriso", "sorrir", "abraça", "abraço", "riso", "comemora"), "alegria contida"),
    (("esperança", "respira", "alívio", "alivio", "amanhece"), "esperança"),
    (("hesita", "dúvida", "duvida", "olha para o", "observa", "encara"), "hesitação"),
    (("entrega", "devolve", "oferece", "estende"), "decisão"),
)


def _shot_emotion(action: str) -> str:
    """Emoção dominante do shot, derivada do verbo da ação.

    Substitui o placeholder fixo "progressão dramatica" (idêntico em 100% dos
    shots), que não carregava informação nenhuma para o modelo de vídeo.
    """
    normalized = " ".join(str(action or "").split()).casefold()
    for words, emotion in _EMOTION_RULES:
        if any(word in normalized for word in words):
            return emotion
    return "determinação"


def _scene_continuity_data(
    section: dict, carried_states: dict[str, dict]
) -> tuple[str, list[str], dict[str, dict]]:
    block = str(section.get("block") or "")
    actions = _screenplay_action_units(block)
    scene_context = " ".join(actions).strip()
    characters = _section_character_names(block)
    states = {name: dict(value) for name, value in carried_states.items()}
    for name in characters:
        relevant = [action for action in actions if name.casefold() in action.casefold()]
        if relevant:
            states[name] = {
                "continuity_notes": " ".join(relevant)[:700],
                "condition": relevant[-1][:300],
            }
        else:
            states.setdefault(
                name,
                {"continuity_notes": f"Preserve o estado de {name} estabelecido anteriormente."},
            )
    return scene_context, characters, states


def _validate_distinct_shot_actions(scenes: list[dict]) -> None:
    for scene in scenes:
        shots = list(scene.get("shots") or [])
        if len(shots) <= 1:
            continue
        actions = {re.sub(r"\s+", " ", str(shot.get("action") or "")).strip() for shot in shots}
        if len(actions) != len(shots):
            raise GenerationOutputError(
                "generate_scenes_and_shots: each Shot in a scene must have a distinct action"
            )


def _script_scene_sections(script_content: str) -> list[dict]:
    text = str(script_content or "")
    pattern = re.compile(r"(?im)^\s*CENA\s+0*(?P<number>\d+)(?:\s*[-:]\s*(?P<title>.+?))?\s*$")
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
                    if not re.match(r"(?i)^(duração|dura[cç][aã]o|objetivo)\s*:", line)
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


def _scene_plan_from_script_sections(sections: list[dict], target_duration_seconds: int) -> dict:
    clip_durations = video_clip_durations(target_duration_seconds)
    clip_groups = _clip_groups_for_script_sections(clip_durations, sections)
    scenes: list[dict] = []
    carried_states: dict[str, dict] = {}
    for scene_number, (section, durations) in enumerate(zip(sections, clip_groups, strict=True), 1):
        action_beats = _section_action_beats(section, len(durations))
        scene_context, characters, carried_states = _scene_continuity_data(
            section, carried_states
        )
        location = _section_location(str(section["title"]))
        scene_lighting = _section_lighting(scene_context)
        previous_action = "Estado inicial descrito pelo contexto completo da cena."
        shots = [
            {
                "shot_number": shot_number,
                "duration_seconds": duration,
                "narration_text": action_beats[shot_number - 1],
                "dialogue_text": "",
                "action": action_beats[shot_number - 1],
                "emotion": _shot_emotion(action_beats[shot_number - 1]),
                "visual_composition": _shot_visual_composition(
                    action=action_beats[shot_number - 1],
                    characters=characters,
                    location=location,
                    lighting=scene_lighting,
                ),
                # Sem movimento inventado: o compilador omite a linha de
                # câmera quando este campo está vazio. "movimento curto e
                # realista" em 100% dos shots virava ruído no prompt.
                "camera_movement": "",
                "generation_type": "TEXT_TO_VIDEO",
                "characters": characters,
                "location": location,
                "props": [],
                "character_states": carried_states,
                "lighting": scene_lighting,
                "scene_context": scene_context[:1400],
                "continuity_state": (
                    previous_action if shot_number == 1 else action_beats[shot_number - 2]
                ),
                "spatial_continuity": (
                    f"Na cena, {scene_context[:900]} Preserve a posição, postura e relação "
                    "dos personagens com os objetos até que uma ação mostre a mudança."
                ),
                "continuity": {
                    "continuity_break": shot_number == 1,
                    "stable_elements": [scene_context[:700]],
                },
            }
            for shot_number, duration in enumerate(durations, 1)
        ]
        scenes.append(
            {
                "scene_number": scene_number,
                "title": section["title"],
                "summary": section["summary"],
                "spatial_layout": (
                    f"Estado visual da cena: {scene_context[:1200]} "
                    f"{DEFAULT_SCENE_SPATIAL_LAYOUT}"
                ),
                "duration_seconds": sum(durations),
                "shots": shots,
            }
        )
    # A short scene may legitimately need several eight-second continuations of
    # the same complete action. Keeping the sentence intact is more important
    # than manufacturing different fragments just to make every value unique.
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
        missing_count = len(clip_durations) - len(flattened)
        for continuation_index in range(1, missing_count + 1):
            continuation = dict(last_shot)
            continuation["narration_text"] = (
                str(continuation.get("narration_text") or continuation.get("action") or "")
                + f" Continuidade visual {continuation_index} de {missing_count}."
            ).strip()
            continuation["action"] = (
                str(continuation.get("action") or "A acao continua em nova tomada curta.")
                + f" Momento seguinte {continuation_index} de {missing_count}: a emocao "
                "evolui sem quebrar a continuidade."
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
                str(last_shot.get("action") or "").strip() + " " + " ".join(extra_actions)
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
        shot.setdefault("emotion", "tensão emocional")
        shot.setdefault(
            "visual_composition",
            "Composicao vertical 9:16 com sujeito principal, ambiente e luz definidos.",
        )
        shot.setdefault("spatial_continuity", DEFAULT_SHOT_SPATIAL_CONTINUITY)
        # Ausência de movimento é um valor válido desde vibes_shot_v11: o
        # compilador omite a linha de câmera quando o campo está vazio. Não
        # preencher com placeholder ("movimento suave e realista" virava
        # "A câmera movimento suave e realista." no prompt, em todo shot).
        shot.setdefault("camera_movement", "")
        shot["generation_type"] = "TEXT_TO_VIDEO"
        groups[-1][1].append(shot)

    normalized_scenes: list[dict] = []
    for scene_number, (scene, shots) in enumerate(groups, 1):
        scene = dict(scene)
        scene["scene_number"] = scene_number
        scene.setdefault("title", f"Cena {scene_number}")
        scene.setdefault("summary", _shot_narration_text(shots[0], f"scene[{scene_number}]"))
        scene.setdefault("spatial_layout", DEFAULT_SCENE_SPATIAL_LAYOUT)
        scene["shots"] = shots
        scene["duration_seconds"] = sum(int(shot["duration_seconds"]) for shot in shots)
        normalized_scenes.append(scene)

    _validate_distinct_shot_actions(normalized_scenes)

    total = sum(
        int(shot["duration_seconds"]) for scene in normalized_scenes for shot in scene["shots"]
    )
    normalized_target_duration = sum(clip_durations)
    if total != normalized_target_duration:
        raise GenerationOutputError(
            "generate_scenes_and_shots: shot durations do not match target duration"
        )
    return {"scenes": normalized_scenes}
