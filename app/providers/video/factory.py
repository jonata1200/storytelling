from typing import Any

from app.providers.registry import resolve_video_provider
from app.providers.video.types import VideoProvider


def configured_video_provider(settings: Any) -> VideoProvider:
    return resolve_video_provider(settings)
