from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.provider_policy import normalize_api_key, normalize_provider_name


def normalize_openrouter_api_key(value: str | None) -> str | None:
    return normalize_api_key(value, "openrouter")


def normalize_omniroute_api_key(value: str | None) -> str | None:
    return normalize_api_key(value, "omniroute")


class Settings(BaseSettings):
    app_name: str = "Storytelling"
    app_env: str = "local"
    app_debug: bool = True
    app_secret_key: str = Field(default="change-me-in-development", repr=False)

    database_url: str = "postgresql+asyncpg://storytelling:storytelling@localhost:5432/storytelling"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    max_upload_bytes: int = 25 * 1024 * 1024
    max_generated_asset_bytes: int = 750 * 1024 * 1024
    allow_user_registration: bool = True
    single_user_mode: bool = True

    openrouter_api_key: str | None = Field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://127.0.0.1:8000"
    openrouter_app_title: str = "Storytelling"
    openrouter_default_model: str = "deepseek/deepseek-v4-flash"
    openrouter_image_model: str = "sourceful/riverflow-v2-fast"
    openrouter_video_model: str = "bytedance/seedance-2.0-fast"
    openrouter_image_timeout_seconds: int = 360
    omniroute_api_key: str | None = Field(default=None, repr=False)
    omniroute_base_url: str = "https://omnirouters.com/v1"
    omniroute_default_model: str = "deepseek/deepseek-v4-flash"
    omniroute_image_model: str = "sourceful/riverflow-v2-fast"
    omniroute_video_model: str = "bytedance/seedance-2.0-fast"
    omniroute_speech_model: str = ""
    omniroute_image_timeout_seconds: int = 360
    ai_provider: str = "omniroute"
    text_provider: str | None = None
    image_provider: str | None = None
    video_provider: str | None = None
    storyboard_image_concurrency: int = 3
    speech_provider: str = "openai_compatible"
    speech_base_url: str = "https://api.openai.com/v1"
    speech_api_key: str | None = Field(default=None, repr=False)
    speech_model: str = ""
    speech_voice: str = "alloy"
    speech_timeout_seconds: int = 120
    user_display_name: str = "Jonata"
    user_email: str = ""
    user_avatar_path: str = ""
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.openrouter_api_key = normalize_openrouter_api_key(self.openrouter_api_key)
        self.omniroute_api_key = normalize_omniroute_api_key(self.omniroute_api_key)
        self.ai_provider = normalize_provider_name(self.ai_provider, "AI_PROVIDER")
        self.text_provider = self._optional_provider(self.text_provider, "TEXT_PROVIDER")
        self.image_provider = self._optional_provider(self.image_provider, "IMAGE_PROVIDER")
        self.video_provider = self._optional_provider(self.video_provider, "VIDEO_PROVIDER")
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.app_secret_key == "change-me-in-development":
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
        return self

    @staticmethod
    def _optional_provider(value: str | None, field_name: str) -> str | None:
        if not str(value or "").strip():
            return None
        return normalize_provider_name(value, field_name)


@lru_cache
def get_settings() -> Settings:
    from app.config.runtime_preferences import load_runtime_preferences

    return Settings(**cast(dict[str, Any], load_runtime_preferences()))
