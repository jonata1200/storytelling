from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import normalize_api_key, normalize_provider_name

DEFAULT_APP_SECRET_KEY = "change-me-in-development"

LOCKED_OLLAMA_CLOUD_TEXT_MODEL = "mistral-large-3:675b-cloud"

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

    ai_provider: str = "ollama_cloud"
    text_provider: str | None = "ollama_cloud"
    text_provider_fallbacks: str = ""
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
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.ollama_cloud_api_key = normalize_api_key(self.ollama_cloud_api_key)
        self.ollama_cloud_default_model = normalize_ollama_cloud_text_model(
            self.ollama_cloud_default_model
        )
        self.openrouter_api_key = normalize_api_key(self.openrouter_api_key)
        self.ai_provider = normalize_provider_name(self.ai_provider, "AI_PROVIDER")
        self.text_provider = self._optional_provider(self.text_provider, "TEXT_PROVIDER")
        self.video_provider = self._optional_provider(self.video_provider, "VIDEO_PROVIDER")
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
    ) -> str | None:
        if not str(value or "").strip():
            return None
        return normalize_provider_name(value, field_name)


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
