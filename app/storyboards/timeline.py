from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TimelineDraftItem:
    source_artifact_id: UUID
    source_asset_id: UUID | None
    layer: str
    start_ms: int
    end_ms: int
    order_index: int
    properties: dict


def build_visual_timeline_items(
    frames: list[tuple[UUID, UUID, int, dict]],
) -> list[TimelineDraftItem]:
    items: list[TimelineDraftItem] = []
    cursor_ms = 0
    for index, (artifact_id, asset_id, duration_seconds, properties) in enumerate(frames, start=1):
        duration_ms = max(1, duration_seconds) * 1000
        items.append(
            TimelineDraftItem(
                source_artifact_id=artifact_id,
                source_asset_id=asset_id,
                layer="visual",
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
                order_index=index,
                properties=properties,
            )
        )
        cursor_ms += duration_ms
    return items


def build_word_alignment(text: str, duration_seconds: int) -> dict:
    words = [word for word in text.split() if word.strip()]
    if not words:
        return {"words": []}
    total_ms = max(1, duration_seconds) * 1000
    step_ms = max(1, total_ms // len(words))
    return {
        "words": [
            {
                "word": word,
                "start_ms": index * step_ms,
                "end_ms": min(total_ms, (index + 1) * step_ms),
            }
            for index, word in enumerate(words)
        ]
    }
