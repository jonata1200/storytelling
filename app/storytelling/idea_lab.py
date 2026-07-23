import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config.model_policy import ensure_openrouter_api_key, validate_openrouter_model_name
from app.config.settings import get_settings
from app.providers.llm.openrouter import OpenRouterLLMProvider
from app.providers.llm.types import LLMRequest, LLMResult
from app.storytelling.service import (
    GenerationOutputError,
    _story_idea_retry_guidance,
    coerce_duration_minutes,
    normalize_story_idea_payload,
    story_idea_diversity_errors,
    story_idea_validation_errors,
)

SAVED_IDEAS_PATH = Path(".runtime/idea_lab_saved.json")
GENERATED_IDEAS_PATH = Path(".runtime/idea_lab_generated.json")
IDEA_PROVIDER_TIMEOUT_SECONDS = 120


def build_idea_lab_prompt(
    theme: str,
    count: int,
    genre: str,
    duration_minutes: float,
    retry_guidance: str = "",
) -> str:
    duration = f"{duration_minutes:g}"
    genre_instruction = (
        f"Genero obrigatorio: todas as ideias devem ser de {genre}."
        if genre
        else "Genero livre: escolha generos variados e adequados a cada ideia."
    )
    theme_instruction = (
        f"Contexto criativo informado pelo usuario: {theme.strip()}."
        if theme.strip()
        else (
            "Contexto criativo informado pelo usuario: nenhum. Crie temas especificos, "
            "concretos e diferentes entre si."
        )
    )
    retry_instruction = (
        f"\nCorrecao obrigatoria da tentativa anterior: {retry_guidance}"
        if retry_guidance
        else ""
    )

    return (
        "Voce e um diretor de desenvolvimento narrativo especializado em historias "
        "curtas para video. Gere ideias originais, cinematograficas e prontas para "
        "virar roteiro.\n\n"
        f"Tarefa: gere exatamente {count} ideias em portugues do Brasil.\n"
        f"Duracao obrigatoria: cada ideia deve sustentar exatamente {duration} minutos "
        "de historia, com complexidade proporcional ao tempo escolhido.\n"
        f"{genre_instruction}\n"
        f"{theme_instruction}\n\n"
        "Regras de qualidade:\n"
        "- Nao numere os titulos e nao use prefixos como 'Ideia 01'.\n"
        "- Cada titulo deve funcionar sozinho em um card: curto, claro e intrigante.\n"
        "- Cada ideia deve ter protagonista, desejo, conflito, obstaculos, risco, "
        "virada, climax e payoff emocional bem definidos.\n"
        "- As ideias precisam ser realmente diferentes entre si em tema, mundo, "
        "tipo de protagonista, profissao, faixa de vida, local principal, objeto "
        "dramatico, antagonismo, dilema central, emocao principal e revelacao final.\n"
        "- Nao reutilize a mesma personagem com nome diferente; cada protagonista "
        "deve ter identidade, desejo, medo e contexto social proprios.\n"
        "- Evite modelos genericos como segredo do passado, heranca misteriosa ou "
        "mensagem que muda tudo, carta atrasada, casa de familia ou reconciliacao "
        "familiar, a menos que haja uma abordagem muito especifica.\n"
        "- O hook deve prender nos primeiros segundos; a premise deve explicar a "
        "historia em 2 ou 3 frases objetivas.\n"
        "- Para duracoes maiores, aumente a escalada, o numero de obstaculos e a "
        "profundidade emocional, sem transformar a ideia em serie.\n\n"
        "Retorne somente JSON valido, sem markdown, sem comentarios e sem texto fora "
        "do objeto. O objeto raiz deve ter a chave \"ideas\". Cada item em \"ideas\" "
        "deve conter exatamente estes campos: title, genre, primary_emotion, theme, "
        "hook, premise, protagonist, duration_minutes, conflict, obstacles, stakes, "
        "twist, climax, payoff, resolution, retention_potential, cliche_risk e "
        "production_complexity.\n"
        f"Use duration_minutes igual a {duration} em todas as ideias. "
        "retention_potential, cliche_risk e production_complexity devem ser numeros "
        "de 0 a 100. obstacles deve ser uma lista com 2 a 4 obstaculos concretos."
        f"{retry_instruction}"
    )


