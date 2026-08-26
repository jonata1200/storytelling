import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config.settings import get_settings
from app.generation.prompt_language import ensure_portuguese_prompt_text
from app.generation.shot_prompt_compiler import (
    bounded_prompt,
    compact_text,
)
from app.storyboards.models import StoryboardFrame
from app.storytelling.models import Scene, Shot
from app.video_generation.retry import exponential_backoff_seconds

VIDEO_PROMPT_OVERRIDES_KEY = "video_prompt_overrides"


def _service_attr(name: str, fallback: object) -> Any:
    service = sys.modules.get("app.video_generation.service")
    return getattr(service, name, fallback) if service is not None else fallback


def video_idempotency_key(
    storyboard_frame_id: UUID,
    variant_index: int,
    provider: str,
    model: str,
    fingerprint: str = "",
) -> str:
    raw = f"{storyboard_frame_id}:{variant_index}:{provider}:{model}:{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _video_request_fingerprint(
    frame: StoryboardFrame,
    source_image_uri: str | None,
    provider: str,
    model: str,
    aspect_ratio: str,
    size: str,
    video_prompt: str | None = None,
    reference_uris: list[str] | None = None,
) -> str:
    frame_metadata = frame.metadata_json if isinstance(frame.metadata_json, dict) else {}
    payload = {
        "storyboard_frame_id": str(frame.id),
        "storyboard_frame_fingerprint": frame_metadata.get("frame_fingerprint"),
        "source_image_asset_id": str(frame.asset_id),
        "source_image_uri": source_image_uri,
        "storyboard_prompt": frame.prompt,
        "video_prompt": video_prompt or frame.prompt,
        "reference_uris": list(reference_uris or []),
        "duration_seconds": frame.duration_seconds,
        "provider": provider,
        "model": model,
        "aspect_ratio": aspect_ratio,
        "size": size,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _video_motion_prompt(
    frame: StoryboardFrame,
    shot: Shot | None = None,
    scene: Scene | None = None,
) -> str:
    action = compact_text(
        getattr(shot, "action", "") or "A ação descrita no storyboard acontece",
        190,
    )
    location = compact_text(getattr(scene, "title", ""), 80)
    dialogue = str(getattr(shot, "dialogue_text", "") or frame.dialogue_text or "").strip()
    scene_action = f"Em {location}, {action}." if location else f"{action}."
    return bounded_prompt(
        [
            scene_action,
            f'Diálogo: "{compact_text(dialogue, 100)}".' if dialogue else "",
        ]
    )


def _video_prompt_override_map(metadata: dict) -> dict[str, str]:
    raw_store = metadata.get(VIDEO_PROMPT_OVERRIDES_KEY)
    if not isinstance(raw_store, dict):
        return {}
    return {
        str(frame_id): str(prompt)
        for frame_id, prompt in raw_store.items()
        if str(prompt or "").strip()
    }


def _video_prompt_override(metadata: dict, frame_id: UUID) -> str | None:
    return _video_prompt_override_map(metadata).get(str(frame_id))


def _video_effective_prompt(
    metadata: dict,
    frame: StoryboardFrame,
    shot: Shot | None = None,
    scene: Scene | None = None,
) -> str:
    return ensure_portuguese_prompt_text(
        _video_prompt_override(metadata, frame.id) or _video_motion_prompt(frame, shot, scene)
    )


def _store_video_prompt_override(metadata: dict, frame_id: UUID, prompt: str) -> dict:
    updated = dict(metadata or {})
    store = dict(_video_prompt_override_map(updated))
    store[str(frame_id)] = prompt.strip()
    updated[VIDEO_PROMPT_OVERRIDES_KEY] = store
    return updated


def _local_storage_path(storage_uri: str | None) -> Path | None:
    if not storage_uri:
        return None
    settings_factory = _service_attr("get_settings", get_settings)
    storage_root = settings_factory().local_storage_path.resolve()
    path = Path(storage_uri)
    try:
        candidate = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        return None
    return candidate


def _failed_job_payload(
    frame: StoryboardFrame,
    variant_index: int,
    reason: str,
    attempts: int,
) -> dict:
    return {
        "storyboard_frame_id": str(frame.id),
        "frame_number": frame.frame_number,
        "variant_index": variant_index,
        "reason": reason,
        "retry_after_seconds": exponential_backoff_seconds(attempts),
        "retry_available": "manual",
    }
