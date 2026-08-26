"""Pure state helpers + page-independent watcher for the continuous-video step.

Espelha o acompanhamento da Bíblia Visual (app.ui.workspace.visual_bible_area):
um watcher independente da página consulta os jobs de vídeo do projeto e
recarrega a página do usuário assim que cada job termina, de modo que o vídeo
aparece no card do segmento sem depender do diálogo de progresso.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nicegui import background_tasks

from app.core.enums import GenerationJobStatus, GenerationJobType
from app.database.session import AsyncSessionLocal
from app.ui.shared.page_config import is_deleted_ui_context_error
from app.video_generation.models import GenerationJob

logger = logging.getLogger(__name__)

VIDEO_POLL_INTERVAL_SECONDS = 5.0

ACTIVE_VIDEO_JOB_STATUSES = {
    GenerationJobStatus.PENDING,
    GenerationJobStatus.RUNNING,
    GenerationJobStatus.RETRY_SCHEDULED,
}


@dataclass(frozen=True)
class VideoPollStatus:
    has_new_completed: bool
    has_active_generation: bool
    error: str | None = None


def video_poll_decision(
    known_segment_video_asset_ids: frozenset[str],
    jobs: list[Any],
    segments: list[Any],
) -> tuple[bool, bool]:
    """Compara jobs ativos e vídeos recém-persistidos com o snapshot conhecido."""
    has_active = any(
        job.status in ACTIVE_VIDEO_JOB_STATUSES
        and str((job.request_payload or {}).get("operation") or "") == "generate_shot"
        for job in jobs
    )
    current_video_assets = {
        str(getattr(segment, "generated_video_asset_id", "") or "")
        for segment in segments
    }
    has_new = any(
        value and value not in known_segment_video_asset_ids for value in current_video_assets
    )
    return has_new, has_active


async def _video_generation_poll_state(
    project_id: UUID,
    known_segment_video_asset_ids: frozenset[str],
) -> VideoPollStatus:
    from sqlalchemy import select

    from app.video_generation.models import ContinuousVideoSegment

    async with AsyncSessionLocal() as session:
        job_result = await session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.project_id == project_id,
                GenerationJob.job_type == GenerationJobType.VIDEO,
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(50)
        )
        segment_result = await session.execute(
            select(ContinuousVideoSegment).where(
                ContinuousVideoSegment.project_id == project_id,
            )
        )
    jobs = [
        job
        for job in job_result.scalars()
        if str((job.request_payload or {}).get("operation") or "") == "generate_shot"
    ]
    segments = list(segment_result.scalars())
    failed = next(
        (job for job in jobs if job.status == GenerationJobStatus.FAILED),
        None,
    )
    has_new, has_active = video_poll_decision(
        known_segment_video_asset_ids,
        jobs,
        segments,
    )
    error = str(failed.error or "") if failed is not None else None
    return VideoPollStatus(has_new, has_active, error)


async def _watch_video_generation(
    project_id: UUID,
    known_segment_video_asset_ids: frozenset[str],
    client: Any,
    *,
    poll_state: Callable[[UUID, frozenset[str]], Awaitable[VideoPollStatus]] | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
    navigate: Callable[[Any, str | None], None] | None = None,
    show_error: Callable[[Any, str], Awaitable[None] | None] | None = None,
) -> None:
    """Acompanha os jobs de vídeo e recarrega a página quando terminam."""
    if poll_state is None:
        poll_state = _video_generation_poll_state

    async def _default_sleep(_seconds: float) -> None:
        await asyncio.sleep(VIDEO_POLL_INTERVAL_SECONDS)

    if sleep is None:
        sleep = _default_sleep
    if navigate is None:
        from app.ui.shared.assistant_state import safe_client_navigation

        navigate = safe_client_navigation

    async def _default_show_error(current_client: Any, error: str) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        try:
            from nicegui import ui

            with current_client:
                ui.notify(
                    f"Falha ao gerar vídeo: {error}",
                    color="negative",
                    timeout=8000,
                    close_button=True,
                )
        except (AssertionError, RuntimeError) as exc:
            if not is_deleted_ui_context_error(exc):
                raise

    if show_error is None:
        show_error = _default_show_error

    while not getattr(client, "is_deleted", False):
        await sleep(VIDEO_POLL_INTERVAL_SECONDS)
        if getattr(client, "is_deleted", False):
            return
        try:
            status = await poll_state(project_id, known_segment_video_asset_ids)
        except Exception:
            # Falha transitória de leitura não deve encerrar o acompanhamento,
            # mas precisa ficar visível: se o banco cair, o watcher giraria em
            # silêncio para sempre (Qual-07).
            logger.debug(
                "video_generation_watch_poll_failed project_id=%s", project_id, exc_info=True
            )
            continue
        if status.error:
            result = show_error(client, status.error)
            if asyncio.iscoroutine(result):
                await result
            return
        if status.has_active_generation:
            continue
        if status.has_new_completed:
            # SEM recarga aqui: a task da UI (_wait_for_video_generation_jobs)
            # mostra o popup de resultado e recarrega no fim do lote. Uma
            # recarga vinda também do watcher causava DUPLA recarga quase
            # simultânea — o websocket caía (aviso de "conexão perdida" no
            # canto inferior esquerdo) e a página travava re-baixando os
            # vídeos das variantes. O watcher segue vivo para falhas e para
            # o caso do usuário fechar o diálogo de progresso.
            return
        # Sem jobs ativos e sem novidades: acompanhamento encerrado.
        return


def start_video_generation_watch(
    project_id: UUID,
    known_segment_video_asset_ids: frozenset[str],
    client: Any,
) -> Any:
    """Watcher independente de página para geração de vídeo recém-enfileirada."""

    task = background_tasks.create(
        _watch_video_generation(project_id, known_segment_video_asset_ids, client),
        name=f"video-generation-watch-{project_id}-{getattr(client, 'id', '')}",
    )

    def cancel_task() -> None:
        task.cancel()

    client.on_delete(cancel_task)


# ---------------------------------------------------------------------------
# Watcher de FRAME (inicial/final) de um segmento. A geração de frame é
# síncrona na UI (sem job na fila), então o acompanhamento observa o SEGMENTO:
# o asset do frame aparece no campo do frame_kind ou o metadata_json registra
# "error"/"package_error" numa falha. Espelha o watcher de vídeo acima.
# ---------------------------------------------------------------------------

FRAME_POLL_INTERVAL_SECONDS = 5.0
FRAME_WATCH_MAX_SECONDS = 600.0


@dataclass(frozen=True)
class FramePollStatus:
    completed: bool
    failed: bool
    error: str | None = None


def frame_poll_decision(
    segment: Any,
    frame_kind: str,
    known_asset_id: str,
) -> FramePollStatus:
    """Estado do frame monitorado: concluído, falhou ou ainda gerando."""

    metadata = getattr(segment, "metadata_json", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    error = str(metadata.get("error") or metadata.get("package_error") or "").strip()
    frame_field = (
        "source_frame_asset_id" if frame_kind == "initial" else "final_frame_asset_id"
    )
    asset_id = str(getattr(segment, frame_field, "") or "")
    if asset_id and asset_id != known_asset_id:
        return FramePollStatus(completed=True, failed=False)
    raw_status = getattr(segment, "status", "")
    status_value = str(getattr(raw_status, "value", raw_status) or "").lower()
    if error and status_value in {"failed", "error"}:
        return FramePollStatus(completed=False, failed=True, error=error)
    return FramePollStatus(completed=False, failed=False)


async def _frame_generation_poll_state(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
    known_asset_id: str,
) -> FramePollStatus | None:
    from sqlalchemy import select

    from app.video_generation.models import ContinuousVideoSegment

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ContinuousVideoSegment).where(
                ContinuousVideoSegment.id == segment_id,
                ContinuousVideoSegment.project_id == project_id,
            )
        )
    segment = result.scalars().first()
    if segment is None:
        return None
    return frame_poll_decision(segment, frame_kind, known_asset_id)


async def _watch_frame_generation(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
    known_asset_id: str,
    client: Any,
    *,
    poll_state: Callable[[UUID, UUID, str, str], Awaitable[FramePollStatus | None]] | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
    navigate: Callable[[Any, str | None], None] | None = None,
    show_error: Callable[[Any, str], Awaitable[None] | None] | None = None,
) -> None:
    """Acompanha a geração de um frame e recarrega a página quando termina.

    Falha é APENAS notificada (sem popup bloqueante): o retry do usuário é
    pelo botão, e o popup de erro persistente já foi problema antes (lote
    recuperado continuava com aviso eterno).
    """
    if poll_state is None:
        poll_state = _frame_generation_poll_state

    async def _default_sleep(_seconds: float) -> None:
        await asyncio.sleep(FRAME_POLL_INTERVAL_SECONDS)

    sleep = sleep or _default_sleep
    if navigate is None:
        from app.ui.shared.assistant_state import safe_client_navigation

        navigate = safe_client_navigation

    frame_label = "inicial" if frame_kind == "initial" else "final"

    async def _default_show_error(current_client: Any, error: str) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        try:
            from nicegui import ui

            with current_client:
                ui.notify(
                    f"Falha ao gerar o frame {frame_label}: {error[:220]}",
                    color="negative",
                    timeout=10000,
                    close_button=True,
                )
        except (AssertionError, RuntimeError) as exc:
            if not is_deleted_ui_context_error(exc):
                raise

    show_error = show_error or _default_show_error

    deadline = asyncio.get_event_loop().time() + FRAME_WATCH_MAX_SECONDS
    while not getattr(client, "is_deleted", False):
        await sleep(FRAME_POLL_INTERVAL_SECONDS)
        if getattr(client, "is_deleted", False):
            return
        if asyncio.get_event_loop().time() > deadline:
            # Segurança: não gira para sempre se a geração travar no backend.
            return
        try:
            status = await poll_state(project_id, segment_id, frame_kind, known_asset_id)
        except Exception:
            logger.debug(
                "frame_generation_watch_poll_failed project_id=%s segment=%s",
                project_id,
                segment_id,
                exc_info=True,
            )
            continue
        if status is None:
            return
        if status.failed:
            result = show_error(client, status.error or "erro desconhecido")
            if asyncio.iscoroutine(result):
                await result
            navigate(client, None)
            return
        if status.completed:
            navigate(client, None)
            return


def start_frame_generation_watch(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
    *,
    known_asset_id: str = "",
    client: Any,
) -> Any:
    """Watcher independente de página para a geração de um frame de segmento."""

    task = background_tasks.create(
        _watch_frame_generation(
            project_id, segment_id, frame_kind, known_asset_id, client
        ),
        name=f"frame-generation-watch-{project_id}-{segment_id}-{frame_kind}",
    )

    def cancel_task() -> None:
        task.cancel()

    client.on_delete(cancel_task)
    return task