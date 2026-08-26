from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, cast

from app.providers.video.types import VideoGenerationResult, VideoJob, VideoJobUpdate


class VibesBrowserBackend(Protocol):
    """Porta para uma automação autorizada; nenhum detalhe web vaza ao domínio."""

    async def submit(self, payload: dict[str, object]) -> VideoJob: ...

    async def poll(self, job: VideoJob) -> VideoJobUpdate: ...

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult: ...


class UnconfiguredVibesBrowserBackend:
    """Falha segura enquanto não houver uma sessão/automação autorizada instalada."""

    @staticmethod
    def _unavailable() -> RuntimeError:
        return RuntimeError(
            "Automação Vibes não configurada. Conecte uma implementação Playwright autorizada "
            "com perfil dedicado; cookies, senhas e endpoints internos não são aceitos."
        )

    async def submit(self, payload: dict[str, object]) -> VideoJob:
        raise self._unavailable()

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        raise self._unavailable()

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        raise self._unavailable()


VIBES_BROWSER_ENTRY_POINT_GROUP = "storytelling.vibes_browser"


def load_vibes_browser_backend() -> VibesBrowserBackend:
    matches = list(entry_points(group=VIBES_BROWSER_ENTRY_POINT_GROUP))
    if not matches:
        from app.providers.browser_bridge import browser_bridge_available
        from app.providers.video.vibes_playwright import PlaywrightVibesBrowserBackend

        return (
            PlaywrightVibesBrowserBackend()
            if browser_bridge_available()
            else UnconfiguredVibesBrowserBackend()
        )
    if len(matches) > 1:
        raise RuntimeError("Mais de um backend Vibes foi instalado. Mantenha somente um.")
    loaded: Any = matches[0].load()
    backend = loaded() if isinstance(loaded, type) else loaded
    for method_name in ("submit", "poll", "download"):
        if not callable(getattr(backend, method_name, None)):
            raise RuntimeError(f"Plugin Vibes não implementa {method_name}().")
    return cast(VibesBrowserBackend, backend)


def vibes_browser_backend_available() -> bool:
    try:
        backend = load_vibes_browser_backend()
        return not isinstance(backend, UnconfiguredVibesBrowserBackend)
    except RuntimeError:
        return False
