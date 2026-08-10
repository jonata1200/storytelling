import subprocess
import tempfile
from pathlib import Path


def resolution_dimensions(resolution: str) -> tuple[int, int]:
    parts = resolution.lower().split("x", 1)
    if len(parts) != 2:
        return 1080, 1920
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError:
        return 1080, 1920
    return max(1, width), max(1, height)


def concat_file_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def render_timeline_video(
    ffmpeg_path: str,
    clip_paths: list[Path],
    output_path: Path,
    profile: dict,
) -> str:
    concat_path = output_path.with_suffix(".concat.txt")
    concat_path.write_text(
        "\n".join(concat_file_line(path) for path in clip_paths) + "\n",
        encoding="utf-8",
    )
    command = [
        ffmpeg_path,
        "-y",
        "-safe",
        "0",
        "-f",
        "concat",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return completed.stderr[-2000:]
    except subprocess.CalledProcessError:
        return render_timeline_video_normalized(ffmpeg_path, clip_paths, output_path, profile)
    finally:
        concat_path.unlink(missing_ok=True)


def render_timeline_video_normalized(
    ffmpeg_path: str,
    clip_paths: list[Path],
    output_path: Path,
    profile: dict,
) -> str:
    resolution = str(profile.get("resolution") or "1080x1920")
    width, height = resolution_dimensions(resolution)
    fps = int(profile.get("fps") or 30)
    bitrate = str(profile.get("bitrate") or "8M")
    logs: list[str] = []
    with tempfile.TemporaryDirectory() as temporary_dir:
        temporary_path = Path(temporary_dir)
        normalized_paths: list[Path] = []
        for index, clip_path in enumerate(clip_paths, start=1):
            normalized_path = temporary_path / f"clip_{index:03d}.mp4"
            normalize_command = [
                ffmpeg_path,
                "-y",
                "-i",
                str(clip_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                "-c:v",
                "libx264",
                "-b:v",
                bitrate,
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(normalized_path),
            ]
            completed = subprocess.run(
                normalize_command,
                check=True,
                capture_output=True,
                text=True,
            )
            logs.append(completed.stderr[-1000:])
            normalized_paths.append(normalized_path)
        concat_path = temporary_path / "normalized.concat.txt"
        concat_path.write_text(
            "\n".join(concat_file_line(path) for path in normalized_paths) + "\n",
            encoding="utf-8",
        )
        concat_command = [
            ffmpeg_path,
            "-y",
            "-safe",
            "0",
            "-f",
            "concat",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            str(output_path),
        ]
        completed = subprocess.run(concat_command, check=True, capture_output=True, text=True)
        logs.append(completed.stderr[-1000:])
    return "FFmpeg normalized incompatible clips before concat. " + "\n".join(logs)[-2000:]
