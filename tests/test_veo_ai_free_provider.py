from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import app.providers.image.veo_ai_free as veo_image_module
import app.providers.video.veo_ai_free as veo_video_module
from app.config.settings import Settings
from app.providers.image.types import ImageGenerationRequest
from app.providers.veo_free.browser import VeoFreeBrowserClient, VeoFreeGeneratedMedia
from app.providers.veo_free.session import save_cookie_bundle
from app.providers.video.types import VideoRequest


class _FakeVeoClient(VeoFreeBrowserClient):
    async def generate_image(self, payload: dict) -> VeoFreeGeneratedMedia:
        return VeoFreeGeneratedMedia(
            media_bytes=b"fake-png",
            content_type="image/png",
            external_job_id="veo-image-1",
            metadata={"payload": payload},
        )

    async def generate_video(self, payload: dict) -> VeoFreeGeneratedMedia:
        return VeoFreeGeneratedMedia(
            media_bytes=b"fake-mp4",
            content_type="video/mp4",
            external_job_id="veo-video-1",
            metadata={"payload": payload},
        )


def _connected_settings(tmp_path: Path) -> Settings:
    session_path = tmp_path / "session.json"
    save_cookie_bundle(
        [
            {
                "name": "session",
                "value": "secret-cookie",
                "expires": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            }
        ],
        session_path,
    )
    return Settings(
        veo_ai_free_enabled=True,
        veo_ai_free_session_path=session_path,
        veo_ai_free_image_model="veo-ai-free/image",
        veo_ai_free_video_model="veo-ai-free/video",
    )


@pytest.mark.asyncio
async def test_veo_ai_free_image_provider_saves_generated_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(veo_image_module, "get_settings", lambda: _connected_settings(tmp_path))
    provider = veo_image_module.VeoAiFreeImageProvider(_FakeVeoClient())

    result = await provider.generate(
        ImageGenerationRequest(
            prompt="portrait",
            target_id="char",
            view_type="front",
            output_dir=tmp_path,
            model="veo-ai-free/image",
        )
    )

    assert result.provider == "veo_ai_free"
    assert result.content_type == "image/png"
    assert result.file_path.read_bytes() == b"fake-png"


@pytest.mark.asyncio
async def test_veo_ai_free_video_provider_saves_generated_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(veo_video_module, "get_settings", lambda: _connected_settings(tmp_path))
    provider = veo_video_module.VeoAiFreeVideoProvider(_FakeVeoClient())

    result = await provider.generate_from_text(
        VideoRequest(
            prompt="camera move",
            duration_seconds=5,
            output_dir=tmp_path,
            model="veo-ai-free/video",
        )
    )

    assert result.provider == "veo_ai_free"
    assert result.file_path is not None
    assert result.file_path.read_bytes() == b"fake-mp4"
    assert result.metadata["experimental"] is True


@pytest.mark.asyncio
async def test_veo_ai_free_provider_requires_connected_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        veo_image_module,
        "get_settings",
        lambda: Settings(veo_ai_free_enabled=True, veo_ai_free_session_path=tmp_path / "missing"),
    )
    provider = veo_image_module.VeoAiFreeImageProvider(_FakeVeoClient())

    with pytest.raises(RuntimeError, match="Reconecte o Veo AI Free"):
        await provider.generate(
            ImageGenerationRequest(
                prompt="portrait",
                target_id="char",
                view_type="front",
                output_dir=tmp_path,
                model="veo-ai-free/image",
            )
        )


@pytest.mark.asyncio
async def test_default_veo_browser_client_is_actionable() -> None:
    with pytest.raises(RuntimeError, match="descoberta manual"):
        await VeoFreeBrowserClient().generate_image({"prompt": "x"})
