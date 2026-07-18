import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openrouter import OpenRouterLLMProvider
from app.providers.llm.types import LLMRequest
from app.storytelling.service import coerce_duration_minutes

SAVED_IDEAS_PATH = Path(".runtime/idea_lab_saved.json")
GENERATED_IDEAS_PATH = Path(".runtime/idea_lab_generated.json")


async def generate_freeform_ideas(
    theme: str = "",
    count: int = 10,
    genre: str = "",
    target_duration_minutes: float = 5.0,
) -> list[dict[str, Any]]:
    settings = get_settings()
    provider = OpenRouterLLMProvider() if settings.openrouter_api_key else MockLLMProvider()
    duration = coerce_duration_minutes(target_duration_minutes)
    genre_instruction = (
        f"Todas as ideias devem pertencer ao genero selecionado: {genre}. "
        if genre
        else "A IA pode escolher generos variados. "
    )
    result = await provider.generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            model=settings.openrouter_default_model,
            prompt=(
                f"Gere exatamente {count} ideias de historias originais em portugues do Brasil. "
                f"Todas as ideias devem ter potencial narrativo para exatamente {duration:g} "
                "minutos de historia, com conflito, virada e payoff adequados para esse tempo. "
                f"{genre_instruction}"
                "A IA deve criar tambem temas diferentes para cada historia, sem depender "
                "de um tema informado pelo usuario. "
                "Cada ideia deve ser claramente diferente das outras em tema, genero, "
                "conflito, protagonista e emocao principal. "
                "Retorne JSON com a chave ideas; cada ideia deve ter title, genre, "
                "primary_emotion, theme, hook, premise, protagonist, duration_minutes, "
                "retention_potential, cliche_risk e production_complexity. "
                f"Use duration_minutes igual a {duration:g} em todas as ideias. "
                f"Contexto opcional do usuario: {theme or 'nenhum'}."
            ),
            variables={
                "theme": theme or "tema livre criado pela IA",
                "count": count,
                "genre": genre or "genero livre criado pela IA",
                "duration_range_minutes": f"{duration:g}",
                "target_duration_minutes": duration,
                "audience": "publico geral",
            },
            output_schema={"type": "object", "properties": {"ideas": {"type": "array"}}},
        )
    )
    ideas = list(result.content.get("ideas") or [])[:count]
    return [_normalize_idea(idea, duration) for idea in ideas if isinstance(idea, dict)]


def load_saved_ideas(path: Path = SAVED_IDEAS_PATH) -> list[dict[str, Any]]:
    return _load_ideas(path, "Saved idea lab")


def load_generated_ideas(path: Path = GENERATED_IDEAS_PATH) -> list[dict[str, Any]]:
    return _load_ideas(path, "Generated idea lab")


def replace_generated_ideas(
    ideas: list[dict[str, Any]],
    path: Path = GENERATED_IDEAS_PATH,
) -> list[dict[str, Any]]:
    normalized = [_normalize_idea(item) for item in ideas]
    _write_ideas(normalized, path)
    return normalized


def delete_generated_idea(idea_id: str, path: Path = GENERATED_IDEAS_PATH) -> None:
    ideas = [item for item in load_generated_ideas(path) if item.get("id") != idea_id]
    _write_ideas(ideas, path)


def delete_all_ideas(
    saved_path: Path = SAVED_IDEAS_PATH,
    generated_path: Path = GENERATED_IDEAS_PATH,
) -> int:
    saved_count = len(load_saved_ideas(saved_path))
    generated_count = len(load_generated_ideas(generated_path))
    _write_ideas([], saved_path)
    _write_ideas([], generated_path)
    return saved_count + generated_count


def _load_ideas(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [_normalize_idea(item) for item in payload if isinstance(item, dict)]


def save_idea(idea: dict[str, Any], path: Path = SAVED_IDEAS_PATH) -> dict[str, Any]:
    normalized = _normalize_idea(idea)
    ideas = [item for item in load_saved_ideas(path) if item.get("id") != normalized["id"]]
    ideas.insert(0, normalized)
    _write_ideas(ideas, path)
    return normalized


def delete_saved_idea(idea_id: str, path: Path = SAVED_IDEAS_PATH) -> None:
    ideas = [item for item in load_saved_ideas(path) if item.get("id") != idea_id]
    _write_ideas(ideas, path)


def _normalize_idea(idea: dict[str, Any], default_duration_minutes: float = 5.0) -> dict[str, Any]:
    normalized = dict(idea)
    normalized.setdefault("id", uuid.uuid4().hex)
    normalized.setdefault("genre", "Drama")
    normalized.setdefault("primary_emotion", normalized.get("final_emotion") or "Curiosidade")
    normalized["duration_minutes"] = coerce_duration_minutes(
        normalized.get("duration_minutes"), default_duration_minutes
    )
    return normalized


def _write_ideas(ideas: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix="ideas-", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(ideas, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
