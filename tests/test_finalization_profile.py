from pathlib import Path
from uuid import uuid4

from app.finalization.service import (
    _concat_file_line,
    export_profile,
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


def test_concat_file_line_uses_absolute_clip_path(tmp_path: Path) -> None:
    clip = tmp_path / "clip 1.mp4"
    clip.write_bytes(b"fake")

    line = _concat_file_line(clip)

    assert line.startswith("file '")
    assert line.endswith("'")
    assert clip.resolve().as_posix() in line


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
