import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    SUPPORTED_IMAGE_PROVIDERS,
    SUPPORTED_TEXT_PROVIDERS,
    SUPPORTED_VIDEO_PROVIDERS,
)

# Limitação conhecida: as preferências são persistidas em .runtime/preferences.json
# (JSON em disco) com cache em memória (lru_cache + get_settings.cache_clear()).
# Isso é suficiente para uso local em processo único, mas NÃO sincroniza entre
# múltiplos processos/workers: uma instância não enxerga alterações feitas por outra.
# Se a aplicação evoluir para multi-processo, migrar este armazenamento para o banco.

PREFERENCE_KEYS = {
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "TEXT_PROVIDER_FALLBACKS",
    "IMAGE_PROVIDER",
    "VIDEO_PROVIDER",
    "META_INTEGRATION_MODE",
    "META_IMAGE_INTEGRATION_MODE",
    "META_API_KEY",
    "META_BASE_URL",
    "META_DEFAULT_MODEL",
    "META_IMAGE_MODEL",
    "META_IMAGE_ENDPOINT",
    "META_IMAGE_DOWNLOAD_HOSTS",
    "META_IMAGE_TIMEOUT_SECONDS",
    "META_BROWSER_PROFILE_PATH",
    "VIBES_INTEGRATION_MODE",
    "VIBES_API_KEY",
    "VIBES_BASE_URL",
    "VIBES_VIDEO_MODEL",
    "VIBES_BROWSER_PROFILE_PATH",
    "OLLAMA_CLOUD_BASE_URL",
    "OLLAMA_CLOUD_DEFAULT_MODEL",
    "OLLAMA_CLOUD_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_VIDEO_MODEL",
    "OPENROUTER_VIDEO_BASE_URL",
    "OPENROUTER_VIDEO_GENERATE_AUDIO",
    "VIDEO_GENERATION_CONCURRENCY",
    "USER_THEME",
    "APP_API_TOKEN",
}
PREFERENCES_PATH = Path(".runtime/preferences.json")
PREFERENCE_VALUE_MAX_LENGTH = 4096
_runtime_prefs_lock = threading.Lock()
logger = logging.getLogger(__name__)
PROVIDER_PREFERENCE_KEYS = {
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "IMAGE_PROVIDER",
    "VIDEO_PROVIDER",
}
PROVIDER_VALUES_BY_KEY = {
    "AI_PROVIDER": set(SUPPORTED_AI_PROVIDERS),
    "TEXT_PROVIDER": set(SUPPORTED_TEXT_PROVIDERS),
    "IMAGE_PROVIDER": set(SUPPORTED_IMAGE_PROVIDERS),
    "VIDEO_PROVIDER": set(SUPPORTED_VIDEO_PROVIDERS),
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
            and normalized_value.strip().casefold()
            not in PROVIDER_VALUES_BY_KEY[normalized_key]
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
        if any(ord(char) <= 0x1F or ord(char) == 0x7F for char in value):
            raise ValueError(f"Invalid control character in preference: {key}")
        if len(value) > PREFERENCE_VALUE_MAX_LENGTH:
            raise ValueError(
                f"Preference value too long for {key}: "
                f"{len(value)} > {PREFERENCE_VALUE_MAX_LENGTH}"
            )
        normalized[key] = value

    with _runtime_prefs_lock:
        existing = {key.upper(): value for key, value in load_runtime_preferences(path).items()}
        existing.update(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix="preferences-", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        handle = None
        try:
            try:
                handle = os.fdopen(descriptor, "w", encoding="utf-8")
            except OSError:
                # fdopen failed: close the raw descriptor to prevent fd leak.
                os.close(descriptor)
                raise
            with handle:
                json.dump(existing, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(path)
            # Arquivo com chaves de API: restringe permissões (mkstemp já usa 0600 no POSIX;
            # o chmod explícito cobre outros cenários/plataformas de forma defensiva).
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            logger.info("runtime_preferences_updated", extra={"keys": sorted(normalized)})
        finally:
            temporary_path.unlink(missing_ok=True)
