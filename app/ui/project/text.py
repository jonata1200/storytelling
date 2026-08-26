from typing import Any

from app.storytelling.service import coerce_duration_minutes
from app.ui.shared.page_config import clean_idea_title


def compact_project_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    cleaned = " ".join((first_line or text).strip().split())
    if not cleaned:
        return "Novo projeto Storytelling"
    common_prefixes = [
        "quero criar uma historia sobre ",
        "quero criar uma história sobre ",
        "quero desenvolver uma historia sobre ",
        "quero desenvolver uma história sobre ",
        "crie uma historia sobre ",
        "crie uma história sobre ",
        "uma historia sobre ",
        "uma história sobre ",
    ]
    lower_cleaned = cleaned.lower()
    for prefix in common_prefixes:
        if lower_cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip(" ,;:-")
            if cleaned:
                cleaned = cleaned[:1].upper() + cleaned[1:]
            break
    first_sentence = cleaned
    for separator in [".", "!", "?"]:
        if separator in first_sentence:
            first_sentence = first_sentence.split(separator, 1)[0].strip()
            break
    words = first_sentence.split()
    if len(words) > 9:
        first_sentence = " ".join(words[:9])
    return first_sentence[:80].strip(" ,;:-") or "Novo projeto Storytelling"


def format_idea_payload_for_project(idea: dict[str, Any]) -> str:
    labels = {
        "title": "Título",
        "theme": "Tema",
        "genre": "Gênero",
        "primary_emotion": "Emoção principal",
        "final_emotion": "Emoção final",
        "hook": "Gancho",
        "premise": "Premissa",
        "protagonist": "Protagonista",
        "protagonist_desire": "Desejo do protagonista",
        "emotional_need": "Necessidade emocional",
        "conflict": "Conflito",
        "obstacles": "Obstáculos",
        "stakes": "Riscos narrativos",
        "twist": "Virada",
        "climax": "Clímax",
        "resolution": "Resolução",
        "duration_minutes": "Duração",
        "retention_potential": "Potencial de retenção",
        "cliche_risk": "Risco de clichê",
        "production_complexity": "Complexidade de produção",
    }
    ordered_keys = [key for key in labels if key in idea]
    ordered_keys.extend(key for key in idea if key not in labels and not key.startswith("_"))
    lines: list[str] = []
    for key in ordered_keys:
        value = idea.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value_text = ", ".join(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            value_text = "; ".join(
                f"{item_key}: {item_value}" for item_key, item_value in value.items()
            )
        else:
            value_text = str(value)
        if key == "title":
            value_text = clean_idea_title(value_text)
        if key == "duration_minutes":
            value_text = f"{coerce_duration_minutes(value):g} minutos"
        lines.append(f"{labels.get(key, key)}: {value_text}")
    return "\n".join(lines)
