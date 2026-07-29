import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.image.omniroute import OmniRouteImageProvider
from app.providers.image.types import ImageGenerationRequest


@pytest.mark.provider
@pytest.mark.asyncio
async def test_omniroute_image_smoke_with_real_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("OMNIROUTE_SMOKE") != "1":
        pytest.skip("Defina OMNIROUTE_SMOKE=1 para executar smoke test real")
    api_key = os.getenv("OMNIROUTE_API_KEY")
    if not api_key:
        pytest.skip("OMNIROUTE_API_KEY não configurada para smoke test real")

    reference = tmp_path / "reference.png"
    reference.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8ffff3f0005fe02fea73581e70000000049454e44ae426082"
        )
    )
    output_dir = tmp_path / "generated"
    monkeypatch.setattr(
        "app.providers.image.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key=api_key,
            omniroute_base_url=os.getenv("OMNIROUTE_BASE_URL", "https://omnirouters.com/v1"),
            omniroute_image_model=os.getenv("OMNIROUTE_IMAGE_MODEL", "chatgpt-web/gpt-5.5"),
            local_storage_path=tmp_path,
        ),
    )

    result = await OmniRouteImageProvider().generate(
        ImageGenerationRequest(
            prompt=(
                "Retrato simples de personagem cinematografico, fundo neutro, "
                "sem texto, preservando a referencia de cor."
            ),
            target_id="smoke-character",
            view_type="front_portrait",
            output_dir=output_dir,
            references=[reference.as_posix()],
            model=os.getenv("OMNIROUTE_IMAGE_MODEL", "chatgpt-web/gpt-5.5"),
            aspect_ratio="1:1",
            resolution="1024x1024",
        )
    )

    assert result.provider == "omniroute"
    assert result.file_path.exists()
    assert result.file_path.stat().st_size > 0
