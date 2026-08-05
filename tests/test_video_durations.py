import pytest

from app.video_generation.durations import (
    VIDEO_CLIP_ALLOWED_SECONDS,
    validate_video_clip_duration,
    video_clip_durations,
)


def test_video_clip_durations_split_exact_five_minutes_into_veo_clips() -> None:
    durations = video_clip_durations(300)

    assert len(durations) == 38
    assert sum(durations) == 300
    assert set(durations).issubset(set(VIDEO_CLIP_ALLOWED_SECONDS))
    assert durations.count(4) == 1
    assert durations.count(8) == 37


def test_video_clip_durations_distribute_remainder_without_invalid_tail() -> None:
    durations = video_clip_durations(60)

    assert sum(durations) == 60
    assert set(durations).issubset(set(VIDEO_CLIP_ALLOWED_SECONDS))
    assert durations.count(4) == 1
    assert durations.count(8) == 7


def test_video_clip_durations_reject_odd_total_duration() -> None:
    with pytest.raises(ValueError, match="par"):
        video_clip_durations(301)


def test_validate_video_clip_duration_rejects_outside_veo_range() -> None:
    with pytest.raises(ValueError, match="4s, 6s, 8s"):
        validate_video_clip_duration(15)
