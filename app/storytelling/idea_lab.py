import asyncio
import json
import os
import tempfile
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config.provider_policy import (
    validate_model_name,
)
from app.config.settings import get_settings
from app.generation.model_settings import configured_text_llm_provider
from app.providers.llm.types import LLMProvider, LLMRequest, LLMResult
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
IDEA_LAB_DURATION_MINUTES = 5.0
IDEA_PROVIDER_TIMEOUT_SECONDS = 300
IDEA_PROGRESS_BATCH_SIZE = 2

# Lock de processo para serializar read-modify-write nos JSON files de ideias.
# Previne lost updates entre coroutines e threads dentro do mesmo processo.
# Para multi-processo, migrar para DB ou file lock跨-processo.
_idea_lab_lock = threading.Lock()


def build_idea_lab_prompt(
    theme: str,
    count: int,
    genre: str,
    primary_emotion: str,
    duration_minutes: float,
    retry_guidance: str = "",
    avoidance_memory: str = "",
) -> str:
    duration = f"{coerce_duration_minutes(duration_minutes):g}"
    genre_instruction = (
        f"Gênero obrigatório: todas as ideias devem ser de {genre}."
        if genre
        else "Gênero livre: escolha gêneros variados e adequados a cada ideia."
    )
    emotion = str(primary_emotion or "").strip()
    emotion_instruction = (
        "Emocao principal obrigatoria: todas as ideias devem ter "
        f"primary_emotion igual a {emotion}."
        if emotion
        else "Emocao principal livre: escolha a emocao dominante mais forte para cada ideia."
    )
    theme_instruction = (
        f"Contexto criativo informado pelo usuario: {theme.strip()}."
        if theme.strip()
        else (
            "Contexto criativo informado pelo usuario: nenhum. Crie temas específicos, "
            "concretos e diferentes entre si."
        )
    )
    retry_instruction = (
        f"\nCorrecao obrigatoria da tentativa anterior: {retry_guidance}" if retry_guidance else ""
    )
    avoidance_instruction = (
        f"\nIdeias ja geradas nesta rodada que devem ser evitadas: {avoidance_memory.strip()}."
        if avoidance_memory.strip()
        else ""
    )

    return (
        "Você é um diretor de desenvolvimento narrativo cinematográfico de alto nível "
        "especializado em histórias curtas de alto impacto para vídeo (High-Concept). "
        "Gere ideias originais, magnéticas e prontas para virar roteiro.\n\n"
        f"Tarefa: gere exatamente {count} ideias em portugues do Brasil.\n"
        f"Duracao obrigatoria: cada ideia deve sustentar exatamente {duration} minutos "
        "de historia, com complexidade proporcional ao tempo escolhido.\n"
        f"{genre_instruction}\n"
        f"{emotion_instruction}\n"
        f"{theme_instruction}\n\n"
        "Regras de qualidade High-Concept:\n"
        "- Não numere os títulos e não use prefixos como 'Ideia 01'.\n"
        "- Cada título deve funcionar sozinho em um card: curto, potente e instigante.\n"
        "- Premissa magnética: o hook deve prender imediatamente nos primeiros 3 segundos, "
        "e a premissa deve resumir a premissa dramática e visual em 2 a 3 frases objetivas.\n"
        "- Protagonista ativo com dilema moral visceral, desejo urgente "
        "e antagonismo proporcional.\n"
        "- Conflito e obstáculos físicos/emocionais concretos, com virada (twist) orgânica que "
        "ressignifique a história, clímax de escolha difícil e payoff emocional inesquecível.\n"
        "- As ideias precisam ser radicalmente diferentes entre si em tema, mundo, "
        "tipo de protagonista, profissão, faixa de vida, local principal, objeto "
        "dramático, antagonismo, dilema central, emoção principal e revelação final.\n"
        "- Não reutilize a mesma personagem com nome diferente; cada protagonista "
        "deve ter identidade, desejo, medo e contexto social próprios.\n"
        "- Evite modelos genéricos como segredo do passado, herança misteriosa, "
        "carta atrasada, casa de família ou reconciliação familiar como motor padrão.\n"
        f"- Estruture a ideia para um roteiro curto de {duration} minutos, com escala objetiva "
        "e produção cinematográfica enxuta e 100% filmável.\n\n"
        "Retorne somente JSON válido, sem markdown, sem comentarios e sem texto fora "
        'do objeto. O objeto raiz deve ter a chave "ideas". Cada item em "ideas" '
        "deve conter exatamente estes campos: title, genre, primary_emotion, theme, "
        "hook, premise, protagonist, duration_minutes, conflict, obstacles, stakes, "
        "twist, climax, payoff, resolution, retention_potential, cliche_risk e "
        "production_complexity.\n"
        f"Use duration_minutes igual a {duration} em todas as ideias. "
        f"{'Use primary_emotion igual a ' + emotion + ' em todas as ideias. ' if emotion else ''}"
        "retention_potential, cliche_risk e production_complexity devem ser números "
        "de 0 a 100. obstacles deve ser uma lista com 2 a 4 obstaculos concretos."
        f"{avoidance_instruction}"
        f"{retry_instruction}"
    )


