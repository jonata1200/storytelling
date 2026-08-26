import pytest

from app.video_generation.durations import (
    VIDEO_CLIP_ALLOWED_SECONDS,
    validate_video_clip_duration,
    video_clip_durations,
)


def test_video_clip_durations_split_exact_five_minutes_into_package_segments() -> None:
    durations = video_clip_durations(300)

    assert len(durations) == 38
    assert sum(durations) == 304
    assert set(durations).issubset(set(VIDEO_CLIP_ALLOWED_SECONDS))
    assert durations == [8] * 38


def test_video_clip_durations_distribute_remainder_without_invalid_tail() -> None:
    durations = video_clip_durations(60)

    assert sum(durations) == 64
    assert set(durations).issubset(set(VIDEO_CLIP_ALLOWED_SECONDS))
    assert durations == [8] * 8


def test_video_clip_durations_round_total_up_to_complete_eight_second_segments() -> None:
    durations = video_clip_durations(301)

    assert durations == [8] * 38
    assert sum(durations) == 304


def test_validate_video_clip_duration_rejects_outside_package_range() -> None:
    with pytest.raises(ValueError, match="somente segmentos de 8s"):
        validate_video_clip_duration(15)
