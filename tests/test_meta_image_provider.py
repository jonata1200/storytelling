import hashlib
from pathlib import Path
from typing import Any

import pytest

import app.providers.image.meta as meta_module
import app.providers.image.meta_playwright as meta_playwright_module
import app.providers.image.types as image_types_module
from app.config.settings import Settings
from app.providers.image.meta import MetaImageProvider
from app.providers.image.meta_browser import UnconfiguredMetaImageBrowserBackend
from app.providers.image.meta_playwright import PlaywrightMetaImageBrowserBackend
from app.providers.image.types import ImageGenerationRequest, ImageGenerationResult


class FakeMetaBrowserBackend:
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        payload = b"\x89PNG\r\n\x1a\nvalid-image"
        request.output_dir.mkdir(parents=True, exist_ok=True)
        path = request.output_dir / "result.png"
        path.write_bytes(payload)
        return ImageGenerationResult(
            file_path=path,
            storage_uri=path.as_posix(),
            sha256=hashlib.sha256(payload).hexdigest(),
            content_type="image/png",
            provider="meta",
            model=request.model,
            prompt=request.prompt,
            external_job_id="browser-generation-1",
        )


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "local_storage_path": tmp_path,
        "meta_image_integration_mode": "browser",
        "meta_browser_automation_enabled": True,
    }
    values.update(overrides or {})
    return Settings(_env_file=None, **values)


async def test_meta_image_uses_authorized_browser_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(meta_module, "get_settings", lambda: settings)
    monkeypatch.setattr(image_types_module, "get_settings", lambda: settings)
    result = await MetaImageProvider(FakeMetaBrowserBackend()).generate(
        ImageGenerationRequest(
            prompt="portrait",
            model="muse-image",
            output_dir=tmp_path / "generated",
        )
    )
    assert result.external_job_id == "browser-generation-1"
    assert result.file_path.read_bytes().startswith(b"\x89PNG")


async def test_meta_image_requires_explicit_browser_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, meta_browser_automation_enabled=False)
    monkeypatch.setattr(meta_module, "get_settings", lambda: settings)
    monkeypatch.setattr(image_types_module, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="META_BROWSER_AUTOMATION_ENABLED"):
        await MetaImageProvider(FakeMetaBrowserBackend()).generate(
            ImageGenerationRequest(
                prompt="portrait",
                model="muse-image",
                output_dir=tmp_path / "generated",
            )
        )


async def test_meta_image_fails_safe_without_installed_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(meta_module, "get_settings", lambda: settings)
    monkeypatch.setattr(image_types_module, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="Automação Meta Image não configurada"):
        await MetaImageProvider(UnconfiguredMetaImageBrowserBackend()).generate(
            ImageGenerationRequest(
                prompt="portrait",
                model="muse-image",
                output_dir=tmp_path / "generated",
            )
        )


async def test_playwright_backend_reuses_project_conversation_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    captured: dict = {}
    bridge_options: dict = {}
    generated = tmp_path / "generated" / "result.webp"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated")

    async def fake_bridge(_action: Any, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(payload)
        bridge_options.update(kwargs)
        return {
            "filePath": str(generated),
            "contentType": "image/webp",
            "jobId": "job-1",
            "conversationUrl": "https://www.meta.ai/c/project-chat",
        }

    monkeypatch.setattr(meta_playwright_module, "get_settings", lambda: settings)
    monkeypatch.setattr(meta_playwright_module, "run_browser_bridge", fake_bridge)
    monkeypatch.setattr(image_types_module, "get_settings", lambda: settings)
    result = await PlaywrightMetaImageBrowserBackend().generate(
        ImageGenerationRequest(
            prompt="personagem em pé",
            model="muse-image",
            output_dir=tmp_path / "generated",
            metadata={"project_id": "project-123"},
        )
    )

    assert captured["conversationKey"] == "project-123"
    assert captured["aspectRatio"] == "9:16"
    assert captured["timeoutSeconds"] == settings.meta_image_timeout_seconds
    assert captured["settledWaitSeconds"] == settings.meta_image_settled_wait_seconds
    assert (
        bridge_options["timeout_seconds"]
        == settings.meta_image_timeout_seconds
        + settings.meta_image_settled_wait_seconds
        + 60
    )
    assert result.metadata["conversation_url"] == "https://www.meta.ai/c/project-chat"
