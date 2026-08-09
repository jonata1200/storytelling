import asyncio
import base64
import binascii
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, cast
from uuid import uuid4

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.production.service import normalize_image_aspect_ratio, normalize_image_resolution
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import data_url_parts, extension_from_media_type

DEFAULT_GOOGLE_AI_IMAGE_TIMEOUT_SECONDS = 120
DEFAULT_GOOGLE_AI_IMAGE_MAX_ATTEMPTS = 2
GOOGLE_AI_IMAGE_RESPONSE_MIME_TYPE = "image/jpeg"
TRANSIENT_GOOGLE_AI_HTTP_STATUS = {429, 500, 502, 503, 504}


class GoogleAIImageProvider:
    provider_name = "google_ai"
    display_name = "Google AI Images"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        model = validate_model_name(request.model, provider=self.provider_name)
        return await asyncio.to_thread(self._generate, request.model_copy(update={"model": model}))

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        generation_request = ImageGenerationRequest(
            prompt=request.prompt,
            target_id="edit",
            view_type="variant",
            output_dir=request.output_dir,
            references=[request.source_uri],
            model=request.model,
        )
        return await self.generate(generation_request)

    def _generate(self, request: ImageGenerationRequest) -> ImageResult:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.google_ai_api_key,
            self.provider_name,
            "GOOGLE_AI_API_KEY",
        )
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        body = self._request_body(prompt, request)
        response = self._post_json(settings.google_ai_base_url, api_key, "/interactions", body)
        image_bytes, media_type = self._image_bytes(response)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        extension = extension_from_media_type(media_type)
        safe_view = request.view_type.replace("/", "_").replace("\\", "_")
        filename = f"{request.target_id}_{safe_view}_{uuid4().hex[:8]}{extension}"
        file_path = request.output_dir / filename
        file_path.write_bytes(image_bytes)
        raw_usage = response.get("usage")
        usage = cast(dict[str, Any], raw_usage) if isinstance(raw_usage, dict) else {}
        return ImageResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            content_type=media_type,
            provider=self.provider_name,
            model=request.model,
            prompt=prompt,
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _request_body(self, prompt: str, request: ImageGenerationRequest) -> dict[str, Any]:
        input_blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for reference in request.references:
            parts = data_url_parts(reference)
            if parts is None:
                continue
            media_type, encoded = parts
            input_blocks.append(
                {
                    "type": "image",
                    "mime_type": media_type,
                    "data": encoded,
                }
            )
        aspect_ratio = normalize_image_aspect_ratio(request.aspect_ratio)
        resolution = normalize_image_resolution(request.resolution, aspect_ratio)
        response_format: dict[str, Any] = {
            "type": "image",
            "mime_type": GOOGLE_AI_IMAGE_RESPONSE_MIME_TYPE,
            "aspect_ratio": aspect_ratio,
            "image_size": self._image_size(resolution),
        }
        return {
            "model": request.model,
            "input": input_blocks if len(input_blocks) > 1 else prompt,
            "response_format": response_format,
        }

    def _image_size(self, resolution: str | None) -> str:
        settings = get_settings()
        if getattr(settings, "google_ai_image_model", "") == "gemini-3.1-flash-lite-image":
            return "1K"
        value = str(resolution or settings.google_ai_image_size or "1K").strip()
        if "x" in value.lower():
            dimensions = [int(part) for part in value.lower().split("x") if part.isdigit()]
            width = max(dimensions) if dimensions else 0
            if width >= 3840:
                return "4K"
            if width >= 1920:
                return "2K"
            return "1K"
        normalized = value.upper()
        if normalized in {"0.5K", "512PX"}:
            return "512px"
        return normalized if normalized in {"1K", "2K", "4K"} else "1K"

    @staticmethod
    def _normalized_aspect_ratio(value: str) -> str:
        return normalize_image_aspect_ratio(value)

    def _post_json(
        self,
        base_url: str,
        api_key: str,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        parsed: object
        for attempt in range(DEFAULT_GOOGLE_AI_IMAGE_MAX_ATTEMPTS):
            request = urllib.request.Request(
                f"{base_url.rstrip('/')}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                    "X-Correlation-ID": current_correlation_id() or "",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=DEFAULT_GOOGLE_AI_IMAGE_TIMEOUT_SECONDS,
                ) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if self._should_retry(attempt, exc.code):
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise RuntimeError(
                    f"{self.display_name} HTTP {exc.code}: {redact_secrets(detail)}"
                ) from exc
            except urllib.error.URLError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"{self.display_name} network error: {redact_secrets(exc.reason)}"
                ) from exc
            except TimeoutError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"{self.display_name} timeout ao aguardar resposta") from exc
            except OSError as exc:
                if self._should_retry(attempt):
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"{self.display_name} connection error: {redact_secrets(exc)}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{self.display_name} retornou JSON invalido") from exc
        else:
            raise RuntimeError(f"{self.display_name} excedeu tentativas de geracao")
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(f"{self.display_name} retornou erro: {redact_secrets(error)}")
        return parsed

    @staticmethod
    def _should_retry(attempt: int, status_code: int | None = None) -> bool:
        has_attempts_left = attempt < DEFAULT_GOOGLE_AI_IMAGE_MAX_ATTEMPTS - 1
        if not has_attempts_left:
            return False
        return status_code is None or status_code in TRANSIENT_GOOGLE_AI_HTTP_STATUS

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

    def _image_bytes(self, response: dict[str, Any]) -> tuple[bytes, str]:
        candidates = self._image_candidates(response)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            inline_data = self._inline_data(candidate)
            encoded = self._encoded_image(candidate, inline_data)
            if not isinstance(encoded, str) or not encoded.strip():
                continue
            media_type = str(
                candidate.get("mime_type")
                or candidate.get("mimeType")
                or candidate.get("media_type")
                or inline_data.get("mime_type")
                or inline_data.get("mimeType")
                or GOOGLE_AI_IMAGE_RESPONSE_MIME_TYPE
            )
            try:
                return base64.b64decode(encoded.encode("ascii"), validate=True), media_type
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError(f"{self.display_name} retornou imagem base64 invalida") from exc
        raise RuntimeError(f"{self.display_name} nao retornou imagem gerada")

    @staticmethod
    def _inline_data(candidate: dict[str, Any]) -> dict[str, Any]:
        for key in ("inlineData", "inline_data"):
            value = candidate.get(key)
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
        return {}

    @staticmethod
    def _encoded_image(candidate: dict[str, Any], inline_data: dict[str, Any]) -> object:
        return (
            candidate.get("data")
            or candidate.get("b64_json")
            or candidate.get("bytesBase64Encoded")
            or inline_data.get("data")
            or inline_data.get("bytesBase64Encoded")
        )

    def _image_candidates(self, response: dict[str, Any]) -> list[Any]:
        candidates: list[Any] = []
        for key in ("output_image", "image"):
            if key in response:
                candidates.append(response[key])
        for key in ("output", "outputs"):
            output = response.get(key)
            if isinstance(output, list):
                candidates.extend(output)
            if isinstance(output, dict):
                candidates.append(output)
        for step in response.get("steps", []) if isinstance(response.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            content = step.get("content")
            if isinstance(content, list):
                candidates.extend(content)
            if isinstance(content, dict):
                candidates.append(content)
            summary = step.get("summary")
            if isinstance(summary, list):
                candidates.extend(summary)
            if isinstance(summary, dict):
                candidates.append(summary)
        return candidates
