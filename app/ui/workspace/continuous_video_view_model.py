from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.ui.workspace.rules import CONTINUOUS_VIDEO_WORKFLOW_MODE
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY,
    continuous_video_frame_strategy,
    continuous_video_segment_validation_errors,
)

CONTROL_VISUAL_WORKFLOW_MODE = "keyframes_i2v"
VIDEO_WORKFLOW_MODE_LABELS = {
    CONTROL_VISUAL_WORKFLOW_MODE: "Controle visual",
    CONTINUOUS_VIDEO_WORKFLOW_MODE: "Assistente de pacote de vídeo",
}


@dataclass(slots=True)
class ContinuousVideoSegmentRow:
    id: UUID
    number: int
    title: str
    prompt: str
    action: str
    visual_summary: str
    duration_seconds: int
    status: str
    status_label: str
    progress_state: str
    cost_estimate: Decimal
    pending_frame_count: int
    frame_cost_estimate: Decimal
    initial_frame_asset_id: UUID | None = None
    final_frame_asset_id: UUID | None = None
    validation_errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContinuousVideoViewModel:
    workflow_mode: str
    is_continuous_mode: bool
    rows: list[ContinuousVideoSegmentRow]
    total_segments: int
    generated_segments: int
    pending_segments: int
    failed_segments: int
    running_segments: int
    total_seconds: int
    pending_frame_count: int
    total_frame_cost_estimate: Decimal
    next_segment_id: UUID | None
    can_plan: bool
    can_prepare: bool
    can_conclude: bool


def production_workflow_mode(settings: Any) -> str:
    mode = str(getattr(settings, "workflow_mode", "") or "").strip()
    return mode or CONTINUOUS_VIDEO_WORKFLOW_MODE


def is_continuous_video_mode(settings: Any) -> bool:
    return production_workflow_mode(settings) == CONTINUOUS_VIDEO_WORKFLOW_MODE


