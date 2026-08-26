import asyncio
from pathlib import Path

from app.config.provider_policy import provider_integration_mode, validate_model_name
from app.config.settings import get_settings
from app.providers.video.types import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoJob,
    VideoJobUpdate,
)
from app.providers.video.vibes_browser import (
    VibesBrowserBackend,
    load_vibes_browser_backend,
)
from app.providers.video.vibes_mapping import map_vibes_request


class VibesVideoProvider:
    provider_name = "vibes"
    display_name = "Vibes"

    def __init__(self, browser_backend: VibesBrowserBackend | None = None) -> None:
        self._browser = browser_backend or load_vibes_browser_backend()

    def _ensure_browser_mode(self) -> None:
        settings = get_settings()
        mode = provider_integration_mode(settings, self.provider_name, "video")
        if mode == "api":
            raise RuntimeError(
                "Vibes não possui API pública documentada para geração de vídeo. "
                "VIBES_INTEGRATION_MODE=api foi bloqueado para evitar endpoints privados."
            )
        if not settings.vibes_browser_automation_enabled:
            raise RuntimeError(
                "Habilite a automação de vídeos Vibes nos Ajustes antes de gerar vídeos."
            )

    async def submit(self, request: VideoGenerationRequest) -> VideoJob:
        self._ensure_browser_mode()
        model = validate_model_name(request.model, provider=self.provider_name)
        normalized = request.model_copy(update={"model": model})
        job = await self._browser.submit(map_vibes_request(normalized))
        return job.model_copy(
            update={"provider": self.provider_name, "model": model, "prompt": request.prompt}
        )

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        self._ensure_browser_mode()
        return await self._browser.poll(job)

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        self._ensure_browser_mode()
        result = await self._browser.download(job, output_dir)
        await asyncio.to_thread(_validate_download, result, output_dir)
        if result.provider != self.provider_name:
            result = result.model_copy(update={"provider": self.provider_name})
        return result


def _is_video(content: bytes, content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if not content or not media_type.startswith("video/"):
        return False
    if media_type in {"video/mp4", "video/quicktime"}:
        return len(content) >= 12 and content[4:8] == b"ftyp"
    if media_type == "video/webm":
        return content.startswith(b"\x1aE\xdf\xa3")
    return False


def _validate_download(result: VideoGenerationResult, output_dir: Path) -> None:
    resolved_output = output_dir.resolve(strict=False)
    resolved_file = result.file_path.resolve(strict=True)
    try:
        resolved_file.relative_to(resolved_output)
    except ValueError as exc:
        raise ValueError("Vibes retornou arquivo fora do diretório de saída") from exc
    if not _is_video(resolved_file.read_bytes(), result.content_type):
        raise ValueError("Vibes retornou arquivo vazio, corrompido ou que não é vídeo")
