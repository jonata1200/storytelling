import re
from collections.abc import Mapping
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|token|secret|password|bearer)\s*[:=]\s*([^\s,;]+)"
)
LEGACY_ROUTER_KEY_PATTERN = re.compile(r"sk-or-[A-Za-z0-9_\-]+")
OPENAI_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+([^\s,;]+)")


def redact_secrets(value: object) -> str:
    text = str(value)
    text = LEGACY_ROUTER_KEY_PATTERN.sub("[REDACTED]", text)
    text = OPENAI_KEY_PATTERN.sub("[REDACTED]", text)
    text = BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", text)
    return SECRET_KEY_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, raw_value in value.items():
        normalized_key = str(key).lower()
        if any(
            marker in normalized_key
            for marker in ("key", "token", "secret", "password", "cookie", "csrf", "session")
        ):
            redacted[str(key)] = "[REDACTED]"
        elif isinstance(raw_value, Mapping):
            redacted[str(key)] = redact_mapping(raw_value)
        elif isinstance(raw_value, str):
            redacted[str(key)] = redact_secrets(raw_value)
        else:
            redacted[str(key)] = raw_value
    return redacted
