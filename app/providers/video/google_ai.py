import asyncio
import base64
import binascii
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, cast

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.media_utils import data_url_parts
from app.providers.video.types import ProviderCapabilities, VideoRequest, VideoResult

DEFAULT_GOOGLE_AI_VIDEO_HTTP_TIMEOUT_SECONDS = 120
DEFAULT_GOOGLE_AI_VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 300
DEFAULT_GOOGLE_AI_VIDEO_MAX_ATTEMPTS = 3
TRANSIENT_GOOGLE_AI_VIDEO_HTTP_STATUS = {429, 500, 502, 503, 504}


class GoogleAIVideoProvider:
    provider_name = "google_ai"
    display_name = "Google AI Videos"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_video=True,
            image_to_video=True,
            video_extension=False,
            reference_images=True,
            first_frame=True,
            last_frame=True,
            native_audio=True,
            supported_durations=[4, 6, 8],
            supported_aspect_ratios=["9:16", "16:9"],
            max_reference_images=3,
        )

    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        external_job_id = await self.submit_from_text(request)
        return await self.poll_submitted(request, external_job_id)

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        external_job_id = await self.submit_from_image(request)
        return await self.poll_submitted_from_image(request, external_job_id)

    async def submit_from_text(self, request: VideoRequest) -> str:
        return await asyncio.to_thread(self._submit, request, False)

    async def submit_from_image(self, request: VideoRequest) -> str:
        return await asyncio.to_thread(self._submit, request, True)

    async def poll_submitted_from_image(
        self,
        request: VideoRequest,
        external_job_id: str,
    ) -> VideoResult:
        return await self.poll_submitted(request, external_job_id)

    async def poll_submitted(self, request: VideoRequest, external_job_id: str) -> VideoResult:
        return await asyncio.to_thread(self._poll, request, external_job_id)

    async def get_status(self, external_job_id: str) -> GenerationJobStatus:
        status = await asyncio.to_thread(self._operation_status, external_job_id)
        if status.get("done") is True:
            if status.get("error"):
                return GenerationJobStatus.FAILED
            return GenerationJobStatus.SUCCEEDED
        return GenerationJobStatus.RUNNING

    async def cancel(self, external_job_id: str) -> None:
        _ = external_job_id

    def _submit(self, request: VideoRequest, image_to_video: bool) -> str:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.google_ai_api_key,
            self.provider_name,
            "GOOGLE_AI_API_KEY",
        )
        model = validate_model_name(request.model, provider=self.provider_name)
        body = self._request_body(request, image_to_video)
        response = self._post_json(
            settings.google_ai_base_url,
            api_key,
            f"/models/{model}:predictLongRunning",
            body,
        )
        operation_name = response.get("name")
        if not isinstance(operation_name, str) or not operation_name.strip():
            raise RuntimeError(f"{self.display_name} nao retornou nome da operacao")
        return operation_name

    def _poll(self, request: VideoRequest, external_job_id: str) -> VideoResult:
        settings = get_settings()
        deadline = time.monotonic() + max(1, settings.google_ai_video_poll_timeout_seconds)
        poll_interval = max(1, settings.google_ai_video_poll_interval_seconds)
        operation = self._operation_status(external_job_id)
        while operation.get("done") is not True:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{self.display_name} timeout ao aguardar video")
            time.sleep(poll_interval)
            operation = self._operation_status(external_job_id)
        if error := operation.get("error"):
            raise RuntimeError(f"{self.display_name} retornou erro: {redact_secrets(error)}")
        video_bytes, content_type, metadata = self._video_bytes(operation)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        safe_job_id = external_job_id.replace("/", "_").replace("\\", "_")
        file_path = request.output_dir / f"{safe_job_id}.mp4"
        file_path.write_bytes(video_bytes)
        return VideoResult(
            external_job_id=external_job_id,
            status=GenerationJobStatus.SUCCEEDED,
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(video_bytes).hexdigest(),
            content_type=content_type,
            provider=self.provider_name,
            model=validate_model_name(request.model, provider=self.provider_name),
            metadata=metadata
            | {
                "operation_name": external_job_id,
                "native_audio": True,
                "aspect_ratio": self._normalized_aspect_ratio(request.aspect_ratio),
                "duration_seconds": self._duration_seconds(
                    request.duration_seconds,
                    resolution=self._resolution(request.resolution or request.size),
                    has_image_input=bool(request.source_image_uri),
                    has_references=bool(request.reference_uris),
                ),
                "resolution": self._resolution(request.resolution or request.size),
            },
        )

    def _operation_status(self, external_job_id: str) -> dict[str, Any]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.google_ai_api_key,
            self.provider_name,
            "GOOGLE_AI_API_KEY",
        )
        if external_job_id.startswith(("http://", "https://")):
            return self._get_json("", api_key, external_job_id)
        path = external_job_id if external_job_id.startswith("/") else f"/{external_job_id}"
        return self._get_json(settings.google_ai_base_url, api_key, path)

    def _request_body(self, request: VideoRequest, image_to_video: bool) -> dict[str, Any]:
        instance: dict[str, Any] = {"prompt": request.prompt}
        if image_to_video and request.source_image_uri:
            image = self._image_payload(request.source_image_uri)
            if image is not None:
                instance["image"] = image
        references = []
        if self._model_supports_reference_images(request.model):
            for reference in request.reference_uris[: self.capabilities.max_reference_images]:
                image = self._image_payload(reference)
                if image is not None:
                    references.append({"image": image, "referenceType": "asset"})
        if references:
            instance["referenceImages"] = references
        resolution = self._resolution(request.resolution or request.size)
        duration_seconds = self._duration_seconds(
            request.duration_seconds,
            resolution=resolution,
            has_image_input=image_to_video and bool(request.source_image_uri),
            has_references=bool(references),
        )
        parameters: dict[str, Any] = {
            "aspectRatio": self._normalized_aspect_ratio(request.aspect_ratio),
            "durationSeconds": str(duration_seconds),
            "resolution": resolution,
            **({"seed": request.seed} if request.seed is not None else {}),
        }
        if image_to_video or references:
            parameters["personGeneration"] = "allow_adult"
        return {
            "instances": [instance],
            "parameters": parameters,
        }

    @staticmethod
    def _model_supports_reference_images(model: str) -> bool:
        normalized = str(model or "").strip().casefold()
        return normalized == "veo-3.1-generate-preview"

    @staticmethod
    def _image_payload(uri: str) -> dict[str, Any] | None:
        parts = data_url_parts(uri)
        if parts is None:
            return None
        media_type, encoded = parts
        return {"mimeType": media_type, "bytesBase64Encoded": encoded}

    @staticmethod
    def _normalized_aspect_ratio(value: str) -> str:
        return "16:9" if str(value or "").strip() == "16:9" else "9:16"

    @staticmethod
    def _duration_seconds(
        value: int,
        *,
        resolution: str = "720p",
        has_image_input: bool = False,
        has_references: bool = False,
    ) -> int:
        _ = has_image_input
        if resolution in {"1080p", "4k"} or has_references:
            return 8
        if value <= 4:
            return 4
        if value <= 6:
            return 6
        return 8

    @staticmethod
    def _resolution(value: str | None) -> str:
        _ = value
        return "720p"

    def _post_json(
        self,
        base_url: str,
        api_key: str,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(api_key),
            method="POST",
        )
        return self._send_json(request, "submit")

    def _get_json(self, base_url: str, api_key: str, path: str) -> dict[str, Any]:
        url = path if path.startswith(("http://", "https://")) else f"{base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            headers=self._headers(api_key),
            method="GET",
        )
        return self._send_json(request, "poll")

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "X-Correlation-ID": current_correlation_id() or "",
        }

    def _send_json(self, request: urllib.request.Request, operation: str) -> dict[str, Any]:
        parsed: object
        for attempt in range(DEFAULT_GOOGLE_AI_VIDEO_MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=DEFAULT_GOOGLE_AI_VIDEO_HTTP_TIMEOUT_SECONDS,
                ) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if self._should_retry(attempt, exc.code):
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise RuntimeError(
                    f"{self.display_name} {operation} HTTP {exc.code}: "
                    f"{redact_secrets(detail)}"
                ) from exc
            except urllib.error.URLError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"{self.display_name} {operation} network error: "
                    f"{redact_secrets(exc.reason)}"
                ) from exc
            except TimeoutError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"{self.display_name} {operation} timeout") from exc
            except OSError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"{self.display_name} {operation} connection error: "
                    f"{redact_secrets(exc)}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{self.display_name} {operation} retornou JSON invalido"
                ) from exc
        else:
            raise RuntimeError(f"{self.display_name} {operation} excedeu tentativas")
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta fora do formato esperado")
        return parsed

    @staticmethod
    def _should_retry(attempt: int, status_code: int | None = None) -> bool:
        has_attempts_left = attempt < DEFAULT_GOOGLE_AI_VIDEO_MAX_ATTEMPTS - 1
        if not has_attempts_left:
            return False
        return status_code is None or status_code in TRANSIENT_GOOGLE_AI_VIDEO_HTTP_STATUS

    @staticmethod
    def _sleep_before_retry(
        attempt: int,
        exc: urllib.error.HTTPError | None = None,
    ) -> None:
        retry_after = ""
        if exc is not None and exc.headers is not None:
            retry_after = str(exc.headers.get("Retry-After") or "")
        if retry_after.isdigit():
            delay_seconds = min(int(retry_after), 8)
        else:
            delay_seconds = min(2**attempt, 8)
        time.sleep(delay_seconds)

    def _video_bytes(self, operation: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
        video = self._first_video_payload(operation)
        raw_inline_data = video.get("inlineData")
        inline_data = (
            cast(dict[str, Any], raw_inline_data) if isinstance(raw_inline_data, dict) else {}
        )
        encoded = video.get("videoBytes") or inline_data.get("data")
        if isinstance(encoded, str) and encoded.strip():
            media_type = str(inline_data.get("mimeType") or video.get("mimeType") or "video/mp4")
            try:
                return base64.b64decode(encoded.encode("ascii"), validate=True), media_type, {
                    "delivery": "inline"
                }
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError(f"{self.display_name} retornou video base64 invalido") from exc
        uri = video.get("uri")
        if isinstance(uri, str) and uri.strip():
            video_bytes, media_type = self._download_video(uri)
            return video_bytes, media_type, {"delivery": "uri", "video_uri": uri}
        raise RuntimeError(f"{self.display_name} nao retornou video final")

    def _first_video_payload(self, operation: dict[str, Any]) -> dict[str, Any]:
        raw_response = operation.get("response")
        response = cast(dict[str, Any], raw_response) if isinstance(raw_response, dict) else {}
        generate_response = response.get("generateVideoResponse")
        if isinstance(generate_response, dict):
            samples = generate_response.get("generatedSamples")
            if isinstance(samples, list) and samples:
                sample = samples[0]
                if isinstance(sample, dict) and isinstance(sample.get("video"), dict):
                    return cast(dict[str, Any], sample["video"])
        generated_videos = response.get("generatedVideos")
        if isinstance(generated_videos, list) and generated_videos:
            first = generated_videos[0]
            if isinstance(first, dict) and isinstance(first.get("video"), dict):
                return cast(dict[str, Any], first["video"])
        raise RuntimeError(f"{self.display_name} retornou operacao sem video")

    def _download_video(self, uri: str) -> tuple[bytes, str]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.google_ai_api_key,
            self.provider_name,
            "GOOGLE_AI_API_KEY",
        )
        request = urllib.request.Request(uri, headers={"x-goog-api-key": api_key}, method="GET")
        for attempt in range(DEFAULT_GOOGLE_AI_VIDEO_MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=DEFAULT_GOOGLE_AI_VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
                ) as response:
                    content: bytes = response.read()
                    content_type = response.headers.get_content_type() or "video/mp4"
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if self._should_retry(attempt, exc.code):
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise RuntimeError(
                    f"{self.display_name} download HTTP {exc.code}: {redact_secrets(detail)}"
                ) from exc
            except urllib.error.URLError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"{self.display_name} download network error: {redact_secrets(exc.reason)}"
                ) from exc
        else:
            raise RuntimeError(f"{self.display_name} download excedeu tentativas")
        return content, content_type
