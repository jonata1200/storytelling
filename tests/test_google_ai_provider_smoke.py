import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.image.google_ai import GoogleAIImageProvider
from app.providers.image.types import ImageGenerationRequest
from app.providers.video.google_ai import GoogleAIVideoProvider
from app.providers.video.types import VideoRequest


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_google_ai_image_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_GOOGLE_AI_IMAGE_SMOKE") != "1" or not os.getenv("GOOGLE_AI_API_KEY"):
        pytest.skip("Defina RUN_GOOGLE_AI_IMAGE_SMOKE=1 e GOOGLE_AI_API_KEY para rodar.")

    settings = Settings(
        google_ai_api_key=os.environ["GOOGLE_AI_API_KEY"],
        google_ai_base_url=os.getenv(
            "GOOGLE_AI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ),
        google_ai_image_model=os.getenv(
            "GOOGLE_AI_IMAGE_MODEL",
            "gemini-3.1-flash-lite-image",
        ),
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.image.google_ai.get_settings", lambda: settings)

    result = await GoogleAIImageProvider().generate(
        ImageGenerationRequest(
            prompt="A simple cinematic vertical keyframe of a moonlit street, no text.",
            target_id="smoke",
            view_type="keyframe",
            output_dir=tmp_path,
            aspect_ratio="9:16",
            model=settings.google_ai_image_model,
        )
    )

    assert result.file_path.exists()
    assert result.file_path.stat().st_size > 0


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_google_ai_video_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_GOOGLE_AI_VIDEO_SMOKE") != "1" or not os.getenv("GOOGLE_AI_API_KEY"):
        pytest.skip("Defina RUN_GOOGLE_AI_VIDEO_SMOKE=1 e GOOGLE_AI_API_KEY para rodar.")

    settings = Settings(
        google_ai_api_key=os.environ["GOOGLE_AI_API_KEY"],
        google_ai_base_url=os.getenv(
            "GOOGLE_AI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ),
        google_ai_video_model=os.getenv("GOOGLE_AI_VIDEO_MODEL", "veo-3.1-generate-preview"),
        google_ai_video_poll_interval_seconds=10,
        google_ai_video_poll_timeout_seconds=900,
        local_storage_path=tmp_path,
    )
    monkeypatch.setattr("app.providers.video.google_ai.get_settings", lambda: settings)

    result = await GoogleAIVideoProvider().generate_from_text(
        VideoRequest(
            prompt="A cinematic shot of a quiet moonlit street, no text or logos.",
            duration_seconds=4,
            aspect_ratio="9:16",
            resolution="720p",
            output_dir=tmp_path,
            model=settings.google_ai_video_model,
        )
    )

    assert result.file_path is not None
    assert result.file_path.exists()
    assert result.file_path.stat().st_size > 0
