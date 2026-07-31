import asyncio
import base64
import binascii
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, cast
from urllib.parse import quote, urlparse
from uuid import uuid4

from app.config.provider_policy import (
    ensure_provider_api_key,
    provider_channel_base_url,
    provider_requires_api_key,
    validate_model_name,
)
from app.config.settings import get_settings
from app.observability.middleware import current_correlation_id
from app.observability.redaction import redact_secrets
from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult
from app.providers.media_utils import extension_from_media_type, local_uri_to_data_url

DEFAULT_IMAGE_TIMEOUT_SECONDS = 360
MIN_IMAGE_TIMEOUT_SECONDS = 30
MAX_IMAGE_TIMEOUT_SECONDS = 900


class NvidiaNimImageProvider:
    provider_name = "nvidia_nim"
    display_name = "NVIDIA NIM Images"

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
        if provider_requires_api_key(settings, self.provider_name):
            ensure_provider_api_key(
                settings.nvidia_nim_api_key,
                self.provider_name,
                "NVIDIA_NIM_API_KEY",
            )
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nEvite: {request.negative_prompt}"
        body = self._request_body(request, prompt)
        response = self._post_image_generation(settings, request.model, body)
        image_bytes, media_type = self._image_bytes(response)

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

    def _request_body(self, request: ImageGenerationRequest, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }
        if request.resolution:
            body["size"] = self._normalized_size(request.resolution)
        elif request.aspect_ratio:
            body["size"] = self._size_for_aspect_ratio(request.aspect_ratio)
        if request.references:
            body["image"] = local_uri_to_data_url(request.references[0])
        return body

    def _post_image_generation(
        self,
        settings: Any,
        model: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        base_url = provider_channel_base_url(settings, self.provider_name, "image")
        if "/genai" in base_url.casefold():
            native_body = self._native_body(body)
            return self._post_json(self._native_model_url(base_url, model), native_body, settings)
        return self._post_json(f"{base_url.rstrip('/')}/images/generations", body, settings)

    def _native_body(self, body: dict[str, Any]) -> dict[str, Any]:
        native_body: dict[str, Any] = {
            "prompt": body["prompt"],
            "seed": 0,
        }
        if image := body.get("image"):
            native_body["image"] = image
        width, height = self._width_height_from_size(str(body.get("size") or ""))
        if width and height:
            native_body["width"] = width
            native_body["height"] = height
        return native_body

    def _post_json(self, url: str, body: dict[str, Any], settings: Any) -> dict[str, Any]:
        api_key = self._api_key_for_request(settings)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Correlation-ID": current_correlation_id() or "",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._request_timeout_seconds(settings),
            ) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                status_code = getattr(response, "status", 200)
                response_headers = response.headers
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.display_name} HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.display_name} network error: {redact_secrets(exc.reason)}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(f"{self.display_name} timeout ao aguardar resposta") from exc
        except OSError as exc:
            raise RuntimeError(
                f"{self.display_name} connection error: {redact_secrets(exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{self.display_name} retornou resposta HTTP que nao e JSON valido"
            ) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{self.display_name} retornou resposta fora do formato esperado")
        parsed = cast(dict[str, Any], parsed)
        if status_code == 202:
            parsed = self._poll_status(url, parsed, response_headers, settings)
        if error := parsed.get("error"):
            raise RuntimeError(f"{self.display_name} retornou erro: {redact_secrets(error)}")
        return parsed

    def _api_key_for_request(self, settings: Any) -> str | None:
        if provider_requires_api_key(settings, self.provider_name):
            return ensure_provider_api_key(
                settings.nvidia_nim_api_key,
                self.provider_name,
                "NVIDIA_NIM_API_KEY",
            )
        return str(getattr(settings, "nvidia_nim_api_key", "") or "").strip() or None

    def _poll_status(
        self,
        request_url: str,
        initial_payload: dict[str, Any],
        headers: Any,
        settings: Any,
    ) -> dict[str, Any]:
        request_id = self._request_id(initial_payload, headers)
        if not request_id:
            return initial_payload
        status_url = self._status_url(request_url, request_id)
        deadline = time.monotonic() + self._request_timeout_seconds(settings)
        api_key = self._api_key_for_request(settings)
        while time.monotonic() < deadline:
            time.sleep(2)
            request_headers = {"Accept": "application/json"}
            if api_key:
                request_headers["Authorization"] = f"Bearer {api_key}"
            request = urllib.request.Request(status_url, headers=request_headers, method="GET")
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self._request_timeout_seconds(settings),
                ) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                    status_code = getattr(response, "status", 200)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"{self.display_name} status HTTP {exc.code}: {redact_secrets(detail)}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"{self.display_name} status network error: {redact_secrets(exc.reason)}"
                ) from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{self.display_name} status retornou resposta que nao e JSON valido"
                ) from exc
            if not isinstance(parsed, dict):
                raise RuntimeError(
                    f"{self.display_name} status retornou resposta fora do formato esperado"
                )
            parsed = cast(dict[str, Any], parsed)
            if parsed.get("error"):
                return parsed
            if self._has_image(parsed):
                return parsed
            provider_status = str(
                parsed.get("status") or parsed.get("nvcf-status") or ""
            ).casefold()
            if status_code != 202 and provider_status in {"fulfilled", "completed", "succeeded"}:
                return parsed
            if status_code != 202 and provider_status in {"errored", "failed", "cancelled"}:
                raise RuntimeError(
                    f"{self.display_name} status retornou falha: {redact_secrets(parsed)}"
                )
        raise RuntimeError(f"{self.display_name} timeout ao aguardar imagem gerada")

    @staticmethod
    def _request_id(payload: dict[str, Any], headers: Any) -> str:
        for key in ("requestId", "request_id", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("NVCF-REQID", "nvcf-reqid"):
            value = headers.get(key) if hasattr(headers, "get") else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _status_url(request_url: str, request_id: str) -> str:
        parsed = urlparse(request_url)
        prefix = "/v1/"
        if prefix in parsed.path:
            base_path = parsed.path.split(prefix, 1)[0]
            return f"{parsed.scheme}://{parsed.netloc}{base_path}/v1/status/{quote(request_id)}"
        return f"{parsed.scheme}://{parsed.netloc}/v1/status/{quote(request_id)}"

    @staticmethod
    def _has_image(payload: dict[str, Any]) -> bool:
        data = payload.get("data")
        artifacts = payload.get("artifacts")
        return bool(
            (isinstance(data, list) and data)
            or (isinstance(artifacts, list) and artifacts)
        )

    def _image_bytes(self, response: dict[str, Any]) -> tuple[bytes, str]:
        data = response.get("data")
        if isinstance(data, list) and data:
            first_image = data[0]
            if isinstance(first_image, dict):
                return self._image_item_bytes(first_image, "image/png")

        artifacts = response.get("artifacts")
        if isinstance(artifacts, list) and artifacts:
            first_artifact = artifacts[0]
            if isinstance(first_artifact, dict):
                return self._image_item_bytes(first_artifact, "image/jpeg")

        raise RuntimeError(f"{self.display_name} retornou resposta sem imagem")

    def _image_item_bytes(
        self,
        item: dict[str, Any],
        fallback_media_type: str,
    ) -> tuple[bytes, str]:
        media_type = str(
            item.get("media_type")
            or item.get("mime_type")
            or item.get("content_type")
            or fallback_media_type
        )
        encoded = item.get("b64_json") or item.get("base64")
        if isinstance(encoded, str) and encoded:
            try:
                return base64.b64decode(encoded.encode("ascii"), validate=True), media_type
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError(f"{self.display_name} retornou imagem base64 invalida") from exc

        image_url = item.get("url") or item.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if isinstance(image_url, str) and image_url:
            return self._download_image(image_url, media_type)
        raise RuntimeError(f"{self.display_name} nao retornou base64 nem URL de imagem")

    def _download_image(self, url: str, fallback_media_type: str) -> tuple[bytes, str]:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_IMAGE_TIMEOUT_SECONDS) as response:
                content: bytes = response.read()
                content_type = response.headers.get_content_type() or fallback_media_type
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{self.display_name} download HTTP {exc.code}: {redact_secrets(detail)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.display_name} download network error: {redact_secrets(exc.reason)}"
            ) from exc
        return content, content_type

    @staticmethod
    def _native_model_url(base_url: str, model: str) -> str:
        return f"{base_url.rstrip('/')}/{quote(model.strip(), safe='/.-_')}"

    @staticmethod
    def _normalized_size(value: str) -> str:
        size = str(value or "").strip()
        return size.lower().replace("*", "x")

    @staticmethod
    def _width_height_from_size(value: str) -> tuple[int | None, int | None]:
        size = value.lower().replace("*", "x")
        if "x" not in size:
            return None, None
        raw_width, raw_height = size.split("x", 1)
        try:
            return int(raw_width), int(raw_height)
        except ValueError:
            return None, None

    @staticmethod
    def _size_for_aspect_ratio(aspect_ratio: str) -> str:
        sizes = {
            "1:1": "1024x1024",
            "9:16": "768x1344",
            "16:9": "1344x768",
            "3:4": "896x1152",
            "4:3": "1152x896",
        }
        return sizes.get(str(aspect_ratio or "").strip(), "1024x1024")

    @staticmethod
    def _request_timeout_seconds(settings: Any) -> int:
        try:
            timeout = int(
                getattr(settings, "nvidia_nim_image_timeout_seconds", None)
                or DEFAULT_IMAGE_TIMEOUT_SECONDS
            )
        except (TypeError, ValueError):
            timeout = DEFAULT_IMAGE_TIMEOUT_SECONDS
        return max(MIN_IMAGE_TIMEOUT_SECONDS, min(MAX_IMAGE_TIMEOUT_SECONDS, timeout))