async def generate_freeform_ideas(
    theme: str = "",
    count: int = 10,
    genre: str = "",
    primary_emotion: str = "",
    target_duration_minutes: float = IDEA_LAB_DURATION_MINUTES,
) -> list[dict[str, Any]]:
    settings = get_settings()
    provider, model, configured_provider = configured_text_llm_provider(settings)
    model = validate_model_name(
        model,
        provider=configured_provider,
    )
    count = max(1, min(10, int(count)))
    duration = coerce_duration_minutes(target_duration_minutes)
    return await _generate_freeform_idea_batch(
        provider,
        model,
        theme,
        count,
        genre,
        primary_emotion,
        duration,
    )


async def generate_freeform_idea_batches(
    theme: str = "",
    count: int = 10,
    genre: str = "",
    primary_emotion: str = "",
    target_duration_minutes: float = IDEA_LAB_DURATION_MINUTES,
    *,
    batch_size: int = IDEA_PROGRESS_BATCH_SIZE,
) -> AsyncIterator[list[dict[str, Any]]]:
    settings = get_settings()
    provider, model, configured_provider = configured_text_llm_provider(settings)
    model = validate_model_name(
        model,
        provider=configured_provider,
    )
    total = max(1, min(10, int(count)))
    duration = coerce_duration_minutes(target_duration_minutes)
    safe_batch_size = max(1, min(total, int(batch_size)))
    generated: list[dict[str, Any]] = []
    while len(generated) < total:
        remaining = total - len(generated)
        current_batch_size = min(safe_batch_size, remaining)
        batch = await _generate_freeform_idea_batch(
            provider,
            model,
            theme,
            current_batch_size,
            genre,
            primary_emotion,
            duration,
            avoidance_memory=_idea_batch_avoidance_memory(generated),
        )
        generated.extend(batch)
        yield batch


async def _generate_freeform_idea_batch(
    provider: LLMProvider,
    model: str,
    theme: str,
    count: int,
    genre: str,
    primary_emotion: str,
    duration: float,
    *,
    avoidance_memory: str = "",
) -> list[dict[str, Any]]:
    retry_guidance = ""
    request = LLMRequest(
        task="generate_story_ideas",
        model=model,
        prompt=build_idea_lab_prompt(
            theme,
            count,
            genre,
            primary_emotion,
            duration,
            retry_guidance,
            avoidance_memory,
        ),
        variables={
            "theme": theme or "tema livre criado pela IA",
            "count": count,
            "genre": genre or "gênero livre criado pela IA",
            "primary_emotion": primary_emotion or "emoção livre criada pela IA",
            "duration_range_minutes": f"{duration:g}",
            "target_duration_minutes": duration,
            "audience": "público geral",
            "retry_guidance": retry_guidance,
            "avoidance_memory": avoidance_memory,
        },
        output_schema={"type": "object", "properties": {"ideas": {"type": "array"}}},
        timeout_seconds=IDEA_PROVIDER_TIMEOUT_SECONDS,
    )
    result = await _generate_with_runtime_fallback(provider, request)
    try:
        return _normalize_generated_ideas(result, count, duration, primary_emotion)
    except GenerationOutputError as exc:
        retry_guidance = _story_idea_retry_guidance([str(exc)])
        retry_request = request.model_copy(
            update={
                "prompt": build_idea_lab_prompt(
                    theme,
                    count,
                    genre,
                    primary_emotion,
                    duration,
                    retry_guidance,
                    avoidance_memory,
                ),
                "variables": request.variables
                | {"retry_guidance": retry_guidance, "avoidance_memory": avoidance_memory},
            }
        )
        result = await _generate_with_runtime_fallback(provider, retry_request)
        return _normalize_generated_ideas(result, count, duration, primary_emotion)


