import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.config.provider_policy import SUPPORTED_AI_PROVIDERS

PREFERENCE_KEYS = {
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "TEXT_PROVIDER_FALLBACKS",
    "IMAGE_PROVIDER",
    "VIDEO_PROVIDER",
    "OLLAMA_CLOUD_BASE_URL",
    "OLLAMA_CLOUD_DEFAULT_MODEL",
    "OLLAMA_CLOUD_API_KEY",
    "GOOGLE_AI_API_KEY",
    "GOOGLE_AI_BASE_URL",
    "GOOGLE_AI_IMAGE_MODEL",
    "GOOGLE_AI_IMAGE_SIZE",
    "GOOGLE_AI_VIDEO_MODEL",
    "GOOGLE_AI_VIDEO_FAST_MODEL",
    "GOOGLE_AI_VIDEO_DEFAULT_DURATION_SECONDS",
    "GOOGLE_AI_VIDEO_POLL_INTERVAL_SECONDS",
    "GOOGLE_AI_VIDEO_POLL_TIMEOUT_SECONDS",
    "SPEECH_PROVIDER",
    "SPEECH_TIMEOUT_SECONDS",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_BASE_URL",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_SPEECH_MODEL",
    "ELEVENLABS_OUTPUT_FORMAT",
    "DUBBING_PROVIDER",
    "DUBBING_SOURCE_LANG",
    "DUBBING_TARGET_LANG",
    "DUBBING_POLL_INTERVAL_SECONDS",
    "DUBBING_POLL_TIMEOUT_SECONDS",
    "VIDEO_GENERATION_CONCURRENCY",
    "USER_DISPLAY_NAME",
    "USER_EMAIL",
    "USER_AVATAR_PATH",
    "USER_THEME",
}
PREFERENCES_PATH = Path(".runtime/preferences.json")
logger = logging.getLogger(__name__)
PROVIDER_PREFERENCE_KEYS = {
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "IMAGE_PROVIDER",
    "VIDEO_PROVIDER",
    "SPEECH_PROVIDER",
    "DUBBING_PROVIDER",
}
ALLOWED_PROVIDER_PREFERENCE_VALUES = {
    *SUPPORTED_AI_PROVIDERS,
    "elevenlabs",
}


def load_runtime_preferences(path: Path = PREFERENCES_PATH) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    preferences: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = str(key).upper()
        if normalized_key not in PREFERENCE_KEYS:
            continue
        normalized_value = str(value)
        if (
            normalized_key in PROVIDER_PREFERENCE_KEYS
            and normalized_value.strip().casefold() not in ALLOWED_PROVIDER_PREFERENCE_VALUES
        ):
            continue
        preferences[normalized_key.lower()] = normalized_value
    return preferences


def save_runtime_preferences(values: dict[str, str], path: Path = PREFERENCES_PATH) -> None:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = raw_key.upper()
        if key not in PREFERENCE_KEYS:
            raise ValueError(f"Preference is not allowed: {key}")
        value = str(raw_value)
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError(f"Invalid control character in preference: {key}")
        normalized[key] = value

    existing = {key.upper(): value for key, value in load_runtime_preferences(path).items()}
    existing.update(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix="preferences-", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
        logger.info("runtime_preferences_updated", extra={"keys": sorted(normalized)})
    finally:
        temporary_path.unlink(missing_ok=True)