async def generate_freeform_ideas(
    theme: str = "",
    count: int = 10,
    genre: str = "",
    target_duration_minutes: float = 5.0,
) -> list[dict[str, Any]]:
    settings = get_settings()
    ensure_openrouter_api_key(settings.openrouter_api_key)
    provider = OpenRouterLLMProvider()
    count = max(1, min(10, int(count)))
    duration = coerce_duration_minutes(target_duration_minutes)
    retry_guidance = ""
    request = LLMRequest(
        task="generate_story_ideas",
        model=validate_openrouter_model_name(settings.openrouter_default_model),
        prompt=build_idea_lab_prompt(theme, count, genre, duration, retry_guidance),
        variables={
            "theme": theme or "tema livre criado pela IA",
            "count": count,
            "genre": genre or "genero livre criado pela IA",
            "duration_range_minutes": f"{duration:g}",
            "target_duration_minutes": duration,
            "audience": "publico geral",
            "retry_guidance": retry_guidance,
        },
        output_schema={"type": "object", "properties": {"ideas": {"type": "array"}}},
    )
    result = await _generate_with_runtime_fallback(provider, request)
    try:
        return _normalize_generated_ideas(result, count, duration)
    except GenerationOutputError as exc:
        retry_guidance = _story_idea_retry_guidance([str(exc)])
        retry_request = request.model_copy(
            update={
                "prompt": build_idea_lab_prompt(theme, count, genre, duration, retry_guidance),
                "variables": request.variables | {"retry_guidance": retry_guidance},
            }
        )
        result = await _generate_with_runtime_fallback(provider, retry_request)
        return _normalize_generated_ideas(result, count, duration)


async def _generate_with_runtime_fallback(
    provider: OpenRouterLLMProvider, request: LLMRequest
) -> LLMResult:
    try:
        provider_call = provider.generate_structured(request)
        return await asyncio.wait_for(provider_call, timeout=IDEA_PROVIDER_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise RuntimeError(
            f"OpenRouter demorou mais de {IDEA_PROVIDER_TIMEOUT_SECONDS}s ao gerar ideias. "
            "Tente novamente ou escolha um modelo de texto mais estavel."
        ) from exc
    except RuntimeError as exc:
        raise RuntimeError(
            "Nao foi possivel gerar ideias com o modelo configurado. "
            f"Detalhe do provedor: {exc}"
        ) from exc


def _normalize_generated_ideas(
    result: LLMResult, count: int, default_duration_minutes: float
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    raw_ideas = result.content.get("ideas")
    if not isinstance(raw_ideas, list) or not raw_ideas:
        raise GenerationOutputError("generate_story_ideas: missing non-empty list 'ideas'")
    for index, raw_idea in enumerate(raw_ideas[:count], 1):
        if not isinstance(raw_idea, dict):
            errors.append(f"generate_story_ideas.ideas[{index}]: expected JSON object")
            continue
        try:
            idea = _normalize_idea(raw_idea, default_duration_minutes)
        except GenerationOutputError as exc:
            errors.append(str(exc))
            continue
        idea_errors = story_idea_validation_errors(idea)
        if idea_errors:
            errors.extend(
                f"generate_story_ideas.ideas[{index}]: {error}" for error in idea_errors
            )
            continue
        normalized.append(idea)
    if not normalized:
        errors.append(f"generate_story_ideas: esperado ao menos 1 ideia valida de {count}")
    if not errors and len(normalized) > 1:
        errors.extend(story_idea_diversity_errors(normalized))
    if errors:
        raise GenerationOutputError("; ".join(errors))
    return normalized


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
    ideas: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            ideas.append(_normalize_idea(item))
        except GenerationOutputError:
            continue
    return ideas


def save_idea(idea: dict[str, Any], path: Path = SAVED_IDEAS_PATH) -> dict[str, Any]:
    normalized = _normalize_idea(idea)
    normalized_key = _idea_dedupe_key(normalized)
    ideas = [
        item
        for item in load_saved_ideas(path)
        if item.get("id") != normalized["id"] and _idea_dedupe_key(item) != normalized_key
    ]
    ideas.insert(0, normalized)
    _write_ideas(ideas, path)
    return normalized


def delete_saved_idea(idea_id: str, path: Path = SAVED_IDEAS_PATH) -> None:
    ideas = [item for item in load_saved_ideas(path) if item.get("id") != idea_id]
    _write_ideas(ideas, path)


def _normalize_idea(idea: dict[str, Any], default_duration_minutes: float = 5.0) -> dict[str, Any]:
    normalized = normalize_story_idea_payload(
        idea, default_duration_minutes=default_duration_minutes
    )
    normalized.setdefault("id", uuid.uuid4().hex)
    return normalized


def _idea_dedupe_key(idea: dict[str, Any]) -> tuple[str, str, str, str]:
    normalized = _normalize_idea(idea)
    return (
        str(normalized.get("title") or "").casefold().strip(),
        str(normalized.get("genre") or "").casefold().strip(),
        f"{coerce_duration_minutes(normalized.get('duration_minutes')):g}",
        str(normalized.get("premise") or "").casefold().strip(),
    )


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
