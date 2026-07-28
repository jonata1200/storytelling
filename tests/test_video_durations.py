import pytest

from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    validate_video_clip_duration,
    video_clip_durations,
)


def test_video_clip_durations_split_exact_five_minutes_into_seedance_clips() -> None:
    durations = video_clip_durations(300)

    assert len(durations) == 20
    assert sum(durations) == 300
    assert set(durations) == {15}


def test_video_clip_durations_distribute_remainder_without_invalid_tail() -> None:
    durations = video_clip_durations(301)

    assert sum(durations) == 301
    assert min(durations) >= VIDEO_CLIP_MIN_SECONDS
    assert max(durations) <= VIDEO_CLIP_MAX_SECONDS
    assert set(durations) == {14, 15}


def test_validate_video_clip_duration_rejects_outside_seedance_range() -> None:
    with pytest.raises(ValueError, match="4 a 15"):
        validate_video_clip_duration(16)
