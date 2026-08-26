from typing import Any

from app.providers.video.types import VideoGenerationRequest

SUPPORTED_DURATIONS = (5, 10)
SUPPORTED_ASPECT_RATIOS = {"9:16": "portrait", "16:9": "landscape", "1:1": "square"}


def map_duration(seconds: int) -> int:
    """Escolhe a duração pública mais próxima sem exceder silenciosamente 10s."""
    value = max(1, int(seconds))
    return min(SUPPORTED_DURATIONS, key=lambda item: (abs(item - value), item))


def map_vibes_request(request: VideoGenerationRequest) -> dict[str, Any]:
    aspect = SUPPORTED_ASPECT_RATIOS.get(request.aspect_ratio)
    if aspect is None:
        allowed = ", ".join(SUPPORTED_ASPECT_RATIOS)
        raise ValueError(
            f"Aspect ratio não suportado pelo Vibes: {request.aspect_ratio}. Use: {allowed}"
        )
    frames = {
        item.frame_type: item.url
        for item in request.frame_images
        if item.url.strip() and item.frame_type in {"first_frame", "last_frame"}
    }
    return {
        "model": request.model,
        "prompt": request.prompt,
        "duration_seconds": map_duration(request.duration),
        "aspect_ratio": aspect,
        "resolution": request.resolution,
        "audio": {"enabled": request.generate_audio},
        "seed": request.seed,
        "first_frame": frames.get("first_frame"),
        "final_frame": frames.get("last_frame"),
        "references": [item.url for item in request.input_references if item.url.strip()],
        "ingredients": [
            {"id": item.id, "type": item.type, "reference_id": item.reference_id}
            for item in request.ingredients
        ],
    }
