import re
from collections.abc import Iterable
from typing import Any

from app.config.provider_policy import (
    SUPPORTED_AI_PROVIDERS,
    ProviderChannel,
    effective_provider_for_channel,
    provider_api_key,
    provider_display_name,
    provider_requires_api_key,
)
from app.config.settings import get_settings

CreationChannel = ProviderChannel | str

_VALID_PROVIDER_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

TEXT_CREATION_STEPS = {
    "ideas",
    "generate_ideas",
    "initial_script",
    "script",
    "generate_script",
    "revise_script",
    "scenes",
    "generate_scenes",
    "generate_scenes_and_shots",
    "visual",
    "generate_assets",
    "storyboard_prompts",
    "generate_storyboard_prompts",
    "director_agent_chat",
}
VIDEO_CREATION_STEPS = {"video", "generate_video", "video_clips", "continuous_video"}


def api_key_variable_name(provider: str) -> str:
    normalized = str(provider or "").strip().casefold()
    if not _VALID_PROVIDER_IDENTIFIER.match(normalized):
        raise ValueError(f"Nome de provider invalido para variavel de env: {provider!r}")
    return {
        "ollama_cloud": "OLLAMA_CLOUD_API_KEY",
    }.get(normalized, f"{normalized.upper()}_API_KEY")


def provider_for_creation_channel(settings: Any, channel: CreationChannel) -> str:
    if channel in {"text", "image", "video"}:
        return effective_provider_for_channel(settings, channel)
    normalized = str(channel or "").strip().casefold()
    if normalized not in SUPPORTED_AI_PROVIDERS:
        raise ValueError(
            f"Canal/provider desconhecido: {channel or '(vazio)'}. "
            f"Use: {', '.join(SUPPORTED_AI_PROVIDERS)}"
        )
    return normalized


def current_settings_for_api_key_validation() -> Any:
    get_settings.cache_clear()
    return get_settings()


def required_channels_for_creation_step(step: str) -> tuple[CreationChannel, ...]:
    normalized = str(step or "").strip().casefold()
    channels: list[CreationChannel] = []
    if normalized in TEXT_CREATION_STEPS:
        channels.append("text")
    if normalized in {
        "visual",
        "generate_assets",
        "storyboard_prompts",
        "generate_storyboard_prompts",
    }:
        channels.append("image")
    if normalized in VIDEO_CREATION_STEPS:
        channels.append("video")
    return tuple(channels)


def missing_api_key_messages_for_channels(
    channels: Iterable[CreationChannel],
    settings: Any | None = None,
) -> list[str]:
    app_settings = settings or current_settings_for_api_key_validation()
    messages: list[str] = []
    seen_providers: set[str] = set()
    for channel in channels:
        provider = provider_for_creation_channel(app_settings, channel)
        if not provider or provider in seen_providers:
            continue
        seen_providers.add(provider)
        if provider_requires_api_key(app_settings, provider) and not provider_api_key(
            app_settings, provider
        ):
            variable = api_key_variable_name(provider)
            messages.append(
                f"{variable} não está configurada para {provider_display_name(provider)}."
            )
    return messages


def missing_api_key_messages_for_creation_step(
    step: str,
    settings: Any | None = None,
) -> list[str]:
    return missing_api_key_messages_for_channels(
        required_channels_for_creation_step(step),
        settings,
    )


def format_missing_api_key_message(messages: Iterable[str]) -> str:
    items = [message.strip() for message in messages if message.strip()]
    if not items:
        return ""
    joined = "\n".join(f"- {item}" for item in items)
    return (
        "Antes de iniciar esta etapa, registre as chaves de API necessárias nas "
        "Configurações de IA.\n\n"
        f"{joined}"
    )


def require_api_keys_for_creation_step(step: str, settings: Any | None = None) -> None:
    messages = missing_api_key_messages_for_creation_step(step, settings)
    if messages:
        raise ValueError(format_missing_api_key_message(messages))


def require_api_keys_for_channels(
    channels: Iterable[CreationChannel],
    settings: Any | None = None,
) -> None:
    messages = missing_api_key_messages_for_channels(channels, settings)
    if messages:
        raise ValueError(format_missing_api_key_message(messages))
