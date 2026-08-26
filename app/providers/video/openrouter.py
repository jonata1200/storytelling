import asyncio
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.providers.video.types import (
    VideoGenerationRequest,
    VideoGenerationResult,
    VideoJob,
    VideoJobUpdate,
)

OPENROUTER_VIDEO_SUBMIT_TIMEOUT_SECONDS = 30
OPENROUTER_VIDEO_POLL_TIMEOUT_SECONDS = 30
OPENROUTER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 180
OPENROUTER_VIDEO_MAX_ATTEMPTS = 3
TRANSIENT_OPENROUTER_HTTP_STATUS = {429, 500, 502, 503, 504}

TERMINAL_VIDEO_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}

logger = logging.getLogger(__name__)


class OpenRouterVideoProvider:
    provider_name = "openrouter"
    display_name = "OpenRouter"

    async def submit(self, request: VideoGenerationRequest) -> VideoJob:
        model = validate_model_name(request.model, provider=self.provider_name)
        return await asyncio.to_thread(
            self._submit,
            request.model_copy(update={"model": model}),
        )

    async def poll(self, job: VideoJob) -> VideoJobUpdate:
        return await asyncio.to_thread(self._poll, job)

    async def download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        return await asyncio.to_thread(self._download, job, output_dir)

    # ------------------------------------------------------------------
    # Implementações síncronas (rodam em thread)
    # ------------------------------------------------------------------

    def _submit(self, request: VideoGenerationRequest) -> VideoJob:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.openrouter_api_key,
            self.provider_name,
            "OPENROUTER_API_KEY",
        )
        body = self._request_body(request)
        payload_kb = len(json.dumps(body).encode("utf-8")) // 1024
        started_at = time.perf_counter()
        logger.warning(
            "openrouter_video_submit_started model=%s duration=%s aspect=%s "
            "resolution=%s references=%s frames=%s payload_kb=%s",
            request.model,
            request.duration,
            request.aspect_ratio,
            request.resolution,
            len(request.input_references),
            len(request.frame_images),
            payload_kb,
        )
        try:
            response = self._post_json(settings.openrouter_video_base_url, api_key, "/videos", body)
        except RuntimeError as exc:
            error_msg = str(exc).lower()
            has_references = bool(body.get("input_references"))
            if has_references and (
                "sensitivecontent" in error_msg
                or "privacyinformation" in error_msg
                or "may contain real person" in error_msg
            ):
                logger.warning(
                    "openrouter_video_content_filter_references model=%s "
                    "retrying_without_references",
                    request.model,
                )
                body.pop("input_references", None)
                payload_kb = len(json.dumps(body).encode("utf-8")) // 1024
                response = self._post_json(
                    settings.openrouter_video_base_url, api_key, "/videos", body
                )
            else:
                logger.warning(
                    "openrouter_video_submit_failed model=%s elapsed_seconds=%.1f",
                    request.model,
                    time.perf_counter() - started_at,
                    exc_info=True,
                )
                raise
        logger.warning(
            "openrouter_video_submit_completed model=%s job_id=%s elapsed_seconds=%.1f",
            request.model,
            str(response.get("id") or ""),
            time.perf_counter() - started_at,
        )
        job_id = str(response.get("id") or "").strip()
        if not job_id:
            raise ValueError(
                "OpenRouter não retornou um job id para a geração de vídeo. "
                f"Resposta: {json.dumps(response)[:400]}"
            )
        return VideoJob(
            id=job_id,
            polling_url=str(response.get("polling_url") or "").strip(),
            status=str(response.get("status") or "pending"),
            provider=self.provider_name,
            model=request.model,
            prompt=request.prompt,
        )

    def _poll(self, job: VideoJob) -> VideoJobUpdate:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.openrouter_api_key,
            self.provider_name,
            "OPENROUTER_API_KEY",
        )
        if not job.polling_url:
            raise ValueError("Job de vídeo sem polling_url para consultar.")
        response = self._get_json(settings.openrouter_video_base_url, api_key, job.polling_url)
        status = str(response.get("status") or "pending").strip().lower()
        error = None
        raw_error = response.get("error")
        if raw_error:
            error = (
                raw_error.get("message")
                if isinstance(raw_error, dict)
                else str(raw_error)
            )
        usage = response.get("usage")
        usage_cost = None
        if isinstance(usage, dict):
            raw_cost = usage.get("cost")
            if raw_cost is not None:
                usage_cost = str(raw_cost)
        unsigned_urls = [
            str(url)
            for url in (response.get("unsigned_urls") or [])
            if str(url).strip()
        ]
        return VideoJobUpdate(
            status=status,
            unsigned_urls=unsigned_urls,
            error=error,
            usage_cost=usage_cost,
        )

    def _download(self, job: VideoJob, output_dir: Path) -> VideoGenerationResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.openrouter_api_key,
            self.provider_name,
            "OPENROUTER_API_KEY",
        )
        started_at = time.perf_counter()
        try:
            video_bytes, content_type = self._download_bytes(
                settings.openrouter_video_base_url,
                api_key,
                job,
                unsigned_urls=job.unsigned_urls,
            )
        except Exception:
            logger.warning(
                "openrouter_video_download_failed job_id=%s elapsed_seconds=%.1f",
                job.id,
                time.perf_counter() - started_at,
                exc_info=True,
            )
            raise
        output_dir.mkdir(parents=True, exist_ok=True)
        extension = _extension_for_content_type(content_type)
        filename = f"segmento-{uuid4().hex[:12]}{extension}"
        file_path = output_dir / filename
        file_path.write_bytes(video_bytes)
        logger.warning(
            "openrouter_video_download_completed job_id=%s bytes=%s elapsed_seconds=%.1f",
            job.id,
            len(video_bytes),
            time.perf_counter() - started_at,
        )
        return VideoGenerationResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(video_bytes).hexdigest(),
            content_type=content_type,
            provider=self.provider_name,
            model="",
            prompt="",
            estimated_cost="0.000000",
            job_id=job.id,
        )

    # ------------------------------------------------------------------
    # Corpo da requisição
    # ------------------------------------------------------------------

    def _request_body(self, request: VideoGenerationRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "duration": int(request.duration),
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "generate_audio": bool(request.generate_audio),
        }
        if request.seed is not None:
            body["seed"] = int(request.seed)
        if request.frame_images:
            body["frame_images"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": item.url},
                    "frame_type": item.frame_type,
                }
                for item in request.frame_images
                if item.url.strip()
            ]
        if request.input_references:
            body["input_references"] = [
                {"type": "image_url", "image_url": {"url": item.url}}
                for item in request.input_references
                if item.url.strip()
            ]
        return body

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _post_json(
        self,
        base_url: str,
        api_key: str,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: BaseException | None = None
        for attempt in range(OPENROUTER_VIDEO_MAX_ATTEMPTS):
            request = urllib.request.Request(
                f"{base_url.rstrip('/')}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "X-Correlation-ID": current_correlation_id() or "",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=OPENROUTER_VIDEO_SUBMIT_TIMEOUT_SECONDS,
                ) as response:
                    return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
                last_error = exc
                if exc.code not in TRANSIENT_OPENROUTER_HTTP_STATUS or attempt == (
                    OPENROUTER_VIDEO_MAX_ATTEMPTS - 1
                ):
                    break
                time.sleep(2**attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == OPENROUTER_VIDEO_MAX_ATTEMPTS - 1:
                    break
                time.sleep(2**attempt)
        if isinstance(last_error, urllib.error.HTTPError):
            detail_text = detail if "detail" in locals() else str(last_error.reason)
            raise RuntimeError(
                f"OpenRouter vídeo HTTP {last_error.code}: {detail_text}"
            ) from last_error
        raise RuntimeError(f"OpenRouter vídeo indisponível: {last_error}") from last_error

    def _get_json(
        self,
        base_url: str,
        api_key: str,
        url: str,
    ) -> dict[str, Any]:
        target = url if url.startswith("http://") or url.startswith("https://") else (
            f"{base_url.rstrip('/')}/{url.lstrip('/')}"
        )
        request = urllib.request.Request(
            target,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=OPENROUTER_VIDEO_POLL_TIMEOUT_SECONDS,
            ) as response:
                return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(
                f"OpenRouter vídeo poll HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"OpenRouter vídeo poll indisponível: {exc}") from exc

    def _download_bytes(
        self,
        base_url: str,
        api_key: str,
        job: VideoJob,
        unsigned_urls: list[str] | None = None,
    ) -> tuple[bytes, str]:
        candidate_urls = list(unsigned_urls or [])
        candidate_urls.append(
            f"{base_url.rstrip('/')}/videos/{job.id}/content"
        )
        last_error: BaseException | None = None
        for url in candidate_urls:
            if not str(url or "").strip():
                continue
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-Correlation-ID": current_correlation_id() or "",
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=OPENROUTER_VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
                ) as response:
                    return response.read(), response.headers.get_content_type() or "video/mp4"
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
        raise RuntimeError(f"Falha ao baixar vídeo do OpenRouter: {last_error}") from last_error


def _extension_for_content_type(content_type: str) -> str:
    normalized = str(content_type or "").strip().lower()
    if "mp4" in normalized:
        return ".mp4"
    if "webm" in normalized:
        return ".webm"
    if "quicktime" in normalized:
        return ".mov"
    return ".mp4"
