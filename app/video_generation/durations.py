import math

VIDEO_CLIP_MIN_SECONDS = 4
VIDEO_CLIP_ALLOWED_SECONDS = (4, 6, 8)
VIDEO_CLIP_MAX_SECONDS = max(VIDEO_CLIP_ALLOWED_SECONDS)
VIDEO_CLIP_TARGET_SECONDS = VIDEO_CLIP_MAX_SECONDS
VIDEO_FRAME_RATE = 24


def validate_video_clip_duration(duration_seconds: int) -> int:
    duration = int(duration_seconds)
    if duration not in VIDEO_CLIP_ALLOWED_SECONDS:
        allowed = ", ".join(f"{value}s" for value in VIDEO_CLIP_ALLOWED_SECONDS)
        raise ValueError(
            "O pacote de video aceita somente segmentos de "
            f"{allowed}; recebido {duration}s."
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
    if total % 2 != 0:
        raise ValueError("A duracao total precisa ser par para distribuir segmentos de video.")

    max_duration = min(max_duration_seconds, VIDEO_CLIP_MAX_SECONDS)
    if total <= max_duration:
        return [validate_video_clip_duration(total)]

    clip_count = math.ceil(total / max_duration)
    while total < VIDEO_CLIP_MIN_SECONDS * clip_count:
        clip_count += 1

    durations = [max_duration] * clip_count
    overage = (max_duration * clip_count) - total
    index = 0
    while overage >= 4 and index < len(durations):
        durations[index] -= 4
        overage -= 4
        index += 1
    if overage == 2 and index < len(durations):
        if durations[index] - 2 >= VIDEO_CLIP_MIN_SECONDS:
            durations[index] -= 2
        elif index + 1 < len(durations) and durations[index + 1] - 2 >= VIDEO_CLIP_MIN_SECONDS:
            durations[index + 1] -= 2
        else:
            # Cannot safely subtract 2 without going below minimum; accept overage.
            pass

    for duration in durations:
        validate_video_clip_duration(duration)
    return durations


def format_clip_durations(durations: list[int]) -> str:
    return ", ".join(f"{duration}s" for duration in durations)
