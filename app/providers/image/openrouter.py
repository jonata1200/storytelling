import asyncio
import base64
import binascii
import hashlib
import json
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from app.config.model_policy import validate_openrouter_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import extension_from_media_type, local_uri_to_data_url

SOURCEFUL_RESOLUTIONS = {"512", "1K", "2K", "4K"}
DEFAULT_IMAGE_TIMEOUT_SECONDS = 360
MIN_IMAGE_TIMEOUT_SECONDS = 30
MAX_IMAGE_TIMEOUT_SECONDS = 900


class OpenRouterImageProvider:
    provider_name = "openrouter"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        request = request.model_copy(
            update={"model": validate_openrouter_model_name(request.model)}
        )
        response = await asyncio.to_thread(self._generate, request)
        return response

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
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY nao configurada")

        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": request.aspect_ratio,
            "output_format": "png",
        }
        if request.resolution:
            body["resolution"] = self._normalized_resolution(request.resolution)
        if request.references:
            body["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": local_uri_to_data_url(reference)},
                }
                for reference in request.references
            ]

        response, submitted_body = self._post_image_generation(body)
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise RuntimeError("OpenRouter Images retornou resposta sem data")
        first_image = data[0]
        if not isinstance(first_image, dict):
            raise RuntimeError("OpenRouter Images retornou item fora do formato esperado")
        encoded_image = first_image.get("b64_json")
        if not isinstance(encoded_image, str) or not encoded_image:
            raise RuntimeError("OpenRouter Images nao retornou b64_json")

        requested_format = str(submitted_body.get("output_format") or "png").lower()
        fallback_media_type = "image/jpeg" if requested_format in {"jpg", "jpeg"} else "image/png"
        media_type = str(first_image.get("media_type") or fallback_media_type)
        try:
            image_bytes = base64.b64decode(encoded_image.encode("ascii"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("OpenRouter Images retornou b64_json invalido") from exc
        request.output_dir.mkdir(parents=True, exist_ok=True)
        extension = extension_from_media_type(media_type)
        safe_view = request.view_type.replace("/", "_").replace("\\", "_")
        filename = f"{request.target_id}_{safe_view}_{uuid4().hex[:8]}{extension}"
        file_path = request.output_dir / filename
        file_path.write_bytes(image_bytes)
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        raw_usage = response.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return ImageResult(
            file_path=file_path,
            storage_uri=file_path.as_posix(),
            sha256=sha256,
            content_type=media_type,
            provider=self.provider_name,
            model=request.model,
            prompt=prompt,
            estimated_cost=str(usage.get("cost") or "0.000000"),
        )

    def _post_image_generation(self, body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        submitted_body = dict(body)
        attempted_bodies: set[str] = set()
        while True:
            attempt_key = json.dumps(submitted_body, sort_keys=True, default=str)
            attempted_bodies.add(attempt_key)
            try:
                return self._post_json("/images", submitted_body), submitted_body
            except RuntimeError as exc:
                retry_body = self._retry_body_for_image_error(exc, submitted_body)
                if retry_body is None:
                    raise
                retry_key = json.dumps(retry_body, sort_keys=True, default=str)
                if retry_key in attempted_bodies:
                    raise
                submitted_body = retry_body

    def _retry_body_for_image_error(
        self, exc: RuntimeError, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self._should_retry_with_jpeg(exc, body):
            retry_body = dict(body)
            retry_body["output_format"] = "jpeg"
            return retry_body

        unsupported_parameters = self._unsupported_parameters_from_error(exc, body)
        if unsupported_parameters:
            retry_body = dict(body)
            for parameter in unsupported_parameters:
                retry_body.pop(parameter, None)
            if retry_body != body:
                return retry_body

        if self._should_retry_without_n(exc, body):
            retry_body = dict(body)
            retry_body.pop("n", None)
            return retry_body

        return None

    @staticmethod
    def _should_retry_with_jpeg(exc: RuntimeError, body: dict[str, Any]) -> bool:
        message = str(exc).lower()
        return (
            str(body.get("output_format") or "").lower() != "jpeg"
            and "output_format" in message
            and "jpeg" in message
        )

    @staticmethod
    def _should_retry_without_n(exc: RuntimeError, body: dict[str, Any]) -> bool:
        message = str(exc).lower()
        return "n" in body and (
            " n " in message
            or '"n"' in message
            or "'n'" in message
            or " n:" in message
            or "parameter: n" in message
        )

    @classmethod
    def _unsupported_parameters_from_error(
        cls, exc: RuntimeError, body: dict[str, Any]
    ) -> list[str]:
        message = str(exc).lower()
        if not any(
            term in message
            for term in ("unsupported", "not supported", "unknown", "invalid option")
        ):
            return []
        retryable_parameters = ("output_format", "aspect_ratio", "n", "resolution")
        return [
            parameter
            for parameter in retryable_parameters
            if parameter in body and cls._error_mentions_parameter(message, parameter)
        ]

    @staticmethod
    def _error_mentions_parameter(message: str, parameter: str) -> bool:
        variants = {
            parameter,
            parameter.replace("_", " "),
            f'"{parameter}"',
            f"'{parameter}'",
            f"`{parameter}`",
            f"parameter: {parameter}",
        }
        return any(variant in message for variant in variants)

    @staticmethod
    def _normalized_resolution(value: str) -> str:
        resolution = str(value or "").strip()
        if resolution in SOURCEFUL_RESOLUTIONS:
            return resolution
        if "x" not in resolution.lower():
            return resolution
        try:
            width, height = (
                int(part.strip())
                for part in resolution.lower().split("x", 1)
            )
        except ValueError:
            return resolution
        longest_side = max(width, height)
        if longest_side <= 768:
            return "512"
        if longest_side <= 1280:
            return "1K"
        if longest_side <= 2048:
            return "2K"
        return "4K"

    @staticmethod
    def _request_timeout_seconds(settings: Any) -> int:
        try:
            timeout = int(
                getattr(settings, "openrouter_image_timeout_seconds", None)
                or DEFAULT_IMAGE_TIMEOUT_SECONDS
            )
        except (TypeError, ValueError):
            timeout = DEFAULT_IMAGE_TIMEOUT_SECONDS
        return max(MIN_IMAGE_TIMEOUT_SECONDS, min(MAX_IMAGE_TIMEOUT_SECONDS, timeout))

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        url = f"{settings.openrouter_base_url.rstrip('/')}{path}"
        timeout_seconds = self._request_timeout_seconds(settings)
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_site_url,
                "X-OpenRouter-Title": settings.openrouter_app_title,
                "X-Correlation-ID": current_correlation_id() or "",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenRouter Images HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OpenRouter Images network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                "OpenRouter Images timeout ao aguardar resposta "
                f"apos {timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"OpenRouter Images connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OpenRouter Images retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenRouter Images retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(
                f"OpenRouter Images retornou erro: {redact_secrets(error)}"
            )
        return parsed
