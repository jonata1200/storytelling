import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.media_utils import local_uri_to_data_url
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    validate_video_clip_duration,
)


class OmniRouteVideoProvider:
    provider_name = "omniroute"

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
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
        )
        return await asyncio.to_thread(self._generate, request, False)

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
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
        ensure_provider_api_key(
            settings.omniroute_api_key,
            self.provider_name,
            "OMNIROUTE_API_KEY",
        )
        duration_seconds = validate_video_clip_duration(request.duration_seconds)
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "seconds": str(duration_seconds),
            "aspect_ratio": request.aspect_ratio,
            "resolution": self._resolution_value(request.size or request.resolution),
            "audio_generation": "Disabled",
            "enable_bgm": "Disabled",
            "keep_original_sound": "Disabled",
        }
        if request.seed is not None:
            body["seed"] = request.seed

        references: list[str] = []
        if image_to_video and request.source_image_uri:
            first_frame = local_uri_to_data_url(request.source_image_uri)
            body["firstframe"] = first_frame
            references.append(first_frame)
        references.extend(local_uri_to_data_url(reference) for reference in request.reference_uris)
        if references:
            body["images"] = references[: self.capabilities.max_reference_images]

        submitted = self._post_json("/videos", body)
        external_job_id = self._task_id(submitted)
        if not external_job_id:
            raise RuntimeError("OmniRoute Videos não retornou id do job")
        completed = self._wait_until_complete(external_job_id, submitted)
        output_url = self._first_content_url(completed)
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
                "native_audio": False,
            },
        )

    def _wait_until_complete(self, external_job_id: str, initial: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 900
        response = initial
        while time.monotonic() < deadline:
            status = str(response.get("status") or "").casefold()
            mapped = self._map_status(status)
            if mapped == GenerationJobStatus.SUCCEEDED:
                return response
            if mapped == GenerationJobStatus.FAILED:
                error = response.get("error") or response.get("message")
                raise RuntimeError(f"OmniRoute Videos job {status}: {redact_secrets(error)}")
            time.sleep(8)
            response = self._get_json(f"/videos/{external_job_id}")
        raise RuntimeError("OmniRoute Videos excedeu o tempo limite de polling")

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        settings = get_settings()
        return urllib.parse.urljoin(
            settings.omniroute_base_url.rstrip("/") + "/",
            path_or_url.lstrip("/"),
        )

    def _headers(self) -> dict[str, str]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.omniroute_api_key,
            self.provider_name,
            "OMNIROUTE_API_KEY",
        )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
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
            raise RuntimeError(
                f"OmniRoute Videos HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        return self._checked_json(parsed)

    def _get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self._url(path), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OmniRoute Videos HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
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
            raise RuntimeError(
                f"OmniRoute Videos download HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc

    def _checked_json(self, parsed: Any) -> dict[str, Any]:
        if not isinstance(parsed, dict):
            raise RuntimeError("OmniRoute Videos retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(f"OmniRoute Videos retornou erro: {redact_secrets(error)}")
        return parsed

    def _map_status(self, status: str) -> GenerationJobStatus:
        normalized = status.casefold()
        if normalized in {"completed", "complete", "succeeded", "success", "done"}:
            return GenerationJobStatus.SUCCEEDED
        if normalized in {"failed", "failure", "error", "cancelled", "canceled", "expired"}:
            return GenerationJobStatus.FAILED
        return GenerationJobStatus.RUNNING

    @staticmethod
    def _resolution_value(value: str | None) -> str:
        resolution = str(value or "").strip().lower()
        if not resolution:
            return "720p"
        if resolution.endswith("p"):
            return resolution
        if "x" not in resolution:
            return resolution
        try:
            width, height = (int(part.strip()) for part in resolution.split("x", 1))
        except ValueError:
            return resolution
        longest_side = max(width, height)
        if longest_side >= 2160:
            return "4k"
        if longest_side >= 1080:
            return "1080p"
        return "720p"

    @staticmethod
    def _task_id(response: Mapping[str, Any]) -> str:
        for key in ("task_id", "taskId", "id"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    def _first_content_url(self, response: Mapping[str, Any]) -> str:
        for value in self._walk_values(response):
            if isinstance(value, str) and value.startswith(("http://", "https://", "/")):
                return value
        raise RuntimeError("OmniRoute Videos não retornou URL do vídeo final")

    def _walk_values(self, value: Any) -> Iterable[Any]:
        if isinstance(value, Mapping):
            for preferred_key in ("url", "video_url", "unsigned_url"):
                if preferred_key in value:
                    yield from self._walk_values(value[preferred_key])
            for preferred_key in ("urls", "unsigned_urls", "video_urls"):
                if preferred_key in value:
                    yield from self._walk_values(value[preferred_key])
            for preferred_key in ("data", "result", "output"):
                if preferred_key in value:
                    yield from self._walk_values(value[preferred_key])
        elif isinstance(value, list):
            for item in value:
                yield from self._walk_values(item)
        else:
            yield value
