import math

VIDEO_CLIP_TARGET_SECONDS = 8
VIDEO_CLIP_MIN_SECONDS = VIDEO_CLIP_TARGET_SECONDS
VIDEO_CLIP_ALLOWED_SECONDS = (VIDEO_CLIP_TARGET_SECONDS,)
VIDEO_CLIP_MAX_SECONDS = VIDEO_CLIP_TARGET_SECONDS
VIDEO_FRAME_RATE = 24


def validate_video_clip_duration(duration_seconds: int) -> int:
    duration = int(duration_seconds)
    if duration not in VIDEO_CLIP_ALLOWED_SECONDS:
        raise ValueError(f"O pacote de video aceita somente segmentos de 8s; recebido {duration}s.")
    return duration


def video_clip_durations(
    total_duration_seconds: int,
    *,
    max_duration_seconds: int = VIDEO_CLIP_TARGET_SECONDS,
) -> list[int]:
    total = max(VIDEO_CLIP_TARGET_SECONDS, int(total_duration_seconds))
    target = min(max_duration_seconds, VIDEO_CLIP_TARGET_SECONDS)
    validate_video_clip_duration(target)
    normalized_total = math.ceil(total / target) * target
    return [target] * (normalized_total // target)


def format_clip_durations(durations: list[int]) -> str:
    return ", ".join(f"{duration}s" for duration in durations)
