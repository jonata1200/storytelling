"""Prompt formatting helpers for continuous-video segments."""

from typing import Any

from app.generation.shot_prompt_compiler import (
    VIDEO_PROMPT_MAX_CHARS,
    bounded_prompt,
    compact_text,
)


def concise_video_prompt(action: str, metadata: dict[str, Any]) -> str:
    shot_spec = metadata.get("shot_generation_spec")
    if isinstance(shot_spec, dict):
        try:
            from app.generation.shot_generation_spec import ShotGenerationSpec
            from app.generation.shot_prompt_compiler import VibesPromptCompiler

            spec = ShotGenerationSpec.model_validate(shot_spec)
            clean_action = " ".join(str(action or "").split()).strip()
            if clean_action:
                spec = spec.model_copy(update={"action": clean_action})
            return VibesPromptCompiler().compile(spec).prompt
        except (TypeError, ValueError):
            pass

    compact_action = compact_text(action, 190)
    from app.generation.shot_prompt_compiler import human_list

    character_names = [str(item) for item in list(metadata.get("characters") or [])[:4]]
    location_names = [str(item) for item in list(metadata.get("locations") or [])[:2]]
    characters = human_list(
        [name for name in character_names if name.casefold() not in compact_action.casefold()]
    )
    locations = human_list(
        [name for name in location_names if name.casefold() not in compact_action.casefold()]
    )
    parts: list[str] = []
    if locations and characters:
        parts.append(f"Contexto: {locations}, com {characters}.")
    elif locations:
        parts.append(f"Contexto: {locations}.")
    elif characters:
        parts.append(f"Também está em cena: {characters}.")
    if compact_action:
        parts.insert(0, f"{compact_action.rstrip('.')}.")
    return bounded_prompt(parts)


def video_provider_prompt(prompt: str, metadata: dict[str, Any]) -> str:
    """Envia somente a descrição da cena; opções técnicas ficam na requisição."""
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if len(clean_prompt) > VIDEO_PROMPT_MAX_CHARS:
        clean_prompt = compact_text(clean_prompt, VIDEO_PROMPT_MAX_CHARS)
    return clean_prompt
