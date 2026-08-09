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
    for scene_number, (section, durations) in enumerate(zip(sections, clip_groups, strict=True), 1):
        shots = [
            {
                "shot_number": shot_number,
                "duration_seconds": duration,
                "narration_text": section["summary"],
                "dialogue_text": "",
                "action": section["summary"],
                "emotion": "progressão dramatica",
                "visual_composition": (
                    "Composicao vertical 9:16 baseada nestá cena do roteiro, "
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
                "spatial_layout": DEFAULT_SCENE_SPATIAL_LAYOUT,
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
        shot.setdefault("camera_movement", "movimento suave e realista")
        shot.setdefault("generation_type", "IMAGE_TO_VIDEO")
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

    total = sum(
        int(shot["duration_seconds"]) for scene in normalized_scenes for shot in scene["shots"]
    )
    if total != target_duration_seconds:
        raise GenerationOutputError(
            "generate_scenes_and_shots: shot durations do not match target duration"
        )
    return {"scenes": normalized_scenes}
