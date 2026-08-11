import re


class GenerationOutputError(RuntimeError):
    pass


def _required_mapping(payload: object, context: str) -> dict:
    if not isinstance(payload, dict):
        raise GenerationOutputError(f"{context}: expected JSON object")
    return payload


def _required_list(payload: dict, key: str, context: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise GenerationOutputError(f"{context}: missing non-empty list '{key}'")
    return value


def _required_str(payload: dict, key: str, context: str) -> str:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing field '{key}'")
    text = str(value).strip()
    if not text:
        raise GenerationOutputError(f"{context}: empty field '{key}'")
    return text


def _bounded_required_str(payload: dict, key: str, context: str, max_length: int) -> str:
    text = _required_str(payload, key, context)
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3].rstrip()}..."


def _story_idea_db_text(payload: dict, key: str, context: str, max_length: int = 220) -> str:
    return _bounded_required_str(payload, key, context, max_length)


def _shot_narration_text(payload: dict, context: str) -> str:
    narration = str(payload.get("narration_text") or "").strip()
    if narration:
        return narration
    dialogue = str(payload.get("dialogue_text") or "").strip()
    if dialogue:
        return dialogue
    return _required_str(payload, "action", context)


def _first_non_empty(payload: dict, *keys: str, fallback: object = "") -> object:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return fallback


def _required_int(payload: dict, key: str, context: str) -> int:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing integer field '{key}'")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationOutputError(f"{context}: invalid integer field '{key}'") from exc


def _coerce_score(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(round(value))))
    text = str(value).strip().lower()
    if not text:
        return default
    labels = {
        "baixo": 25,
        "baixa": 25,
        "low": 25,
        "medio": 50,
        "médio": 50,
        "media": 50,
        "média": 50,
        "medium": 50,
        "alto": 80,
        "alta": 80,
        "high": 80,
    }
    if text in labels:
        return labels[text]
    match = re.search(r"-?\d+(?:[,.]\d+)?", text)
    if match is None:
        return default
    number = float(match.group(0).replace(",", "."))
    if "/" in text and number <= 10:
        number *= 10
    return max(0, min(100, int(round(number))))


def coerce_duration_minutes(value: object, default: float = 5.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        duration = float(str(value).replace(",", "."))
    except ValueError:
        return default
    return max(2.0, min(25.0, duration))


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return max(1, default)
    try:
        number = int(float(str(value).replace(",", ".")))
    except ValueError:
        return max(1, default)
    return max(1, number)
