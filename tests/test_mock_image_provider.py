from pathlib import Path

import pytest

from app.providers.image.mock import MockImageProvider
from app.providers.image.types import ImageGenerationRequest


@pytest.mark.asyncio
async def test_mock_image_provider_creates_svg_reference(tmp_path: Path) -> None:
    provider = MockImageProvider()

    result = await provider.generate(
        ImageGenerationRequest(
            prompt="Personagem principal, retrato frontal",
            target_id="char_test",
            view_type="front_portrait",
            output_dir=tmp_path,
            aspect_ratio="16:9",
        )
    )

    assert result.file_path.exists()
    assert result.content_type == "image/svg+xml"
    assert len(result.sha256) == 64
    assert "front_portrait" in result.file_path.name
    svg = result.file_path.read_text(encoding="utf-8")
    assert 'width="1920" height="1080"' in svg