def normalize_continuous_video_status(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def continuous_video_status_label(status: str) -> str:
    return {
        "pending": "Pendente",
        "preparing": "Preparando",
        "ready": "Pronto",
        "done": "Concluido",
        "rejected": "Rejeitado",
        "failed": "Falhou",
        "generating": "Preparando",
        "ready_for_review": "Pronto",
        "approved": "Concluido",
        "retry_scheduled": "Pendente",
        "running": "Processando",
        "succeeded": "Concluido",
        "cancelled": "Cancelado",
        "skipped": "Ja existe",
        "sending": "Enviando",
    }.get(status, "Pendente")


def continuous_video_progress_state(
    segment: Any,
    *,
    preexisting_succeeded_ids: set[UUID] | None = None,
) -> str:
    status = normalize_continuous_video_status(
        getattr(segment, "review_status", None) or getattr(segment, "status", "")
    )
    segment_id = getattr(segment, "id", None)
    if status in {"done", "approved", "succeeded"} and segment_id in (
        preexisting_succeeded_ids or set()
    ):
        return "skipped"
    if status in {"done", "approved", "succeeded"}:
        return "done"
    if status in {"failed", "rejected"}:
        return "failed"
    if status in {"running", "preparing", "generating"}:
        return "processing"
    return "pending"


def _segment_cost(segment: Any) -> Decimal:
    raw_cost = getattr(segment, "cost_estimate", None)
    if raw_cost is not None:
        try:
            cost = Decimal(str(raw_cost))
        except Exception:
            cost = Decimal("0")
        if cost > Decimal("0"):
            return cost
    return Decimal("0.000000")


def _pending_frame_count(
    segment: Any,
    *,
    frame_strategy: str,
    chain_source_available: bool = False,
) -> int:
    metadata = (
        getattr(segment, "metadata_json", {})
        if isinstance(getattr(segment, "metadata_json", {}), dict)
        else {}
    )
    initial_frame_asset_id = getattr(segment, "source_frame_asset_id", None) or metadata.get(
        "initial_frame_asset_id"
    )
    if frame_strategy == CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY:
        return 0 if initial_frame_asset_id else 1
    count = 0 if initial_frame_asset_id else 1
    count += 1
    return count


def _image_frame_cost(quantity: int, production_settings: Any) -> Decimal:
    _ = quantity, production_settings
    return Decimal("0.000000")


def _visual_summary(metadata: dict[str, Any]) -> str:
    names = [
        *list(metadata.get("characters") or []),
        *list(metadata.get("locations") or []),
        *list(metadata.get("props") or []),
    ]
    return ", ".join(str(name) for name in names if str(name).strip())


def _row_from_segment(
    segment: Any,
    production_settings: Any,
    *,
    pending_frame_count: int,
) -> ContinuousVideoSegmentRow:
    metadata = (
        getattr(segment, "metadata_json", {})
        if isinstance(getattr(segment, "metadata_json", {}), dict)
        else {}
    )
    status = normalize_continuous_video_status(
        getattr(segment, "review_status", None) or getattr(segment, "status", "")
    )
    state = continuous_video_progress_state(segment)
    return ContinuousVideoSegmentRow(
        id=segment.id,
        number=int(getattr(segment, "segment_number", 0) or 0),
        title=str(getattr(segment, "title", "") or f"Segmento {int(segment.segment_number):02d}"),
        prompt=str(getattr(segment, "prompt", "") or ""),
        action=str(metadata.get("action") or ""),
        visual_summary=_visual_summary(metadata),
        duration_seconds=int(getattr(segment, "duration_seconds", 0) or 0),
        status=status,
        status_label=continuous_video_status_label(status),
        progress_state=state,
        cost_estimate=_segment_cost(segment),
        pending_frame_count=pending_frame_count,
        frame_cost_estimate=_image_frame_cost(pending_frame_count, production_settings),
        initial_frame_asset_id=(
            getattr(segment, "source_frame_asset_id", None)
            or metadata.get("initial_frame_asset_id")
        ),
        final_frame_asset_id=(
            getattr(segment, "final_frame_asset_id", None) or metadata.get("final_frame_asset_id")
        ),
        validation_errors=continuous_video_segment_validation_errors(segment),
    )


def build_continuous_video_view_model(summary: dict[str, Any]) -> ContinuousVideoViewModel:
    settings = summary.get("production_settings")
    workflow_mode = production_workflow_mode(settings)
    frame_strategy = continuous_video_frame_strategy(settings)
    sorted_segments = sorted(
        list(summary.get("continuous_video_segments", [])),
        key=lambda item: int(getattr(item, "segment_number", 0) or 0),
    )
    rows: list[ContinuousVideoSegmentRow] = []
    chain_source_available = False
    for segment in sorted_segments:
        pending_frame_count = _pending_frame_count(
            segment,
            frame_strategy=frame_strategy,
            chain_source_available=chain_source_available,
        )
        row = _row_from_segment(
            segment,
            settings,
            pending_frame_count=pending_frame_count,
        )
        rows.append(row)
        if frame_strategy == CONTINUOUS_VIDEO_FRAME_STRATEGY_CONTINUITY:
            if row.final_frame_asset_id is not None or pending_frame_count > 0:
                chain_source_available = True
    generated = sum(1 for row in rows if row.status in {"ready", "done", "approved", "succeeded"})
    failed = sum(1 for row in rows if row.status in {"failed", "rejected"})
    running = sum(1 for row in rows if row.status in {"preparing", "generating", "running"})
    pending = len(rows) - generated
    next_row = next(
        (row for row in rows if row.status in {"pending", "retry_scheduled", "failed", "rejected"}),
        None,
    )
    can_prepare = any(
        row.status in {"pending", "retry_scheduled", "failed", "rejected"} for row in rows
    )
    can_conclude = any(row.status in {"ready", "ready_for_review"} for row in rows)
    return ContinuousVideoViewModel(
        workflow_mode=workflow_mode,
        is_continuous_mode=workflow_mode == CONTINUOUS_VIDEO_WORKFLOW_MODE,
        rows=rows,
        total_segments=len(rows),
        generated_segments=generated,
        pending_segments=pending,
        failed_segments=failed,
        running_segments=running,
        total_seconds=sum(row.duration_seconds for row in rows),
        pending_frame_count=sum(row.pending_frame_count for row in rows),
        total_frame_cost_estimate=sum(
            (row.frame_cost_estimate for row in rows),
            Decimal("0.000000"),
        ),
        next_segment_id=next_row.id if next_row is not None else None,
        can_plan=True,
        can_prepare=can_prepare,
        can_conclude=can_conclude,
    )
