from pathlib import Path

from app.finalization.service import _concat_file_line, export_profile


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
