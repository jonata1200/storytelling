from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.providers.video import types as video_types
from app.video_generation import continuous_generation


@pytest.mark.asyncio
async def test_first_video_segment_uses_prompt_without_synthetic_frames(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        continuous_generation,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_video_model="bytedance/seedance-2.0-mini",
            openrouter_video_generate_audio=True,
            local_storage_path=tmp_path,
        ),
    )
    monkeypatch.setattr(
        video_types,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    segment = SimpleNamespace(
        source_frame_asset_id=None,
        prompt="Travelling lento enquanto a personagem atravessa o corredor.",
        duration_seconds=8,
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

    assert request.frame_images == []
    assert request.input_references == []
    assert request.prompt == segment.prompt
