import re

from app.storytelling.normalization_common import (
    GenerationOutputError,
    _coerce_score,
    _required_list,
    _required_mapping,
    _required_str,
    coerce_duration_minutes,
)

STORY_IDEA_REQUIRED_TEXT_FIELDS = (
    "title",
    "genre",
    "primary_emotion",
    "hook",
    "premise",
    "protagonist",
    "conflict",
    "twist",
    "payoff",
    "resolution",
)


def normalize_story_idea_payload(payload: dict, default_duration_minutes: float = 5.0) -> dict:
    normalized = dict(payload)
    title = _required_str(normalized, "title", "story_idea")
    normalized.setdefault("genre", "Drama")
    normalized.setdefault("primary_emotion", normalized.get("final_emotion") or "Curiosidade")
    normalized.setdefault("hook", normalized.get("premise") or title)
    normalized.setdefault("premise", normalized.get("hook") or title)
    normalized.setdefault("protagonist", "Protagonista a definir")
    if normalized.get("payoff") in (None, "", [], {}) and normalized.get("resolution") not in (
        None,
        "",
        [],
        {},
    ):
        normalized["payoff"] = normalized["resolution"]
    if normalized.get("resolution") in (None, "", [], {}) and normalized.get("payoff") not in (
        None,
        "",
        [],
        {},
    ):
        normalized["resolution"] = normalized["payoff"]
    normalized["duration_minutes"] = coerce_duration_minutes(
        normalized.get("duration_minutes"), default_duration_minutes
    )
    normalized["retention_potential"] = _coerce_score(normalized.get("retention_potential"), 75)
    normalized["cliche_risk"] = _coerce_score(normalized.get("cliche_risk"), 25)
    normalized["production_complexity"] = _coerce_score(normalized.get("production_complexity"), 35)
    normalized["title"] = title
    return normalized


def story_idea_validation_errors(payload: dict) -> list[str]:
    errors: list[str] = []
    for field in STORY_IDEA_REQUIRED_TEXT_FIELDS:
        if not str(payload.get(field) or "").strip():
            errors.append(f"campo obrigatório vazio: {field}")

    protagonist = str(payload.get("protagonist") or "").strip().casefold()
    if protagonist in {"protagonista", "protagonista a definir", "personagem a definir"}:
        errors.append("protagonist precisa ser específico, não placeholder")

    duration = coerce_duration_minutes(payload.get("duration_minutes"))
    if not 2 <= duration <= 25:
        errors.append("duration_minutes deve ficar entre 2 e 25")

    for field in ("retention_potential", "cliche_risk", "production_complexity"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            errors.append(f"{field} deve ser inteiro entre 0 e 100")

    obstacles = payload.get("obstacles")
    if obstacles is not None and (
        not isinstance(obstacles, list) or not any(str(item).strip() for item in obstacles)
    ):
        errors.append("obstacles deve ser uma lista não vazia quando informado")

    if payload.get("hook") == payload.get("premise"):
        errors.append("hook e premise precisam ter funcoes narrativas diferentes")

    return errors


def _idea_similarity_key(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9áéíóúâêôãõç]+", " ", text)
    stopwords = {
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "que",
        "e",
        "ou",
        "sua",
        "seu",
        "suas",
        "seus",
        "ela",
        "ele",
        "precisa",
        "descobre",
        "encontra",
    }
    tokens = [token for token in text.split() if token and token not in stopwords]
    return " ".join(tokens[:16])


def _idea_protagonist_identity(value: object) -> str:
    text = str(value or "").casefold()
    text = re.split(r"[,;(\n]", text, maxsplit=1)[0]
    return _idea_similarity_key(text)


def story_idea_diversity_errors(items: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    fields = (
        ("protagonist", "protagonista"),
        ("conflict", "conflito"),
        ("twist", "virada"),
        ("payoff", "payoff"),
        ("resolution", "resolucao"),
    )
    for index, item in enumerate(items, 1):
        for field, label in fields:
            key_text = (
                _idea_protagonist_identity(item.get(field))
                if field == "protagonist"
                else _idea_similarity_key(item.get(field))
            )
            if not key_text:
                continue
            key = (field, key_text)
            previous = seen.get(key)
            if previous is not None:
                errors.append(f"ideias {previous} e {index} repetem {label}: {item.get(field)}")
            else:
                seen[key] = index

    generic_patterns = (
        "mensagem que muda tudo",
        "verdade chega tarde demais",
        "péssoa comum precisa encarar uma revelacao",
        "segredo do passado",
        "heranca misteriosa",
        "carta azul",
        "casa da familia",
    )
    for index, item in enumerate(items, 1):
        combined = " ".join(str(item.get(field) or "") for field, _ in fields).casefold()
        for pattern in generic_patterns:
            if pattern in combined:
                errors.append(f"ideia {index} usa motor narrativo generico: {pattern}")
    return errors


def _story_idea_retry_guidance(errors: list[str]) -> str:
    return (
        "A resposta anterior não serve para o pipeline. Corrija estes pontos e retorne "
        "novamente somente JSON, mantendo exatamente a chave ideas: "
        f"{'; '.join(errors)}. "
    )


def _normalize_generated_story_ideas(content: dict, default_duration_minutes: float) -> list[dict]:
    items: list[dict] = []
    errors: list[str] = []
    raw_ideas = _required_list(content, "ideas", "generate_story_ideas")
    for index, raw_item in enumerate(raw_ideas, 1):
        context = f"generate_story_ideas.ideas[{index}]"
        try:
            item = normalize_story_idea_payload(
                _required_mapping(raw_item, context),
                default_duration_minutes=default_duration_minutes,
            )
        except GenerationOutputError as exc:
            errors.append(str(exc))
            continue
        item_errors = story_idea_validation_errors(item)
        if item_errors:
            errors.extend(f"{context}: {error}" for error in item_errors)
            continue
        items.append(item)
    if not items:
        errors.append("generate_story_ideas: esperado pelo menos 1 ideia válida")
    if not errors and len(items) > 1:
        errors.extend(story_idea_diversity_errors(items))
    if errors:
        raise GenerationOutputError("; ".join(errors))
    return items
