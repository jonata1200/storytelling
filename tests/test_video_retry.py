from uuid import uuid4

from app.providers.video.mock import MockVideoProvider
from app.storyboards.models import StoryboardFrame
from app.video_generation.retry import exponential_backoff_seconds
from app.video_generation.service import (
    _video_request_fingerprint,
    video_generation_validation_errors,
    video_idempotency_key,
)


def test_exponential_backoff_caps_delay() -> None:
    assert exponential_backoff_seconds(1, base_seconds=2, cap_seconds=10) == 2
    assert exponential_backoff_seconds(3, base_seconds=2, cap_seconds=10) == 8
    assert exponential_backoff_seconds(10, base_seconds=2, cap_seconds=10) == 10


def test_video_idempotency_key_changes_when_frame_fingerprint_changes() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=uuid4(),
        duration_seconds=5,
        prompt="Prompt de storyboard completo para video vertical.",
        metadata_json={"frame_fingerprint": "frame-a"},
    )

    first_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
    )
    frame.metadata_json = {"frame_fingerprint": "frame-b"}
    second_fingerprint = _video_request_fingerprint(
        frame,
        "asset://frame-a",
        "mock",
        "mock-video",
        "9:16",
        "1080x1920",
    )

    assert first_fingerprint != second_fingerprint
    assert video_idempotency_key(
        frame.id, 1, "mock", "mock-video", first_fingerprint
    ) != video_idempotency_key(frame.id, 1, "mock", "mock-video", second_fingerprint)


def test_video_generation_validation_reports_bad_frame_inputs() -> None:
    frame = StoryboardFrame(
        id=uuid4(),
        asset_id=None,
        duration_seconds=99,
        prompt="curto",
    )

    errors = video_generation_validation_errors(
        frame,
        None,
        MockVideoProvider(),
        "16:9",
    )

    assert "frame sem asset_id" in errors
    assert "prompt generico demais" in errors
    assert "imagem fonte ausente" in errors
    assert "duracao 99s nao suportada pelo provider" in errors
    assert "aspect_ratio 16:9 nao suportado pelo provider" in errors
