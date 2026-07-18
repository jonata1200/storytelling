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

SAVED_IDEAS_PATH = Path(".runtime/idea_lab_saved.json")


async def generate_freeform_ideas(theme: str = "", count: int = 10) -> list[dict[str, Any]]:
    settings = get_settings()
    provider = OpenRouterLLMProvider() if settings.openrouter_api_key else MockLLMProvider()
    result = await provider.generate_structured(
        LLMRequest(
            task="generate_story_ideas",
            model=settings.openrouter_default_model,
            prompt=(
                f"Gere exatamente {count} ideias de historias originais em portugues do Brasil. "
                "A IA deve criar tambem temas diferentes para cada historia, sem depender "
                "de um tema informado pelo usuario. "
                "Cada ideia deve ser claramente diferente das outras em tema, genero, "
                "conflito, protagonista e emocao principal. "
                "Retorne JSON com a chave ideas; cada ideia deve ter title, genre, "
                "primary_emotion, theme, hook, premise, protagonist, retention_potential, "
                "cliche_risk e production_complexity. "
                f"Contexto opcional do usuario: {theme or 'nenhum'}."
            ),
            variables={
                "theme": theme or "tema livre criado pela IA",
                "count": count,
                "audience": "publico geral",
            },
            output_schema={"type": "object", "properties": {"ideas": {"type": "array"}}},
        )
    )
    ideas = list(result.content.get("ideas") or [])[:count]
    return [_normalize_idea(idea) for idea in ideas if isinstance(idea, dict)]


def load_saved_ideas(path: Path = SAVED_IDEAS_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Saved idea lab payload must be a JSON array")
    return [_normalize_idea(item) for item in payload if isinstance(item, dict)]


def save_idea(idea: dict[str, Any], path: Path = SAVED_IDEAS_PATH) -> dict[str, Any]:
    normalized = _normalize_idea(idea)
    ideas = [item for item in load_saved_ideas(path) if item.get("id") != normalized["id"]]
    ideas.insert(0, normalized)
    _write_saved_ideas(ideas, path)
    return normalized


def delete_saved_idea(idea_id: str, path: Path = SAVED_IDEAS_PATH) -> None:
    ideas = [item for item in load_saved_ideas(path) if item.get("id") != idea_id]
    _write_saved_ideas(ideas, path)


def _normalize_idea(idea: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(idea)
    normalized.setdefault("id", uuid.uuid4().hex)
    normalized.setdefault("genre", "Drama")
    normalized.setdefault("primary_emotion", normalized.get("final_emotion") or "Curiosidade")
    return normalized


def _write_saved_ideas(ideas: list[dict[str, Any]], path: Path = SAVED_IDEAS_PATH) -> None:
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
