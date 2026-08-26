"""Continuity helpers based exclusively on frames extracted from generated videos."""

from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.video_generation.models import ContinuousVideoSegment


async def _ensure_package_initial_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    _production_settings: Any,
) -> None:
    """Link the previous video's extracted last frame when one is available."""
    if segment.segment_number <= 1 or segment.source_frame_asset_id is not None:
        return
    from app.video_generation.continuous import get_continuous_video_segment_by_number

    previous = await get_continuous_video_segment_by_number(
        session, project_id, segment.segment_number - 1
    )
    if previous is None or previous.final_frame_asset_id is None:
        return
    segment.source_frame_asset_id = previous.final_frame_asset_id
    metadata = dict(segment.metadata_json or {})
    metadata["initial_frame_asset_id"] = str(previous.final_frame_asset_id)
    metadata["frame_source"] = "previous_video_extraction"
    segment.metadata_json = metadata
    await session.flush()


def _generation_removed() -> NoReturn:
    raise RuntimeError(
        "A geração de frames por IA foi removida; use prompts de vídeo e frames extraídos."
    )


async def _generate_segment_initial_frame(*_args: object, **_kwargs: object) -> NoReturn:
    _generation_removed()


async def _generate_segment_final_frame(*_args: object, **_kwargs: object) -> NoReturn:
    _generation_removed()
