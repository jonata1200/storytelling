import base64
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.providers.image.meta as meta_module
from app.config.settings import Settings
from app.providers.image.meta import MetaImageProvider
from app.providers.image.types import ImageGenerationRequest

PNG = b"\x89PNG\r\n\x1a\n" + b"image-content"


class _Response:
    headers = {"content-type": "application/json"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        local_storage_path=tmp_path,
        image_provider="meta",
        meta_image_integration_mode="api",
        meta_api_key="meta-image-secret",
        meta_image_endpoint="https://images.meta.example/v1/generations",
        meta_image_model="muse-image",
    )


@pytest.mark.asyncio
async def test_meta_image_provider_writes_original_and_maps_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(meta_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.providers.image.types.get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response(
            {
                "id": "generation-1",
                "model": "muse-image",
                "data": [
                    {
                        "b64_json": base64.b64encode(PNG).decode(),
                        "seed": 42,
                    }
                ],
                "usage": {"cost": "0.0123"},
            }
        )

    monkeypatch.setattr(meta_module.urllib.request, "urlopen", fake_urlopen)
    result = await MetaImageProvider().generate(
        ImageGenerationRequest(
            prompt="Retrato frontal",
            model="muse-image",
            output_dir=tmp_path / "generated_images" / "project",
        )
    )

    assert captured["url"] == "https://images.meta.example/v1/generations"
    assert captured["auth"] == "Bearer meta-image-secret"
    assert captured["body"]["response_format"] == "b64_json"
    assert result.file_path.read_bytes() == PNG
    assert result.content_type == "image/png"
    assert result.external_job_id == "generation-1"
    assert result.metadata["seed"] == 42
    assert result.estimated_cost == "0.0123"


@pytest.mark.asyncio
async def test_meta_image_provider_retries_429_and_rejects_invalid_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(meta_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.providers.image.types.get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    calls = 0

    def throttled(_request: Any, timeout: float) -> _Response:
        _ = timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                settings.meta_image_endpoint,
                429,
                "rate limit",
                Message(),
                io.BytesIO(b'{"error":"rate limit"}'),
            )
        return _Response(
            {"data": [{"b64_json": base64.b64encode(b"not-image").decode()}]}
        )

    monkeypatch.setattr(meta_module.urllib.request, "urlopen", throttled)
    monkeypatch.setattr(meta_module.time, "sleep", lambda _delay: None)
    with pytest.raises(RuntimeError, match="não é uma imagem"):
        await MetaImageProvider().generate(
            ImageGenerationRequest(
                prompt="Imagem",
                model="muse-image",
                output_dir=tmp_path / "generated_images",
            )
        )
    assert calls == 2


def test_meta_image_provider_requires_validated_official_endpoint(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.meta_image_endpoint = ""
    original = meta_module.get_settings
    meta_module.get_settings = lambda: settings
    try:
        request = ImageGenerationRequest.model_construct(
            prompt="Imagem", model="muse-image", output_dir=tmp_path
        )
        with pytest.raises(ValueError, match="META_IMAGE_ENDPOINT"):
            MetaImageProvider()._generate(request)
    finally:
        meta_module.get_settings = original
