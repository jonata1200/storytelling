from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_openrouter_api_key(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip()
    if not key.startswith("sk-or-"):
        return None
    return key


class Settings(BaseSettings):
    app_name: str = "Storytelling"
    app_env: str = "local"
    app_debug: bool = True
    app_secret_key: str = Field(default="change-me-in-development", repr=False)

    api_basic_username: str = "admin"
    api_basic_password: str = Field(default="admin", repr=False)

    database_url: str = "postgresql+asyncpg://storytelling:storytelling@localhost:5432/storytelling"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    storage_backend: str = "local"
    local_storage_path: Path = Path("./storage")
    allow_user_registration: bool = False

    openrouter_api_key: str | None = Field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://127.0.0.1:8000"
    openrouter_app_title: str = "Storytelling"
    openrouter_default_model: str = "deepseek/deepseek-v4-flash"
    openrouter_image_model: str = "sourceful/riverflow-v2.5-pro"
    openrouter_video_model: str = "bytedance/seedance-2.0-fast"
    user_display_name: str = "Jonata"
    user_email: str = ""
    user_avatar_path: str = ""
    user_theme: str = "dark"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_insecure_non_local_defaults(self) -> "Settings":
        self.openrouter_api_key = normalize_openrouter_api_key(self.openrouter_api_key)
        if self.app_env.lower() not in {"local", "development", "test"}:
            if self.api_basic_username == "admin" and self.api_basic_password == "admin":
                raise ValueError("Default API credentials are forbidden outside local environments")
            if self.app_secret_key == "change-me-in-development":
                raise ValueError("APP_SECRET_KEY must be changed outside local environments")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false outside local environments")
        return self


@lru_cache
def get_settings() -> Settings:
    from app.config.runtime_preferences import load_runtime_preferences

    return Settings(**cast(dict[str, Any], load_runtime_preferences()))
