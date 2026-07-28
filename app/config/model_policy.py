MOCK_MODEL_IDS = {
    "mock",
    "mock-llm",
    "mock-image",
    "mock-video",
    "mock-speech",
}


def normalize_model_name(value: object, field_name: str = "modelo") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} não pode ficar vazio")
    if len(text) > 220:
        raise ValueError(f"{field_name} deve ter no maximo 220 caracteres")
    return text


def is_openrouter_free_model(model: object) -> bool:
    return ":free" in str(model or "").casefold()


def is_mock_model(model: object) -> bool:
    text = str(model or "").strip().casefold()
    return text in MOCK_MODEL_IDS or text.startswith("mock-")


def validate_openrouter_model_name(value: object, field_name: str = "modelo") -> str:
    model = normalize_model_name(value, field_name)
    if is_openrouter_free_model(model):
        raise ValueError(
            "Modelos free da OpenRouter (:free) estão bloqueados. "
            "Escolha um modelo pago/estável para evitar travamentos."
        )
    if is_mock_model(model):
        raise ValueError(
            "Modelos mock estão bloqueados no fluxo da aplicação. "
            "Configure um modelo real da OpenRouter."
        )
    return model


def ensure_openrouter_api_key(api_key: str | None) -> str:
    key = str(api_key or "").strip()
    if not key:
        raise ValueError(
            "OPENROUTER_API_KEY não configurada. Configure uma chave válida para usar IA real."
        )
    return key
