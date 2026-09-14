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
    if compact_action:
        return bounded_prompt([f"{compact_action.rstrip('.')}."])
    return ""


def video_provider_prompt(prompt: str, metadata: dict[str, Any]) -> str:
    """Envia somente a descrição da cena; opções técnicas ficam na requisição."""
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if len(clean_prompt) > VIDEO_PROMPT_MAX_CHARS:
        clean_prompt = compact_text(clean_prompt, VIDEO_PROMPT_MAX_CHARS)
    return clean_prompt
