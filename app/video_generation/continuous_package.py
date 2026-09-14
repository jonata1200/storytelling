"""Preparation of initial/final frame packages for continuous-video segments."""

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus
from app.database.session import AsyncSessionLocal
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.video_generation.continuous_frames import (
    _ensure_package_initial_frame,
    _generate_segment_final_frame,
    _generate_segment_initial_frame,
)
from app.video_generation.models import ContinuousVideoSegment

logger = logging.getLogger(__name__)


async def emit_continuous_video_segment_event(
    session: AsyncSession,
    *,
    segment: ContinuousVideoSegment,
    status: str,
    provider: str,
    model: str,
    message: str,
    estimated_cost: Decimal | None = None,
    details: dict[str, Any] | None = None,
    operation: str = "manual_package",
) -> None:
    payload = {
        "segment_id": str(segment.id),
        "segment_number": segment.segment_number,
        "duration_seconds": segment.duration_seconds,
    }
    if details:
        payload.update(details)
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=segment.project_id,
            job_id=segment.generation_job_id,
            event_type="continuous_video_segment",
            status=status,
            provider=provider,
            model=model,
            operation=operation,
            estimated_cost=estimated_cost,
            message=_safe_event_message(message),
            details=payload,
        ),
    )


def _safe_event_message(
    text: str | None,
    *,
    limit: int = 1900,
) -> str:
    """Trunca mensagens longas com indicador de truncamento.

    O schema OperationalEventCreate.message tem max_length=2000. Call logs
    do Playwright podem ter 5000+ chars (stack trace + argumentos). Sem
    truncar, o Pydantic levanta ValidationError dentro de uma transação
    SQLAlchemy → MissingGreenlet cascata que trava o worker.

    Mantém os primeiros `limit` chars + sufixo informativo. O erro completo
    fica em metadata.details (campo livre, sem limite).
    """
    if text is None:
        return ""
    raw = str(text)
    if len(raw) <= limit:
        return raw
    head = raw[:limit]
    return f"{head}\n[...truncado, {len(raw)} → {limit} chars]"


async def _prepare_continuous_video_segment_fast(
    project_id: UUID,
    segment_id: UUID,
) -> tuple[ContinuousVideoSegment | None, list[str]]:
    from app.video_generation import continuous as api

    async with AsyncSessionLocal() as session:
        segment = await session.get(ContinuousVideoSegment, segment_id)
        if segment is None or segment.project_id != project_id:
            return None, ["Segmento nao encontrado."]
        production_settings = await get_or_create_production_settings(session, project_id)
        segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_GENERATING
        segment.status = GenerationJobStatus.RUNNING
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["frame_strategy"] = api.CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
        segment.metadata_json = metadata
        await session.commit()
        try:
            if segment.source_frame_asset_id is None:
                await _generate_segment_initial_frame(
                    session, project_id, segment, production_settings
                )
                await session.commit()
                await session.refresh(segment)
            await _generate_segment_final_frame(session, project_id, segment, production_settings)
            api._set_continuous_video_review_status(segment, api.CONTINUOUS_VIDEO_REVIEW_READY)
            segment.status = GenerationJobStatus.SUCCEEDED
            metadata = dict(segment.metadata_json or {})
            metadata.pop("error", None)
            metadata.pop("package_error", None)
            metadata["package_ready_at"] = datetime.now(UTC).isoformat()
            metadata["frame_strategy"] = api.CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
            segment.metadata_json = metadata
            await emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="ready",
                provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message="Frames do pacote prontos: gere os vídeos na aba Vídeo.",
            )
            await session.commit()
            await session.refresh(segment)
            return segment, []
        except Exception as exc:
            logger.warning(
                "continuous_video_package_failed project_id=%s segment_number=%s reason=%s",
                project_id,
                segment.segment_number,
                exc,
            )
            error_message = str(exc)
            segment.status = GenerationJobStatus.FAILED
            segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_FAILED
            metadata = dict(segment.metadata_json or {})
            metadata["error"] = error_message
            metadata["package_error"] = error_message
            metadata["failed_at"] = datetime.now(UTC).isoformat()
            metadata["frame_strategy"] = api.CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY
            segment.metadata_json = metadata
            await emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="failed",
                provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message=error_message,
            )
            await session.commit()
            return segment, [error_message]


