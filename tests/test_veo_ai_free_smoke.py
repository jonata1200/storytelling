import os
from pathlib import Path

import pytest

from app.config.settings import get_settings
from app.providers.image.types import ImageGenerationRequest
from app.providers.image.veo_ai_free import VeoAiFreeImageProvider


@pytest.mark.skipif(
    os.getenv("RUN_VEO_FREE_SMOKE_TESTS") != "1",
    reason="Set RUN_VEO_FREE_SMOKE_TESTS=1 to manually exercise Veo AI Free.",
)
@pytest.mark.asyncio
async def test_veo_ai_free_image_smoke(tmp_path: Path) -> None:
    settings = get_settings()
    result = await VeoAiFreeImageProvider().generate(
        ImageGenerationRequest(
            prompt="simple cinematic test frame",
            target_id="smoke",
            view_type="front",
            output_dir=tmp_path,
            model=settings.veo_ai_free_image_model,
        )
    )

    assert result.provider == "veo_ai_free"
    assert result.file_path.is_file()
