from app.config.runtime_preferences import save_runtime_preferences
from app.config.settings import get_settings


def save_preferences(values: dict[str, str]) -> None:
    save_runtime_preferences(values)
    get_settings.cache_clear()
