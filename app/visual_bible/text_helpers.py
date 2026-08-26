"""Helpers de texto compartilhados entre os módulos de perfil visual.

Extraído de ``profiles.py`` para quebrar o ciclo estrutural de import
(INC-05): ``character_profiles.py`` passou a consumir estes helpers daqui,
e ``profiles.py`` reexporta os nomes originais para compatibilidade.
"""

import re
import unicodedata


def _prompt_text(value: object) -> str:
    if isinstance(value, dict):
        parts = [
            f"{_humanize_identifier(key).lower()}: {_prompt_text(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_prompt_text(item) for item in value if item not in (None, "", [], {}))
    return str(value or "").strip()


def _humanize_identifier(value: object) -> str:
    text = str(value or "").strip().strip("_-")
    if not text:
        return "Item"
    prefixes = ("char_", "loc_", "prop_", "personagem_", "local_", "objeto_")
    lower_text = text.lower()
    for prefix in prefixes:
        if lower_text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return " ".join(part for part in text.replace("-", "_").split("_") if part).title() or "Item"


def _clean_prompt_fragment(value: object, prefixes: tuple[str, ...]) -> str:
    text = _prompt_text(value).strip()
    if not text:
        return ""
    for prefix in prefixes:
        clean_prefix = re.escape(prefix.strip())
        if not clean_prefix:
            continue
        stripped = re.sub(
            rf"^{clean_prefix}\b[\s:,\-]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        if stripped != text:
            return stripped
        if re.fullmatch(clean_prefix, text, flags=re.IGNORECASE):
            return ""
    return text


def _short_text(value: object, fallback: str, max_length: int) -> str:
    text = str(value or fallback).strip() or fallback
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3].rstrip()}..."


def _first_value(raw: dict, *keys: str, fallback: object = "") -> object:
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return fallback


def _ascii_lower(value: object) -> str:
    text = _prompt_text(value)
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _profile_mapping(raw: object, fallback_name: str | None = None) -> dict:
    if isinstance(raw, dict):
        normalized = dict(raw)
        if not normalized.get("name"):
            identifier_name = (
                _humanize_identifier(normalized.get("id")) if normalized.get("id") else ""
            )
            role_name = _role_display_name(
                _first_value(normalized, "role", "funcao", "função", fallback="")
            )
            normalized["name"] = (
                normalized.get("nome")
                or normalized.get("title")
                or normalized.get("titulo")
                or fallback_name
                or identifier_name
                or role_name
                or "Item"
            )
        return normalized
    text = str(raw or "").strip()
    return {"name": text or "Item", "description": text}


def _role_display_name(value: object) -> str:
    text = _prompt_text(value)
    text = re.split(r"\s*\(", text, maxsplit=1)[0]
    text = re.sub(
        r"\b(?:coadjuvante|co-protagonista|coprotagonista|protagonista|principal|secundario|secundaria|apoio)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text.title()