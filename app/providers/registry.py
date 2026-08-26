from collections.abc import Callable
from typing import Any, cast

from app.config.provider_policy import ProviderChannel, effective_provider_for_channel
from app.providers.image.types import ImageProvider
from app.providers.llm.types import LLMProvider
from app.providers.video.types import VideoProvider

ProviderFactory = Callable[[], object]


class ProviderRegistry:
    """Central provider resolution without leaking adapters into domain services."""

    def __init__(self) -> None:
        self._factories: dict[ProviderChannel, dict[str, ProviderFactory]] = {
            "text": {},
            "image": {},
            "video": {},
        }

    def register(self, channel: ProviderChannel, name: str, factory: ProviderFactory) -> None:
        normalized = str(name or "").strip().casefold()
        if not normalized:
            raise ValueError("Nome do provider não pode ficar vazio.")
        self._factories[channel][normalized] = factory

    def resolve(self, channel: ProviderChannel, name: str) -> object:
        normalized = str(name or "").strip().casefold()
        factory = self._factories[channel].get(normalized)
        if factory is None:
            raise ValueError(
                f"Provider '{normalized or '(vazio)'}' não possui adapter registrado "
                f"para o canal {channel}."
            )
        return factory()

    def resolve_configured(self, settings: Any, channel: ProviderChannel) -> object:
        return self.resolve(channel, effective_provider_for_channel(settings, channel))


def _vibes_factory() -> object:
    from app.providers.video.vibes import VibesVideoProvider

    return VibesVideoProvider()


def _ollama_cloud_factory() -> object:
    from app.providers.llm.ollama_cloud import OllamaCloudLLMProvider

    return OllamaCloudLLMProvider()


def _meta_image_factory() -> object:
    from app.providers.image.meta import MetaImageProvider

    return MetaImageProvider()


provider_registry = ProviderRegistry()
provider_registry.register("text", "ollama_cloud", _ollama_cloud_factory)
provider_registry.register("image", "meta", _meta_image_factory)
provider_registry.register("video", "vibes", _vibes_factory)


def resolve_text_provider(settings: Any, name: str | None = None) -> LLMProvider:
    provider = name or effective_provider_for_channel(settings, "text")
    return cast(LLMProvider, provider_registry.resolve("text", provider))


def resolve_image_provider(settings: Any, name: str | None = None) -> ImageProvider:
    provider = name or effective_provider_for_channel(settings, "image")
    return cast(ImageProvider, provider_registry.resolve("image", provider))


def resolve_video_provider(settings: Any, name: str | None = None) -> VideoProvider:
    provider = name or effective_provider_for_channel(settings, "video")
    return cast(VideoProvider, provider_registry.resolve("video", provider))
