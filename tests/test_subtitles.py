from app.finalization.subtitles import (
    build_srt_from_alignment,
    milliseconds_to_srt_timestamp,
    safe_area_profile,
)


def test_milliseconds_to_srt_timestamp_formats_hours_minutes_seconds() -> None:
    assert milliseconds_to_srt_timestamp(3_723_045) == "01:02:03,045"


def test_build_srt_from_alignment_chunks_words() -> None:
    alignment = {
        "words": [
            {"word": "Uma", "start_ms": 0, "end_ms": 300},
            {"word": "historia", "start_ms": 300, "end_ms": 700},
            {"word": "em", "start_ms": 700, "end_ms": 900},
            {"word": "cenas", "start_ms": 900, "end_ms": 1300},
        ]
    }

    content = build_srt_from_alignment(alignment, max_words_per_caption=2)

    assert "1\n00:00:00,000 --> 00:00:00,700\nUma historia" in content
    assert "2\n00:00:00,700 --> 00:00:01,300\nem cenas" in content


def test_safe_area_profile_keeps_vertical_video_margins() -> None:
    profile = safe_area_profile()

    assert profile["top_percent"] == 10
    assert profile["bottom_percent"] == 18