def _idea_batch_avoidance_memory(ideas: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for idea in ideas[-8:]:
        fragments.append(
            " | ".join(
                str(value)
                for value in (
                    idea.get("title"),
                    idea.get("protagonist"),
                    idea.get("conflict"),
                    idea.get("twist"),
                    idea.get("payoff") or idea.get("resolution"),
                )
                if value not in (None, "", [], {})
            )
        )
    return "; ".join(fragment for fragment in fragments if fragment)


async def _generate_with_runtime_fallback(provider: LLMProvider, request: LLMRequest) -> LLMResult:
    try:
        provider_call = provider.generate_structured(request)
        return await asyncio.wait_for(provider_call, timeout=IDEA_PROVIDER_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        provider_name = getattr(provider, "provider_name", "Provider")
        raise RuntimeError(
            f"{provider_name} demorou mais de {IDEA_PROVIDER_TIMEOUT_SECONDS}s ao gerar ideias. "
            "Tente novamente ou escolha um modelo de texto mais estável."
        ) from exc
    except RuntimeError as exc:
        raise RuntimeError(
            f"Não foi possível gerar ideias com o modelo configurado. Detalhe do provedor: {exc}"
        ) from exc


def _normalize_generated_ideas(
    result: LLMResult,
    count: int,
    default_duration_minutes: float,
    primary_emotion: str = "",
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
            if primary_emotion.strip():
                raw_idea = dict(raw_idea)
                raw_idea["primary_emotion"] = primary_emotion.strip()
            idea = _normalize_idea(raw_idea, default_duration_minutes)
        except GenerationOutputError as exc:
            errors.append(str(exc))
            continue
        idea_errors = story_idea_validation_errors(idea)
        if idea_errors:
            errors.extend(f"generate_story_ideas.ideas[{index}]: {error}" for error in idea_errors)
            continue
        normalized.append(idea)
    if not normalized:
        errors.append(f"generate_story_ideas: esperado ao menos 1 ideia válida de {count}")
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
    with _idea_lab_lock:
        created_at = datetime.now(UTC).isoformat()
        normalized = [_normalize_idea(item, created_at=created_at) for item in ideas]
        _write_ideas(normalized, path)
        return normalized


def delete_generated_idea(idea_id: str, path: Path = GENERATED_IDEAS_PATH) -> None:
    with _idea_lab_lock:
        ideas = [item for item in load_generated_ideas(path) if item.get("id") != idea_id]
        _write_ideas(ideas, path)


def delete_all_ideas(
    saved_path: Path = SAVED_IDEAS_PATH,
    generated_path: Path = GENERATED_IDEAS_PATH,
) -> int:
    with _idea_lab_lock:
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
    return sorted(ideas, key=_idea_created_at_sort_key, reverse=True)


def save_idea(idea: dict[str, Any], path: Path = SAVED_IDEAS_PATH) -> dict[str, Any]:
    with _idea_lab_lock:
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
    with _idea_lab_lock:
        ideas = [item for item in load_saved_ideas(path) if item.get("id") != idea_id]
        _write_ideas(ideas, path)


def _normalize_idea(
    idea: dict[str, Any],
    default_duration_minutes: float = IDEA_LAB_DURATION_MINUTES,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_story_idea_payload(
        idea, default_duration_minutes=default_duration_minutes
    )
    normalized.setdefault("id", uuid.uuid4().hex)
    normalized.setdefault("created_at", created_at or datetime.now(UTC).isoformat())
    return normalized


def _idea_created_at_sort_key(idea: dict[str, Any]) -> str:
    return str(idea.get("created_at") or "")


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
