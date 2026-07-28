from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pytest import MonkeyPatch

from app.finalization import service as finalization_service
from app.finalization.service import (
    TimelineAudioAsset,
    _concat_file_line,
    _render_timeline_video_with_audio,
    _voice_for_speaker,
    _voice_profile_for_key,
    clip_compatibility_errors,
    export_profile,
    export_profile_from_payload,
    final_timeline_coverage_errors,
    parse_dialogue_lines,
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


def test_parse_dialogue_lines_accepts_colon_and_screenplay_blocks() -> None:
    lines = parse_dialogue_lines("CLARA: Oi, Lucas.\nLUCAS\nTudo bem por aqui.")

    assert [line.speaker for line in lines] == ["CLARA", "Lucas"]
    assert [line.text for line in lines] == ["Oi, Lucas.", "Tudo bem por aqui."]


def test_voice_for_speaker_uses_character_map_or_stable_fallback() -> None:
    assert _voice_for_speaker("Clara jovem", {"clara": "nova"}) == "nova"
    assert _voice_for_speaker("Outro", {}) == _voice_profile_for_key("outro")


def test_render_timeline_video_with_audio_delays_and_mixes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    output_path = tmp_path / "final.mp4"
    audio_path = tmp_path / "clara.wav"
    audio_path.write_bytes(b"audio")
    commands: list[list[str]] = []

    def fake_render(
        ffmpeg_path: str,
        clip_paths: list[Path],
        output_path: Path,
        profile: dict,
    ) -> str:
        output_path.write_bytes(b"video")
        return "video log"

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> SimpleNamespace:
        commands.append(command)
        output_path.write_bytes(b"mp4")
        return SimpleNamespace(stderr="audio log")

    monkeypatch.setattr(finalization_service, "_render_timeline_video", fake_render)
    monkeypatch.setattr(finalization_service.subprocess, "run", fake_run)

    log = _render_timeline_video_with_audio(
        "ffmpeg",
        [tmp_path / "clip.mp4"],
        [TimelineAudioAsset(path=audio_path, start_ms=1200)],
        output_path,
        {"audio_codec": "aac"},
    )

    command_text = " ".join(commands[0])
    assert "adelay=1200:all=1" in command_text
    assert "amix=inputs=1" in command_text
    assert "-map [mix]" in command_text
    assert "character dialogue audio" in log
