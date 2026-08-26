import base64
import os
from uuid import uuid4

import pytest

from app.config.provider_policy import provider_model
from app.config.settings import get_settings
from app.providers.image.types import ImageGenerationRequest, ImageReference
from app.providers.registry import resolve_image_provider
from app.providers.storage import generated_output_dir

TINY_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\nreference"
).decode()


@pytest.mark.provider
@pytest.mark.smoke
@pytest.mark.skipif(
    os.getenv("STORYTELLING_META_IMAGE_SMOKE") != "1",
    reason="Set STORYTELLING_META_IMAGE_SMOKE=1 to call the real Meta image provider.",
)
@pytest.mark.parametrize(
    ("case", "prompt", "reference_count"),
    [
        ("character", "Retrato frontal canônico de personagem adulta brasileira.", 0),
        ("location", "Plano geral canônico de uma sala brasileira acolhedora.", 0),
        ("multiple_references", "Componha a mesma pessoa no mesmo ambiente.", 2),
    ],
)
@pytest.mark.asyncio
async def test_meta_image_real_smoke(
    case: str, prompt: str, reference_count: int
) -> None:
    settings = get_settings()
    provider = resolve_image_provider(settings, "meta")
    references = [
        ImageReference(uri=TINY_PNG_DATA_URL, role=f"reference_{index}")
        for index in range(reference_count)
    ]
    result = await provider.generate(
        ImageGenerationRequest(
            prompt=prompt,
            model=provider_model(settings, "meta", "image"),
            aspect_ratio="9:16",
            references=references,
            output_dir=generated_output_dir(
                "image", uuid4(), settings.local_storage_path
            ),
            metadata={"smoke_case": case},
        )
    )

    assert result.provider == "meta"
    assert result.file_path.is_file()
    assert result.content_type.startswith("image/")
