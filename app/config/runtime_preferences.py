import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

PREFERENCE_KEYS = {
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "IMAGE_PROVIDER",
    "VIDEO_PROVIDER",
    "OMNIROUTE_BASE_URL",
    "OMNIROUTE_DEFAULT_MODEL",
    "OMNIROUTE_IMAGE_MODEL",
    "OMNIROUTE_VIDEO_MODEL",
    "OMNIROUTE_VIDEO_SUBMIT_TIMEOUT_SECONDS",
    "OMNIROUTE_VIDEO_POLL_INTERVAL_SECONDS",
    "OMNIROUTE_VIDEO_POLL_TIMEOUT_SECONDS",
    "OMNIROUTE_VIDEO_DOWNLOAD_TIMEOUT_SECONDS",
    "OMNIROUTE_SPEECH_MODEL",
    "OPENCODE_BASE_URL",
    "OPENCODE_DEFAULT_MODEL",
    "VIDEO_GENERATION_CONCURRENCY",
    "USER_DISPLAY_NAME",
    "USER_EMAIL",
    "USER_AVATAR_PATH",
    "USER_THEME",
}
SECRET_PREFERENCE_KEYS = {
    "OMNIROUTE_API_KEY",
    "OPENCODE_API_KEY",
    "SPEECH_API_KEY",
}
PREFERENCES_PATH = Path(".runtime/preferences.json")
logger = logging.getLogger(__name__)


def load_runtime_preferences(path: Path = PREFERENCES_PATH) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key).lower(): str(value)
        for key, value in payload.items()
        if str(key).upper() in PREFERENCE_KEYS
    }


def save_runtime_preferences(values: dict[str, str], path: Path = PREFERENCES_PATH) -> None:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = raw_key.upper()
        if key in SECRET_PREFERENCE_KEYS:
            raise ValueError(f"Secret preference must be configured via environment: {key}")
        if key not in PREFERENCE_KEYS:
            raise ValueError(f"Preference is not allowed: {key}")
        value = str(raw_value)
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError(f"Invalid control character in preference: {key}")
        normalized[key] = value

    existing = {key.upper(): value for key, value in load_runtime_preferences(path).items()}
    existing = {key: value for key, value in existing.items() if key not in SECRET_PREFERENCE_KEYS}
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
