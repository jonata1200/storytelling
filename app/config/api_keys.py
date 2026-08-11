from collections.abc import Iterable
from typing import Any

from app.config.provider_policy import (
    ProviderChannel,
    effective_provider_for_channel,
    provider_api_key,
    provider_display_name,
    provider_requires_api_key,
)
from app.config.settings import get_settings

CreationChannel = ProviderChannel | str

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
    "generate_visual_bible",
    "storyboard_prompts",
    "generate_storyboard_prompts",
    "director_agent_chat",
}
IMAGE_CREATION_STEPS = {
    "approve_visual_prompt",
    "visual_images",
    "visual_references",
    "approve_visual_prompt_with_generation",
    "approve_storyboard_prompt",
    "storyboard",
    "generate_storyboard",
    "storyboard_frames",
}
VIDEO_CREATION_STEPS = {"video", "generate_video", "video_clips", "continuous_video"}
ELEVENLABS_CREATION_STEPS = {
    "speech",
    "finalization",
    "dubbing",
    "generate_dubbing",
}


def api_key_variable_name(provider: str) -> str:
    return {
        "ollama_cloud": "OLLAMA_CLOUD_API_KEY",
        "google_ai": "GOOGLE_AI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
    }.get(provider, f"{provider.upper()}_API_KEY")


def provider_for_creation_channel(settings: Any, channel: CreationChannel) -> str:
    if channel in {"text", "image", "video"}:
        return effective_provider_for_channel(settings, channel)
    if channel == "speech":
        return str(getattr(settings, "speech_provider", "") or "elevenlabs").strip().casefold()
    if channel == "dubbing":
        return str(getattr(settings, "dubbing_provider", "") or "elevenlabs").strip().casefold()
    return str(channel or "").strip().casefold()


def current_settings_for_api_key_validation() -> Any:
    get_settings.cache_clear()
    return get_settings()


def required_channels_for_creation_step(step: str) -> tuple[CreationChannel, ...]:
    normalized = str(step or "").strip().casefold()
    channels: list[CreationChannel] = []
    if normalized in TEXT_CREATION_STEPS:
        channels.append("text")
    if normalized in IMAGE_CREATION_STEPS:
        channels.append("image")
    if normalized in VIDEO_CREATION_STEPS:
        channels.append("video")
    if normalized in ELEVENLABS_CREATION_STEPS:
        channels.append("dubbing" if normalized in {"dubbing", "generate_dubbing"} else "speech")
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
