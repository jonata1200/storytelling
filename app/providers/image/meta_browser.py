from importlib.metadata import entry_points
from typing import Any, Protocol, cast

from app.providers.image.types import ImageGenerationRequest, ImageGenerationResult


class MetaImageBrowserBackend(Protocol):
    """Porta para automação autorizada do Meta Image com perfil dedicado."""

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


class UnconfiguredMetaImageBrowserBackend:
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        _ = request
        raise RuntimeError(
            "Automação Meta Image não configurada. Instale uma implementação browser "
            "autorizada; cookies, senhas e endpoints privados não são aceitos."
        )


META_IMAGE_BROWSER_ENTRY_POINT_GROUP = "storytelling.meta_image_browser"


def load_meta_image_browser_backend() -> MetaImageBrowserBackend:
    """Load one explicitly installed, authorized browser backend plugin."""
    matches = list(entry_points(group=META_IMAGE_BROWSER_ENTRY_POINT_GROUP))
    if not matches:
        from app.providers.browser_bridge import browser_bridge_available
        from app.providers.image.meta_playwright import PlaywrightMetaImageBrowserBackend

        return (
            PlaywrightMetaImageBrowserBackend()
            if browser_bridge_available()
            else UnconfiguredMetaImageBrowserBackend()
        )
    if len(matches) > 1:
        raise RuntimeError(
            "Mais de um backend Meta Image foi instalado. Mantenha somente uma implementação."
        )
    loaded: Any = matches[0].load()
    backend = loaded() if isinstance(loaded, type) else loaded
    if not callable(getattr(backend, "generate", None)):
        raise RuntimeError("O plugin de browser do Meta Image não implementa generate().")
    return cast(MetaImageBrowserBackend, backend)


def meta_image_browser_backend_available() -> bool:
    try:
        backend = load_meta_image_browser_backend()
        return not isinstance(backend, UnconfiguredMetaImageBrowserBackend)
    except RuntimeError:
        return False
