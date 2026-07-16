from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Storytelling Studio"
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
