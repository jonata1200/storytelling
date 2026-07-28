import math

VIDEO_CLIP_MIN_SECONDS = 4
VIDEO_CLIP_MAX_SECONDS = 15
VIDEO_CLIP_TARGET_SECONDS = 15
VIDEO_FRAME_RATE = 24


def validate_video_clip_duration(duration_seconds: int) -> int:
    duration = int(duration_seconds)
    if duration < VIDEO_CLIP_MIN_SECONDS or duration > VIDEO_CLIP_MAX_SECONDS:
        raise ValueError(
            "Seedance 2.0 Fast aceita clipes de "
            f"{VIDEO_CLIP_MIN_SECONDS} a {VIDEO_CLIP_MAX_SECONDS} segundos; "
            f"recebido {duration}s."
        )
    return duration


def video_clip_durations(
    total_duration_seconds: int,
    *,
    max_duration_seconds: int = VIDEO_CLIP_TARGET_SECONDS,
) -> list[int]:
    total = int(total_duration_seconds)
    if total < VIDEO_CLIP_MIN_SECONDS:
        raise ValueError(
            f"A duração total precisa ter pelo menos {VIDEO_CLIP_MIN_SECONDS}s."
        )

    max_duration = min(max_duration_seconds, VIDEO_CLIP_MAX_SECONDS)
    if total <= max_duration:
        return [validate_video_clip_duration(total)]

    clip_count = math.ceil(total / max_duration)
    base_duration = total // clip_count
    remainder = total % clip_count
    durations = [
        base_duration + 1 if index < remainder else base_duration
        for index in range(clip_count)
    ]
    for duration in durations:
        validate_video_clip_duration(duration)
    return durations


def format_clip_durations(durations: list[int]) -> str:
    return ", ".join(f"{duration}s" for duration in durations)
