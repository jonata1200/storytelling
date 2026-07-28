from app.config.provider_policy import (
    MOCK_MODEL_IDS,
    ensure_provider_api_key,
    is_free_model,
    is_mock_model,
    normalize_model_name,
    validate_model_name,
)

__all__ = [
    "MOCK_MODEL_IDS",
    "ensure_openrouter_api_key",
    "ensure_provider_api_key",
    "is_mock_model",
    "is_openrouter_free_model",
    "normalize_model_name",
    "validate_model_name",
    "validate_openrouter_model_name",
]


def is_openrouter_free_model(model: object) -> bool:
    return is_free_model(model)


def validate_openrouter_model_name(value: object, field_name: str = "modelo") -> str:
    return validate_model_name(value, field_name, provider="openrouter")


def ensure_openrouter_api_key(api_key: str | None) -> str:
    return ensure_provider_api_key(api_key, "openrouter", "OPENROUTER_API_KEY")
