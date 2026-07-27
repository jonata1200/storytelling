from pathlib import Path
from uuid import uuid4

from app.finalization.service import (
    _concat_file_line,
    clip_compatibility_errors,
    export_profile,
    export_profile_from_payload,
    final_timeline_coverage_errors,
)
from app.storyboards.models import StoryboardFrame
from app.video_generation.models import VideoClip


def test_export_profile_defaults_to_vertical_social_video() -> None:
    profile = export_profile()

    assert profile["aspect_ratio"] == "9:16"
    assert profile["resolution"] == "1080x1920"
    assert profile["fps"] == 30
    assert profile["safe_area"]["bottom_percent"] == 18


def test_export_profile_from_payload_overrides_render_settings() -> None:
    profile = export_profile_from_payload(
        fps=24,
        bitrate="12M",
        resolution="1920x1080",
        embed_subtitles=False,
    )

    assert profile["fps"] == 24
    assert profile["bitrate"] == "12M"
    assert profile["resolution"] == "1920x1080"
    assert profile["embed_subtitles"] is False


def test_concat_file_line_uses_absolute_clip_path(tmp_path: Path) -> None:
    clip = tmp_path / "clip 1.mp4"
    clip.write_bytes(b"fake")

    line = _concat_file_line(clip)

    assert line.startswith("file '")
    assert line.endswith("'")
    assert clip.resolve().as_posix() in line


def test_clip_compatibility_errors_reports_missing_and_empty_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    missing = tmp_path / "missing.mp4"
    empty.write_bytes(b"")

    errors = clip_compatibility_errors([empty, missing])

    assert "Clipe vazio: empty.mp4" in errors
    assert "Clipe nao encontrado: missing.mp4" in errors


def test_final_timeline_coverage_requires_selected_clip_for_each_frame() -> None:
    first_frame_id = uuid4()
    second_frame_id = uuid4()
    frames = [
        StoryboardFrame(id=first_frame_id, frame_number=1),
        StoryboardFrame(id=second_frame_id, frame_number=2),
    ]
    clips = [
        VideoClip(
            id=uuid4(),
            storyboard_frame_id=first_frame_id,
            duration_seconds=5,
            selected=True,
        )
    ]

    errors = final_timeline_coverage_errors(frames, clips)

    assert "1 frame(s) sem clipe selecionado" in errors


def test_final_timeline_coverage_rejects_duplicate_selected_clips() -> None:
    frame_id = uuid4()
    frames = [StoryboardFrame(id=frame_id, frame_number=1)]
    clips = [
        VideoClip(id=uuid4(), storyboard_frame_id=frame_id, selected=True),
        VideoClip(id=uuid4(), storyboard_frame_id=frame_id, selected=True),
    ]

    assert "1 frame(s) com mais de um clipe selecionado" in final_timeline_coverage_errors(
        frames, clips
    )
