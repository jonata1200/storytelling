import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config.model_policy import validate_openrouter_model_name
from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.providers.media_utils import local_uri_to_data_url
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    validate_video_clip_duration,
)


class OpenRouterVideoProvider:
    provider_name = "openrouter"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_video=True,
            image_to_video=True,
            reference_images=True,
            first_frame=True,
            native_audio=True,
            supported_durations=list(range(VIDEO_CLIP_MIN_SECONDS, VIDEO_CLIP_MAX_SECONDS + 1)),
            supported_aspect_ratios=["9:16", "16:9", "1:1", "4:3", "3:4"],
            max_reference_images=4,
        )

    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        request = request.model_copy(
            update={"model": validate_openrouter_model_name(request.model)}
        )
        return await asyncio.to_thread(self._generate, request, False)

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        request = request.model_copy(
            update={"model": validate_openrouter_model_name(request.model)}
        )
        return await asyncio.to_thread(self._generate, request, True)

    async def get_status(self, external_job_id: str) -> GenerationJobStatus:
        response = await asyncio.to_thread(self._get_json, f"/videos/{external_job_id}")
        return self._map_status(str(response.get("status") or ""))

    async def cancel(self, external_job_id: str) -> None:
        _ = external_job_id
        return None

    def _generate(self, request: VideoRequest, image_to_video: bool) -> VideoResult:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")
        duration_seconds = validate_video_clip_duration(request.duration_seconds)

        body: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "duration": duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": False,
        }
        if request.size:
            body["size"] = request.size
        elif request.resolution:
            body["resolution"] = request.resolution
        else:
            body["resolution"] = "720p"
        if request.seed is not None:
            body["seed"] = request.seed
        if image_to_video and request.source_image_uri:
            body["frame_images"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": local_uri_to_data_url(request.source_image_uri)},
                    "frame_type": "first_frame",
                }
            ]
        elif request.reference_uris:
            body["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": local_uri_to_data_url(reference)},
                }
                for reference in request.reference_uris
            ]

        submitted = self._post_json("/videos", body)
        external_job_id = str(submitted.get("id") or "")
        if not external_job_id:
            raise RuntimeError("OpenRouter Videos nao retornou id do job")
        completed = self._wait_until_complete(external_job_id, submitted)
        output_url = self._first_content_url(external_job_id, completed)
        video_bytes = self._download(output_url)

        request.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = request.output_dir / f"{external_job_id}.mp4"
        file_path.write_bytes(video_bytes)
        sha256 = hashlib.sha256(video_bytes).hexdigest()
        raw_usage = completed.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return VideoResult(
            external_job_id=external_job_id,
            status=GenerationJobStatus.SUCCEEDED,
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            content_type="video/mp4",
            provider=self.provider_name,
            model=request.model,
            estimated_cost=str(usage.get("cost") or "0.000000"),
            metadata={
                "submit_response": submitted,
                "poll_response": completed,
                "mode": "image_to_video" if image_to_video else "text_to_video",
            },
        )

    def _wait_until_complete(self, external_job_id: str, initial: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 900
        response = initial
        while time.monotonic() < deadline:
            status = str(response.get("status") or "")
            if status == "completed":
                return response
            if status in {"failed", "cancelled", "expired"}:
                raise RuntimeError(f"OpenRouter Videos job {status}: {response.get('error')}")
            time.sleep(8)
            response = self._get_json(f"/videos/{external_job_id}")
        raise RuntimeError("OpenRouter Videos excedeu o tempo limite de polling")

    def _first_content_url(self, external_job_id: str, response: dict[str, Any]) -> str:
        urls = response.get("unsigned_urls")
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
        return f"/videos/{external_job_id}/content?index=0"

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        settings = get_settings()
        return urllib.parse.urljoin(
            settings.openrouter_base_url.rstrip("/") + "/",
            path_or_url.lstrip("/"),
        )

    def _headers(self) -> dict[str, str]:
        settings = get_settings()
        return {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-OpenRouter-Title": settings.openrouter_app_title,
        }

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url(path),
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter Videos HTTP {exc.code}: {detail}") from exc
        return self._checked_json(parsed)

    def _get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self._url(path), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter Videos HTTP {exc.code}: {detail}") from exc
        return self._checked_json(parsed)

    def _download(self, path_or_url: str) -> bytes:
        request = urllib.request.Request(
            self._url(path_or_url),
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                content: bytes = response.read()
                return content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter Videos download HTTP {exc.code}: {detail}") from exc

    def _checked_json(self, parsed: Any) -> dict[str, Any]:
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter Videos retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(f"OpenRouter Videos retornou erro: {error}")
        return parsed

    def _map_status(self, status: str) -> GenerationJobStatus:
        if status == "completed":
            return GenerationJobStatus.SUCCEEDED
        if status in {"pending", "in_progress"}:
            return GenerationJobStatus.RUNNING
        if status in {"failed", "cancelled", "expired"}:
            return GenerationJobStatus.FAILED
        return GenerationJobStatus.RUNNING
