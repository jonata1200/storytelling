import asyncio
import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from app.config.settings import get_settings
from app.providers.browser_bridge import run_browser_bridge
from app.providers.video.types import VideoGenerationResult, VideoJob, VideoJobUpdate


class PlaywrightVibesBrowserBackend:
    # Artefatos intermediários do bridge (MP4s parciais + job-state.json) ficam
    # FORA do escopo da varredura de órfãos (INC-09): o checkpoint job-state.json
    # é a fonte de retomada do poll e não pode ser apagado como "órfão".
    BRIDGE_JOB_DIR = Path("bridge_jobs") / "video"

    @staticmethod
    def _bridge_job_output_dir(storage_root: Path) -> Path:
        return storage_root / PlaywrightVibesBrowserBackend.BRIDGE_JOB_DIR

    @staticmethod
    def _job_path(value: object, output_dir: Path) -> Path:
        resolved = Path(str(value)).resolve(strict=True)
        resolved.relative_to(output_dir.resolve(strict=False))
        return resolved

    async def submit(self, payload: dict[str, object]) -> VideoJob:
        settings = get_settings()
        output_dir = self._bridge_job_output_dir(settings.local_storage_path)
        response = await run_browser_bridge(
            "submit-video",
            {
                "profilePath": str(settings.vibes_browser_profile_path),
                "outputDir": str(output_dir),
                **payload,
            },
            timeout_seconds=180,
        )
        polling_path = await asyncio.to_thread(
            self._job_path, response["pollingUrl"], output_dir
        )
        return VideoJob(
            id=str(response.get("jobId") or uuid4()),
            polling_url=polling_path.as_posix(),
            project_url=str(response.get("projectUrl") or ""),
            status=str(response.get("status") or "pending"),
        )

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        settings = get_settings()
        response = await run_browser_bridge(
            "poll-video",
            {
                "profilePath": str(settings.vibes_browser_profile_path),
                "statePath": job.polling_url,
                "deadlineSeconds": 1800,
            },
            timeout_seconds=120,
        )
        paths: list[str] = []
        output_dir = self._bridge_job_output_dir(settings.local_storage_path)
        for value in list(response.get("filePaths") or []):
            try:
                resolved = await asyncio.to_thread(
                    self._job_path, value, output_dir
                )
            except (FileNotFoundError, ValueError):
                continue
            paths.append(resolved.as_posix())
        return VideoJobUpdate(
            status=str(response.get("status") or "pending"),
            unsigned_urls=paths,
            project_url=str(response.get("projectUrl") or job.project_url),
            error=str(response.get("error") or "") or None,
        )

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        if not job.unsigned_urls:
            raise FileNotFoundError("Nenhum vídeo do Vibes foi baixado para este job")
        source = await asyncio.to_thread(
            lambda: Path(job.unsigned_urls[0]).resolve(strict=True)
        )
        await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
        destination = output_dir / f"vibes-{job.id}.mp4"
        await asyncio.to_thread(shutil.copyfile, source, destination)
        content = await asyncio.to_thread(destination.read_bytes)
        return VideoGenerationResult(
            file_path=destination,
            storage_uri=destination.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type="video/mp4",
            provider="vibes",
            model=job.model or "vibes",
            prompt=job.prompt,
            job_id=job.id,
        )
