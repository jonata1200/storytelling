from pathlib import Path
from typing import Protocol

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