async def _prepare_continuous_video_package_fast(
    session: AsyncSession,
    project_id: UUID,
    segments_to_prepare: list[ContinuousVideoSegment],
    validation_errors: dict[int, list[str]],
    progress_callback: Any | None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    from app.video_generation import continuous as api

    app_settings = get_settings()
    concurrency = max(
        1,
        min(int(getattr(app_settings, "video_generation_concurrency", 2) or 2), 4),
    )
    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    completed_frame_work = 0
    total_frame_work = sum(
        api._continuous_video_package_frame_work_count(segment) for segment in segments_to_prepare
    )
    if total_frame_work > 0:
        await api._emit_continuous_video_package_progress(
            progress_callback,
            0,
            total_frame_work,
            f"Agora: preparando frames em modo rapido ({concurrency} em paralelo).",
        )

    async def mark_progress(increment: int, detail: str) -> None:
        nonlocal completed_frame_work
        async with progress_lock:
            completed_frame_work += increment
            await api._emit_continuous_video_package_progress(
                progress_callback,
                completed_frame_work,
                total_frame_work,
                detail,
            )

    async def run_segment(segment: ContinuousVideoSegment) -> ContinuousVideoSegment | None:
        frame_count = api._continuous_video_package_frame_work_count(segment)
        async with semaphore:
            await api._emit_continuous_video_package_progress(
                progress_callback,
                completed_frame_work,
                total_frame_work,
                f"Agora: preparando Segmento {segment.segment_number:02d} em modo rapido.",
            )
            try:
                prepared, errors = await _prepare_continuous_video_segment_fast(
                    project_id, segment.id
                )
            except Exception as exc:
                logger.warning(
                    "continuous_video_segment_prepare_failed project_id=%s segment=%s: %s",
                    project_id,
                    segment.segment_number,
                    exc,
                )
                validation_errors[segment.segment_number] = [str(exc)]
                await mark_progress(frame_count, f"Segmento {segment.segment_number:02d} falhou.")
                return None
            if errors:
                validation_errors[segment.segment_number] = errors
            await mark_progress(frame_count, f"Segmento {segment.segment_number:02d} processado.")
            return prepared

    prepared = [
        segment
        for segment in await asyncio.gather(
            *(run_segment(segment) for segment in segments_to_prepare)
        )
        if segment is not None
    ]
    refreshed = await api.list_continuous_video_segments(session, project_id)
    refreshed_by_id = {segment.id: segment for segment in refreshed}
    return [refreshed_by_id.get(segment.id, segment) for segment in prepared], validation_errors


async def prepare_continuous_video_package(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    progress_callback: Any | None = None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    """Generate and validate the initial/final storyboard anchors for each shot."""
    from app.video_generation import continuous as api

    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise ValueError("Projeto nao encontrado.")
    segments = await api.list_continuous_video_segments(session, project_id)
    if not segments:
        _plan, segments, plan_errors = await api.plan_continuous_video_segments(
            session, project_id, replace_existing=False
        )
        if plan_errors:
            first_segment_number = min(plan_errors)
            raise ValueError(
                "Revise o planejamento antes de preparar: "
                + "; ".join(plan_errors[first_segment_number])
            )
    if segment_ids:
        selected_ids = set(segment_ids)
        segments = [segment for segment in segments if segment.id in selected_ids]
    if not segments:
        return [], {}
    production_settings = await get_or_create_production_settings(session, project_id)
    prepared: list[ContinuousVideoSegment] = []
    segments_to_prepare: list[ContinuousVideoSegment] = []
    validation_errors: dict[int, list[str]] = {}
    for segment in segments:
        if api._refresh_auto_segment_prompt(segment):
            await session.flush()
        existing_errors = api.continuous_video_segment_validation_errors(segment)
        if existing_errors:
            validation_errors[segment.segment_number] = existing_errors
            continue
        if (
            segment.review_status
            in {api.CONTINUOUS_VIDEO_REVIEW_READY, api.CONTINUOUS_VIDEO_REVIEW_APPROVED}
            and segment.source_frame_asset_id is not None
        ):
            prepared.append(segment)
            continue
        if api._continuous_video_package_frame_work_count(segment) == 0:
            await _ensure_package_initial_frame(session, project_id, segment, production_settings)
            prepared.append(segment)
            continue
        segments_to_prepare.append(segment)

    total_frame_work = sum(
        api._continuous_video_package_frame_work_count(segment) for segment in segments_to_prepare
    )
    if total_frame_work > 0:
        await api._emit_continuous_video_package_progress(
            progress_callback,
            0,
            total_frame_work,
            "Agora: preparando frame inicial do primeiro segmento.",
        )
    completed_frame_work = 0
    for segment in segments_to_prepare:
        segment_title = f"Segmento {segment.segment_number:02d}"
        segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_GENERATING
        segment.status = GenerationJobStatus.RUNNING
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        segment.metadata_json = metadata
        await session.flush()
        try:
            needs_initial_frame = segment.source_frame_asset_id is None
            needs_final_frame = segment.final_frame_asset_id is None
            if needs_initial_frame:
                await api._emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Agora: preparando frame inicial do {segment_title}.",
                )
            await _ensure_package_initial_frame(session, project_id, segment, production_settings)
            if needs_initial_frame and segment.source_frame_asset_id is not None:
                await session.commit()
                await session.refresh(segment)
                completed_frame_work += 1
                await api._emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Frame inicial do {segment_title} pronto.",
                )
            else:
                await session.commit()
                await session.refresh(segment)
            if needs_final_frame:
                await api._emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Agora: preparando frame final do {segment_title}.",
                )
                await _generate_segment_final_frame(
                    session, project_id, segment, production_settings
                )
                await session.commit()
                await session.refresh(segment)
                completed_frame_work += 1
                await api._emit_continuous_video_package_progress(
                    progress_callback,
                    completed_frame_work,
                    total_frame_work,
                    f"Frame final do {segment_title} pronto.",
                )
        except Exception as exc:
            logger.warning(
                "continuous_video_package_failed project_id=%s segment_number=%s reason=%s",
                project_id,
                segment.segment_number,
                exc,
            )
            error_message = str(exc)
            segment.status = GenerationJobStatus.FAILED
            segment.review_status = api.CONTINUOUS_VIDEO_REVIEW_FAILED
            metadata = dict(segment.metadata_json or {})
            metadata["error"] = error_message
            metadata["package_error"] = error_message
            metadata["failed_at"] = datetime.now(UTC).isoformat()
            segment.metadata_json = metadata
            validation_errors[segment.segment_number] = [error_message]
            await emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="failed",
                provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
                model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
                message=error_message,
            )
            await session.flush()
            continue
        api._set_continuous_video_review_status(segment, api.CONTINUOUS_VIDEO_REVIEW_READY)
        segment.status = GenerationJobStatus.SUCCEEDED
        metadata = dict(segment.metadata_json or {})
        metadata.pop("error", None)
        metadata.pop("package_error", None)
        metadata["package_ready_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = metadata
        prepared.append(segment)
        await emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="ready",
            provider=api.CONTINUOUS_PACKAGE_DEFAULT_SOURCE,
            model=api.CONTINUOUS_VIDEO_DEFAULT_MODEL,
            message="Pacote de vídeo pronto: copie o prompt e use os frames.",
        )
        await session.flush()
    await session.commit()
    for item in prepared:
        await session.refresh(item)
    return prepared, validation_errors
