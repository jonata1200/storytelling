"""Stub of continuous_generation.py to support imports while disabling video generation."""

import logging
from typing import Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _extract_last_frame_from_video(
    session: AsyncSession,
    project_id: UUID,
    segment: Any,
    video_path: Any,
) -> UUID | None:
    return None


async def generate_video_for_segment(
    session: AsyncSession,
    project_id: UUID,
    segment: Any,
    production_settings: Any,
    progress_callback: Any = None,
) -> tuple[bool, str]:
    return False, "Video generation is disabled."
