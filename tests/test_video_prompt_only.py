from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.providers.video import types as video_types
from app.video_generation import continuous_generation


@pytest.mark.asyncio
async def test_video_request_uses_only_the_initial_frame(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        continuous_generation,
        "get_settings",
        lambda: SimpleNamespace(
            video_provider="vibes",
            vibes_video_model="vibes",
            local_storage_path=tmp_path,
        ),
    )
    monkeypatch.setattr(
        video_types,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    initial_asset_id = uuid4()
    final_asset_id = uuid4()

    async def fake_asset_data_url(_session: object, asset_id: object) -> str | None:
        return "data:image/png;base64,AA==" if asset_id == initial_asset_id else None

    monkeypatch.setattr(continuous_generation, "_asset_data_url", fake_asset_data_url)
    segment = SimpleNamespace(
        source_frame_asset_id=initial_asset_id,
        final_frame_asset_id=final_asset_id,
        prompt="Travelling lento enquanto a personagem atravessa o corredor.",
        duration_seconds=8,
        metadata_json={},
    )
    production = SimpleNamespace(
        video_model="manual_package",
        aspect_ratio="9:16",
        video_resolution="720p",
    )

    request = await continuous_generation._build_video_request(
        object(),  # type: ignore[arg-type]
        uuid4(),
        segment,  # type: ignore[arg-type]
        production,
    )

    assert len(request.frame_images) == 1
    assert request.frame_images[0].frame_type == "first_frame"
    assert request.input_references == []
    assert request.prompt == segment.prompt
    assert "Comece exatamente no frame inicial" not in request.prompt
    assert "9:16" not in request.prompt
