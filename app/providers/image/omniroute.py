import asyncio
import base64
import binascii
import hashlib
import json
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from app.config.provider_policy import ensure_provider_api_key, validate_model_name
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import extension_from_media_type, local_uri_to_data_url

DEFAULT_IMAGE_TIMEOUT_SECONDS = 360
MIN_IMAGE_TIMEOUT_SECONDS = 30
MAX_IMAGE_TIMEOUT_SECONDS = 900


class OmniRouteImageProvider:
    provider_name = "omniroute"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        request = request.model_copy(
            update={"model": validate_model_name(request.model, provider=self.provider_name)}
        )
        return await asyncio.to_thread(self._generate, request)

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
        ensure_provider_api_key(
            settings.omniroute_api_key,
            self.provider_name,
            "OMNIROUTE_API_KEY",
        )

        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": request.aspect_ratio,
            "output_format": "png",
            "response_format": "b64_json",
        }
        if request.resolution:
            body["size"] = self._normalized_size(request.resolution)
        if request.references:
            body["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {"url": local_uri_to_data_url(reference)},
                }
                for reference in request.references
            ]

        response, submitted_body = self._post_image_generation(body)
        image_bytes, media_type = self._image_bytes(response, submitted_body)
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
                return self._post_json("/images/generations", submitted_body), submitted_body
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
        retryable_parameters = ("output_format", "aspect_ratio", "n", "response_format")
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
    def _normalized_size(value: str) -> str:
        size = str(value or "").strip()
        if "x" in size.lower():
            return size.lower()
        named_sizes = {
            "512": "512x512",
            "1k": "1024x1024",
            "2k": "2048x2048",
            "4k": "4096x4096",
        }
        return named_sizes.get(size.casefold(), size)

    @staticmethod
    def _request_timeout_seconds(settings: Any) -> int:
        try:
            timeout = int(
                getattr(settings, "omniroute_image_timeout_seconds", None)
                or DEFAULT_IMAGE_TIMEOUT_SECONDS
            )
        except (TypeError, ValueError):
            timeout = DEFAULT_IMAGE_TIMEOUT_SECONDS
        return max(MIN_IMAGE_TIMEOUT_SECONDS, min(MAX_IMAGE_TIMEOUT_SECONDS, timeout))

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        api_key = ensure_provider_api_key(
            settings.omniroute_api_key,
            self.provider_name,
            "OMNIROUTE_API_KEY",
        )
        url = f"{settings.omniroute_base_url.rstrip('/')}{path}"
        timeout_seconds = self._request_timeout_seconds(settings)
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
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
                f"OmniRoute Images HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OmniRoute Images network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                "OmniRoute Images timeout ao aguardar resposta "
                f"após {timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"OmniRoute Images connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "OmniRoute Images retornou resposta HTTP que não é JSON válido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OmniRoute Images retornou resposta fora do formato esperado")
        if error := parsed.get("error"):
            raise RuntimeError(f"OmniRoute Images retornou erro: {redact_secrets(error)}")
        return parsed

    def _image_bytes(
        self,
        response: dict[str, Any],
        submitted_body: dict[str, Any],
    ) -> tuple[bytes, str]:
        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise RuntimeError("OmniRoute Images retornou resposta sem data")
        first_image = data[0]
        if not isinstance(first_image, dict):
            raise RuntimeError("OmniRoute Images retornou item fora do formato esperado")

        requested_format = str(submitted_body.get("output_format") or "png").lower()
        fallback_media_type = "image/jpeg" if requested_format in {"jpg", "jpeg"} else "image/png"
        media_type = str(
            first_image.get("media_type") or first_image.get("mime_type") or fallback_media_type
        )
        encoded_image = first_image.get("b64_json")
        if isinstance(encoded_image, str) and encoded_image:
            try:
                return base64.b64decode(encoded_image.encode("ascii"), validate=True), media_type
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("OmniRoute Images retornou b64_json inválido") from exc

        image_url = first_image.get("url") or first_image.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if isinstance(image_url, str) and image_url:
            return self._download_image(image_url, media_type)

        raise RuntimeError("OmniRoute Images não retornou b64_json nem URL de imagem")

    def _download_image(self, url: str, fallback_media_type: str) -> tuple[bytes, str]:
        settings = get_settings()
        timeout_seconds = self._request_timeout_seconds(settings)
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                content: bytes = response.read()
                content_type = response.headers.get_content_type() or fallback_media_type
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OmniRoute Images download HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OmniRoute Images download network error: {redact_secrets(exc.reason)}"
            ) from exc
        return content, content_type
