from pathlib import Path

import pytest

from app.core.enums import GenerationJobStatus
from app.providers.video.mock import MockVideoProvider
from app.providers.video.types import VideoRequest


@pytest.mark.asyncio
async def test_mock_video_provider_generates_mockvideo_file(tmp_path: Path) -> None:
    provider = MockVideoProvider()

    result = await provider.generate_from_image(
        VideoRequest(
            prompt="Storyboard emotional close up",
            duration_seconds=4,
            source_image_uri="asset://frame",
            output_dir=tmp_path,
        )
    )

    assert result.status == GenerationJobStatus.SUCCEEDED
    assert result.file_path is not None
    assert result.file_path.exists()
    assert result.sha256 is not None
    assert provider.capabilities.image_to_video
