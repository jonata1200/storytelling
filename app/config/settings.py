from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import (
    SUPPORTED_IMAGE_PROVIDERS,
    SUPPORTED_TEXT_PROVIDERS,
    SUPPORTED_VIDEO_PROVIDERS,
    normalize_api_key,
    normalize_provider_name,
)

DEFAULT_APP_SECRET_KEY = "change-me-in-development"

LOCKED_OLLAMA_CLOUD_TEXT_MODEL = "mistral-large-3:675b-cloud"
DEFAULT_META_TEXT_MODEL = "muse-spark-1.2"

OLLAMA_CLOUD_TEXT_MODELS = (
    "deepseek-v4-flash:0731-cloud",
    "gemma4:31b-cloud",
    "gpt-oss:120b-cloud",
    "minimax-m2.7:cloud",
    "mistral-large-3:675b-cloud",
    "nemotron-3-nano:30b-cloud",
    "nemotron-3-super:cloud",
    "qwen3.5:397b-cloud",
)

class Settings(BaseSettings):
    app_name: str = "Storytelling"
    app_env: str = "local"
    app_debug: bool = True
    app_secret_key: str = Field(default=DEFAULT_APP_SECRET_KEY, repr=False)
    app_api_token: str = Field(default="", repr=False)

    database_url: str = Field(default="", repr=False)
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    max_generated_asset_bytes: int = 750 * 1024 * 1024

    ai_provider: str = "meta"
    text_provider: str | None = "meta"
    text_provider_fallbacks: str = "ollama_cloud"
    image_provider: str | None = "meta"
    meta_integration_mode: str = "api"
    meta_image_integration_mode: str = "api"
    meta_api_key: str | None = Field(default=None, repr=False)
    meta_base_url: str = ""
    meta_default_model: str = DEFAULT_META_TEXT_MODEL
    meta_image_model: str = "muse-image"
    meta_image_endpoint: str = ""
    meta_image_download_hosts: str = ""
    meta_image_timeout_seconds: float = Field(default=180, ge=15, le=600)
    meta_browser_profile_path: Path = Path("./runtime/browser_profiles/meta")
    ollama_cloud_api_key: str | None = Field(default=None, repr=False)
    ollama_cloud_base_url: str = "https://ollama.com/api"
    ollama_cloud_default_model: str = LOCKED_OLLAMA_CLOUD_TEXT_MODEL
    ffmpeg_path: str = ""
    video_generation_concurrency: int = Field(default=2, ge=1, le=4)
    video_provider: str | None = "openrouter"
    openrouter_api_key: str | None = Field(default=None, repr=False)
    openrouter_video_model: str = "bytedance/seedance-2.0-mini"
    openrouter_video_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_video_generate_audio: bool = True
    vibes_integration_mode: str = "browser"
    vibes_api_key: str | None = Field(default=None, repr=False)
    vibes_base_url: str = ""
    vibes_video_model: str = ""
    vibes_browser_profile_path: Path = Path("./runtime/browser_profiles/vibes")
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.ollama_cloud_api_key = normalize_api_key(self.ollama_cloud_api_key)
        self.ollama_cloud_default_model = normalize_ollama_cloud_text_model(
            self.ollama_cloud_default_model
        )
        self.openrouter_api_key = normalize_api_key(self.openrouter_api_key)
        self.meta_api_key = normalize_api_key(self.meta_api_key)
        self.vibes_api_key = normalize_api_key(self.vibes_api_key)
        self.ai_provider = normalize_provider_name(self.ai_provider, "AI_PROVIDER")
        self.text_provider = self._optional_provider(
            self.text_provider, "TEXT_PROVIDER", SUPPORTED_TEXT_PROVIDERS
        )
        self.image_provider = self._optional_provider(
            self.image_provider, "IMAGE_PROVIDER", SUPPORTED_IMAGE_PROVIDERS
        )
        self.video_provider = self._optional_provider(
            self.video_provider, "VIDEO_PROVIDER", SUPPORTED_VIDEO_PROVIDERS
        )
        self.meta_integration_mode = self._integration_mode(
            self.meta_integration_mode, "META_INTEGRATION_MODE"
        )
        self.meta_image_integration_mode = self._integration_mode(
            self.meta_image_integration_mode, "META_IMAGE_INTEGRATION_MODE"
        )
        self.vibes_integration_mode = self._integration_mode(
            self.vibes_integration_mode, "VIBES_INTEGRATION_MODE"
        )
        self.meta_browser_profile_path = self._browser_profile_path(
            self.meta_browser_profile_path, "META_BROWSER_PROFILE_PATH"
        )
        self.vibes_browser_profile_path = self._browser_profile_path(
            self.vibes_browser_profile_path, "VIBES_BROWSER_PROFILE_PATH"
        )
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.app_secret_key == DEFAULT_APP_SECRET_KEY:
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
            if not self.database_url.strip():
                raise ValueError("DATABASE_URL must be set outside local environments")
        else:
            if self.app_secret_key == DEFAULT_APP_SECRET_KEY:
                import logging

                logging.getLogger(__name__).warning(
                    "APP_SECRET_KEY ainda usa o valor padrao de desenvolvimento. "
                    "Qualquer pessoa com acesso ao repositorio pode forjar tokens "
                    "de sessao e CSRF. Defina um segredo proprio antes de expor a aplicacao."
                )
        if not self.database_url.strip():
            self.database_url = (
                "postgresql+asyncpg://storytelling:storytelling@localhost:5433/storytelling"
            )
        return self

    @staticmethod
    def _optional_provider(
        value: str | None,
        field_name: str,
        allowed: tuple[str, ...],
    ) -> str | None:
        if not str(value or "").strip():
            return None
        return normalize_provider_name(value, field_name, allowed)

    @staticmethod
    def _integration_mode(value: object, field_name: str) -> str:
        mode = str(value or "").strip().casefold()
        if mode not in {"api", "browser"}:
            raise ValueError(f"{field_name} inválido: {mode or '(vazio)'}. Use: api, browser")
        return mode

    @staticmethod
    def _browser_profile_path(value: Path, field_name: str) -> Path:
        root = (Path.cwd() / "runtime" / "browser_profiles").resolve()
        resolved = value.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} deve ficar dentro de {root}. Recebido: {value}"
            ) from exc
        return resolved


def normalize_ollama_cloud_text_model(value: object) -> str:
    model = str(value or "").strip()
    if model in OLLAMA_CLOUD_TEXT_MODELS:
        return model
    import logging

    logging.getLogger(__name__).warning(
        "ollama_cloud_text_model_invalid received=%r default=%s",
        value,
        LOCKED_OLLAMA_CLOUD_TEXT_MODEL,
    )
    return LOCKED_OLLAMA_CLOUD_TEXT_MODEL


@lru_cache
def get_settings() -> Settings:
    from app.config.runtime_preferences import load_runtime_preferences

    return Settings(**cast(dict[str, Any], load_runtime_preferences()))


def insecure_default_secret_key_warning() -> str | None:
    settings = get_settings()
    if settings.app_secret_key != DEFAULT_APP_SECRET_KEY:
        return None
    return (
        "APP_SECRET_KEY ainda usa o valor padrão de desenvolvimento. Qualquer pessoa com "
        "acesso ao repositório pode forjar tokens de sessão e CSRF. Defina um segredo "
        "próprio antes de expor a aplicação."
    )
