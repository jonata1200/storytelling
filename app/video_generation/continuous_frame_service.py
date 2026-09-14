"""Lifecycle operations for continuous-video package frame assets."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus
from app.production.service import get_or_create_production_settings
from app.video_generation.continuous_frames import (
    _ensure_package_initial_frame,
    _generate_segment_final_frame,
    _generate_segment_initial_frame,
)
from app.video_generation.continuous_frames import (
    segment_frame_prompts as segment_frame_prompts,  # noqa: F401
)
from app.video_generation.continuous_review import invalidate_continuous_video_downstream_segments
from app.video_generation.models import ContinuousVideoSegment

logger = logging.getLogger(__name__)

_CONTINUOUS_FRAME_ASSET_ROLES = {
    "continuous_video_initial_frame",
    "continuous_video_final_frame",
}


async def _delete_continuous_video_frame_asset_if_unshared(
    session: AsyncSession,
    *,
    asset_id: UUID,
    segment_id: UUID,
) -> str | None:
    from app.assets.models import Asset, AssetVersion

    asset = await session.get(Asset, asset_id)
    if asset is None:
        return None
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    if (
        str(metadata.get("segment_id") or "") != str(segment_id)
        or metadata.get("technical_role") not in _CONTINUOUS_FRAME_ASSET_ROLES
    ):
        return None
    shared_result = await session.execute(
        select(ContinuousVideoSegment.id)
        .where(
            ContinuousVideoSegment.id != segment_id,
            or_(
                ContinuousVideoSegment.source_frame_asset_id == asset_id,
                ContinuousVideoSegment.final_frame_asset_id == asset_id,
            ),
        )
        .limit(1)
    )
    if shared_result.scalars().first() is not None:
        return None
    storage_uri = str(asset.storage_uri or "")
    await session.execute(delete(AssetVersion).where(AssetVersion.asset_id == asset_id))
    await session.delete(asset)
    return storage_uri


async def _continuous_video_frame_asset_belongs_to_segment(
    session: AsyncSession,
    *,
    asset_id: UUID,
    segment_id: UUID,
) -> bool:
    from app.assets.models import Asset

    asset = await session.get(Asset, asset_id)
    if asset is None:
        return False
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return (
        str(metadata.get("segment_id") or "") == str(segment_id)
        and metadata.get("technical_role") in _CONTINUOUS_FRAME_ASSET_ROLES
    )


def _set_continuous_video_segment_package_status(segment: ContinuousVideoSegment) -> None:
    from app.video_generation import continuous as api

    metadata = dict(segment.metadata_json or {})
    if segment.source_frame_asset_id is not None:
        api._set_continuous_video_review_status(segment, api.CONTINUOUS_VIDEO_REVIEW_READY)
        metadata = dict(segment.metadata_json or {})
        segment.status = GenerationJobStatus.SUCCEEDED
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
    else:
        segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_PENDING
        segment.status = GenerationJobStatus.PENDING
        metadata.pop("package_ready_at", None)
        metadata["review_status"] = api.CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata


async def remove_continuous_video_segment_frame(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> ContinuousVideoSegment | None:
    """Detach one frame from a segment and delete it only when it is unshared."""
    from app.video_generation import continuous as api

    normalized_kind = str(frame_kind or "").strip().lower()
    if normalized_kind not in {"initial", "final"}:
        raise ValueError("frame_kind deve ser 'initial' ou 'final'.")
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    metadata = dict(segment.metadata_json or {})
    removed_at = datetime.now(UTC).isoformat()
    old_asset_id = (
        segment.source_frame_asset_id
        if normalized_kind == "initial"
        else segment.final_frame_asset_id
    )
    if normalized_kind == "initial":
        segment.source_frame_asset_id = None
        metadata.pop("initial_frame_asset_id", None)
        metadata.pop("initial_frame_storage_uri", None)
        metadata.pop("initial_frame_reference_uris", None)
        metadata["initial_frame_removed_manually"] = True
        metadata["initial_frame_removed_at"] = removed_at
    else:
        segment.final_frame_asset_id = None
        metadata.pop("final_frame_asset_id", None)
        metadata.pop("final_frame_storage_uri", None)
        metadata.pop("final_frame_reference_uris", None)
        metadata["final_frame_removed_manually"] = True
        metadata["final_frame_removed_at"] = removed_at
    metadata.pop("error", None)
    metadata.pop("package_error", None)
    segment.metadata_json = metadata
    _set_continuous_video_segment_package_status(segment)
    await session.flush()
    if old_asset_id is not None:
        deleted_storage_uri = await _delete_continuous_video_frame_asset_if_unshared(
            session, asset_id=old_asset_id, segment_id=segment.id
        )
        if deleted_storage_uri:
            from app.storage.service import delete_local_storage_files

            delete_local_storage_files([deleted_storage_uri])
    if normalized_kind == "final":
        await invalidate_continuous_video_downstream_segments(
            session,
            project_id,
            segment.segment_number,
            reason="upstream_final_frame_removed",
        )
    await api._emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="pending",
        provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
        model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
        message=(
            "Frame inicial removido manualmente."
            if normalized_kind == "initial"
            else "Frame final removido manualmente."
        ),
    )
    await session.commit()
    await session.refresh(segment)
    return segment


async def regenerate_continuous_video_segment_frame(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> ContinuousVideoSegment | None:
    """Regenerate only one frame from a segment package."""
    from app.video_generation import continuous as api

    normalized_kind = str(frame_kind or "").strip().lower()
    if normalized_kind not in {"initial", "final"}:
        raise ValueError("frame_kind deve ser 'initial' ou 'final'.")
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    metadata = dict(segment.metadata_json or {})
    old_asset_id = (
        segment.source_frame_asset_id
        if normalized_kind == "initial"
        else segment.final_frame_asset_id
    )
    if (
        normalized_kind == "initial"
        and segment.segment_number > 1
        and old_asset_id is not None
        and not await _continuous_video_frame_asset_belongs_to_segment(
            session, asset_id=old_asset_id, segment_id=segment.id
        )
    ):
        raise ValueError(
            "O frame inicial deste segmento vem do frame final do segmento anterior. "
            "Regere o frame final do segmento anterior para manter a continuidade."
        )
    if normalized_kind == "initial":
        segment.source_frame_asset_id = None
        metadata.pop("initial_frame_asset_id", None)
        metadata.pop("initial_frame_storage_uri", None)
        metadata.pop("initial_frame_reference_uris", None)
    else:
        segment.final_frame_asset_id = None
        metadata.pop("final_frame_asset_id", None)
        metadata.pop("final_frame_storage_uri", None)
        metadata.pop("final_frame_reference_uris", None)
    metadata.pop("error", None)
    metadata.pop("package_error", None)
    segment.metadata_json = metadata
    segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_PREPARING
    segment.status = GenerationJobStatus.RUNNING
    await session.flush()
    if old_asset_id is not None:
        deleted_storage_uri = await _delete_continuous_video_frame_asset_if_unshared(
            session, asset_id=old_asset_id, segment_id=segment.id
        )
        if deleted_storage_uri:
            from app.storage.service import delete_local_storage_files

            delete_local_storage_files([deleted_storage_uri])
    production_settings = await get_or_create_production_settings(session, project_id)
    try:
        if normalized_kind == "initial":
            if old_asset_id is None and segment.segment_number > 1:
                await _ensure_package_initial_frame(
                    session, project_id, segment, production_settings
                )
            else:
                await _generate_segment_initial_frame(
                    session, project_id, segment, production_settings
                )
            message = "Frame inicial regenerado com sucesso."
        else:
            if segment.source_frame_asset_id is None:
                raise ValueError("Gere o frame inicial antes de gerar o frame final.")
            await _generate_segment_final_frame(session, project_id, segment, production_settings)
            await invalidate_continuous_video_downstream_segments(
                session,
                project_id,
                segment.segment_number,
                reason="upstream_final_frame_regenerated",
            )
            message = "Frame final regenerado com sucesso."
        _set_continuous_video_segment_package_status(segment)
        await api._emit_continuous_video_segment_event(
            session,
            segment=segment,
            status=(
                "ready" if segment.review_status == api.CONTINUOUS_VIDEO_REVIEW_READY else "pending"
            ),
            provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
            model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
            message=message,
        )
        await session.commit()
        await session.refresh(segment)
        return segment
    except Exception as exc:
        logger.warning(
            "regenerate_segment_frame_failed project_id=%s segment=%s frame_kind=%s: %s",
            project_id,
            segment.segment_number,
            normalized_kind,
            exc,
        )
        segment.status = GenerationJobStatus.FAILED
        segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_FAILED
        error_metadata = dict(segment.metadata_json or {})
        error_metadata["error"] = str(exc)
        error_metadata["package_error"] = str(exc)
        error_metadata["failed_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = error_metadata
        await session.commit()
        raise


async def regenerate_continuous_video_segment_frames(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
) -> ContinuousVideoSegment | None:
    """Generate only missing frames for a single segment."""
    from app.video_generation import continuous as api

    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if api._continuous_video_package_frame_work_count(segment) == 0:
        return segment
    prepared, validation_errors = await api.prepare_continuous_video_package(
        session, project_id, segment_ids=[segment_id]
    )
    if validation_errors:
        first_segment_number = min(validation_errors)
        raise ValueError("; ".join(validation_errors[first_segment_number]))
    return prepared[0] if prepared else segment


async def update_continuous_video_segment_frame_prompt(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    initial_frame_prompt: str | None = None,
    final_frame_prompt: str | None = None,
) -> ContinuousVideoSegment | None:
    """Save custom frame prompt overrides into segment metadata."""
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    metadata = dict(segment.metadata_json or {})
    if initial_frame_prompt is not None:
        if initial_frame_prompt.strip():
            metadata["initial_frame_prompt_override"] = initial_frame_prompt.strip()
        else:
            metadata.pop("initial_frame_prompt_override", None)
    if final_frame_prompt is not None:
        if final_frame_prompt.strip():
            metadata["final_frame_prompt_override"] = final_frame_prompt.strip()
        else:
            metadata.pop("final_frame_prompt_override", None)
    segment.metadata_json = metadata
    await session.commit()
    await session.refresh(segment)
    return segment
