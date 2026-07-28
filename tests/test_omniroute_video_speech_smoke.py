import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.speech.omniroute import OmniRouteSpeechProvider
from app.providers.speech.types import SpeechRequest
from app.providers.video.omniroute import OmniRouteVideoProvider
from app.providers.video.types import VideoRequest


def _write_reference_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8ffff3f0005fe02fea73581e70000000049454e44ae426082"
        )
    )


@pytest.mark.provider
@pytest.mark.asyncio
async def test_omniroute_video_smoke_image_to_video_9_16(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("OMNIROUTE_VIDEO_SMOKE") != "1":
        pytest.skip("Defina OMNIROUTE_VIDEO_SMOKE=1 para executar smoke test real de vídeo")
    api_key = os.getenv("OMNIROUTE_API_KEY")
    if not api_key:
        pytest.skip("OMNIROUTE_API_KEY não configurada para smoke test real de vídeo")

    first_frame = tmp_path / "first_frame.png"
    _write_reference_png(first_frame)
    model = os.getenv("OMNIROUTE_VIDEO_MODEL", "Kling-3.0-omni")
    monkeypatch.setattr(
        "app.providers.video.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key=api_key,
            omniroute_base_url=os.getenv("OMNIROUTE_BASE_URL", "https://omnirouters.com/v1"),
            omniroute_video_model=model,
            local_storage_path=tmp_path,
        ),
    )
    monkeypatch.setattr(
        "app.providers.media_utils.get_settings",
        lambda: Settings(local_storage_path=tmp_path),
    )

    result = await OmniRouteVideoProvider().generate_from_image(
        VideoRequest(
            prompt="Um personagem olha para a câmera e respira em silêncio, sem texto.",
            duration_seconds=5,
            source_image_uri=first_frame.as_posix(),
            output_dir=tmp_path / "video",
            model=model,
            aspect_ratio="9:16",
            size="1080x1920",
        )
    )

    assert result.provider == "omniroute"
    assert result.file_path is not None
    assert result.file_path.exists()
    assert result.file_path.stat().st_size > 0
    assert result.metadata["native_audio"] is False


@pytest.mark.provider
@pytest.mark.asyncio
async def test_omniroute_speech_smoke_two_stable_character_voices(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("OMNIROUTE_SPEECH_SMOKE") != "1":
        pytest.skip("Defina OMNIROUTE_SPEECH_SMOKE=1 para executar smoke test real de speech")
    api_key = os.getenv("OMNIROUTE_API_KEY")
    model = os.getenv("OMNIROUTE_SPEECH_MODEL") or os.getenv("SPEECH_MODEL")
    if not api_key:
        pytest.skip("OMNIROUTE_API_KEY não configurada para smoke test real de speech")
    if not model:
        pytest.skip("OMNIROUTE_SPEECH_MODEL ou SPEECH_MODEL não configurado")

    monkeypatch.setattr(
        "app.providers.speech.omniroute.get_settings",
        lambda: Settings(
            omniroute_api_key=api_key,
            omniroute_base_url=os.getenv("OMNIROUTE_BASE_URL", "https://omnirouters.com/v1"),
            omniroute_speech_model=model,
            speech_voice=os.getenv("OMNIROUTE_SPEECH_VOICE", "alloy"),
        ),
    )

    provider = OmniRouteSpeechProvider()
    alice = await provider.synthesize(
        SpeechRequest(
            text="Eu volto antes do anoitecer.",
            voice_profile_id=os.getenv("OMNIROUTE_SPEECH_VOICE_A", "alloy"),
            output_dir=tmp_path / "speech",
            model=model,
        )
    )
    bruno = await provider.synthesize(
        SpeechRequest(
            text="Então deixe a porta aberta.",
            voice_profile_id=os.getenv("OMNIROUTE_SPEECH_VOICE_B", "echo"),
            output_dir=tmp_path / "speech",
            model=model,
        )
    )

    assert alice.provider == "omniroute"
    assert bruno.provider == "omniroute"
    assert alice.file_path.exists()
    assert bruno.file_path.exists()
    assert alice.file_path.stat().st_size > 0
    assert bruno.file_path.stat().st_size > 0
