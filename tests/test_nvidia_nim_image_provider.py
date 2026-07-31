import base64
import json
from pathlib import Path
from typing import Any

import pytest

import app.providers.image.nvidia_nim as nvidia_image_module
from app.config.settings import Settings
from app.providers.image.nvidia_nim import NvidiaNimImageProvider
from app.providers.image.types import ImageGenerationRequest


class _JsonResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _request(tmp_path: Path, model: str = "qwen/qwen-image") -> ImageGenerationRequest:
    return ImageGenerationRequest(
        prompt="Um cartaz cinematografico com titulo legivel",
        target_id="scene-1",
        view_type="poster",
        output_dir=tmp_path,
        resolution="1024x1024",
        model=model,
    )


@pytest.mark.asyncio
async def test_nvidia_nim_image_provider_uses_openai_compatible_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any], str | None]] = []
    encoded_image = base64.b64encode(b"image-bytes").decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, body, request.get_header("Authorization")))
        return _JsonResponse(
            {"data": [{"b64_json": encoded_image, "content_type": "image/png"}]}
        )

    monkeypatch.setattr(
        nvidia_image_module,
        "get_settings",
        lambda: Settings(
            nvidia_nim_api_key="nv-secret",
            nvidia_nim_image_base_url="http://localhost:8000/v1",
        ),
    )
    monkeypatch.setattr(nvidia_image_module.urllib.request, "urlopen", fake_urlopen)

    result = await NvidiaNimImageProvider().generate(_request(tmp_path))

    assert result.provider == "nvidia_nim"
    assert result.model == "qwen/qwen-image"
    assert result.file_path.read_bytes() == b"image-bytes"
    assert calls == [
        (
            "http://localhost:8000/v1/images/generations",
            {
                "model": "qwen/qwen-image",
                "prompt": "Um cartaz cinematografico com titulo legivel",
                "n": 1,
                "response_format": "b64_json",
                "size": "1024x1024",
            },
            "Bearer nv-secret",
        )
    ]


@pytest.mark.asyncio
async def test_nvidia_nim_image_provider_polls_async_hosted_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    encoded_image = base64.b64encode(b"async-image").decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        del timeout
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            return _JsonResponse({"requestId": "req-123"}, status=202)
        return _JsonResponse({"artifacts": [{"base64": encoded_image}]})

    monkeypatch.setattr(
        nvidia_image_module,
        "get_settings",
        lambda: Settings(
            nvidia_nim_api_key="nv-secret",
            nvidia_nim_image_base_url="https://ai.api.nvidia.com/v1/genai",
        ),
    )
    monkeypatch.setattr(nvidia_image_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(nvidia_image_module.time, "sleep", lambda _seconds: None)

    result = await NvidiaNimImageProvider().generate(_request(tmp_path))

    assert result.file_path.read_bytes() == b"async-image"
    assert calls == [
        ("POST", "https://ai.api.nvidia.com/v1/genai/qwen/qwen-image"),
        ("GET", "https://ai.api.nvidia.com/v1/status/req-123"),
    ]


@pytest.mark.asyncio
async def test_nvidia_nim_image_provider_can_use_native_genai_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    encoded_image = base64.b64encode(b"native-image").decode("ascii")

    def fake_urlopen(request: Any, timeout: int) -> _JsonResponse:
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, body))
        return _JsonResponse({"artifacts": [{"base64": encoded_image}]})

    monkeypatch.setattr(
        nvidia_image_module,
        "get_settings",
        lambda: Settings(
            nvidia_nim_api_key="nv-secret",
            nvidia_nim_image_base_url="https://ai.api.nvidia.com/v1/genai",
        ),
    )
    monkeypatch.setattr(nvidia_image_module.urllib.request, "urlopen", fake_urlopen)

    result = await NvidiaNimImageProvider().generate(
        _request(tmp_path, model="black-forest-labs/flux.1-schnell")
    )

    assert result.file_path.read_bytes() == b"native-image"
    assert calls == [
        (
            "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell",
            {
                "prompt": "Um cartaz cinematografico com titulo legivel",
                "seed": 0,
                "width": 1024,
                "height": 1024,
            },
        )
    ]


@pytest.mark.asyncio
async def test_nvidia_nim_image_provider_requires_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        nvidia_image_module,
        "get_settings",
        lambda: Settings(nvidia_nim_api_key=None),
    )

    with pytest.raises(ValueError, match="NVIDIA_NIM_API_KEY"):
        await NvidiaNimImageProvider().generate(_request(tmp_path))
