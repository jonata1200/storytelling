from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.costs.service import estimate_operation_cost
from app.ui.workspace.rules import CONTINUOUS_VIDEO_WORKFLOW_MODE
from app.video_generation.continuous import continuous_video_segment_validation_errors

CONTROL_VISUAL_WORKFLOW_MODE = "keyframes_i2v"
VIDEO_WORKFLOW_MODE_LABELS = {
    CONTROL_VISUAL_WORKFLOW_MODE: "Controle visual",
    CONTINUOUS_VIDEO_WORKFLOW_MODE: "Video continuo economico",
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
    asset_id: UUID | None = None
    model: str = "veo-3.1-fast-generate-preview"
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
    remaining_seconds: int
    total_cost: Decimal
    remaining_cost: Decimal
    next_segment_id: UUID | None
    can_plan: bool
    can_generate_next: bool
    can_generate_all: bool
    can_continue: bool
    can_pause: bool


def production_workflow_mode(settings: Any) -> str:
    mode = str(getattr(settings, "workflow_mode", "") or "").strip()
    return mode or CONTROL_VISUAL_WORKFLOW_MODE


def is_continuous_video_mode(settings: Any) -> bool:
    return production_workflow_mode(settings) == CONTINUOUS_VIDEO_WORKFLOW_MODE


def normalize_continuous_video_status(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def continuous_video_status_label(status: str) -> str:
    return {
        "pending": "Pendente",
        "generating": "Processando",
        "ready_for_review": "Revisar",
        "approved": "Aprovado",
        "rejected": "Rejeitado",
        "retry_scheduled": "Pendente",
        "running": "Processando",
        "succeeded": "Concluido",
        "failed": "Falhou",
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
    if status in {"approved", "ready_for_review", "succeeded"} and segment_id in (
        preexisting_succeeded_ids or set()
    ):
        return "skipped"
    if status in {"approved", "ready_for_review", "succeeded"}:
        return "done"
    if status in {"failed", "rejected"}:
        return "failed"
    if status in {"running", "generating"}:
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
    return estimate_operation_cost(
        "text_to_video",
        Decimal(int(getattr(segment, "duration_seconds", 0) or 0)),
        provider=str(getattr(segment, "provider", "") or "google_ai"),
        model=str(getattr(segment, "model", "") or "veo-3.1-fast-generate-preview"),
    ).estimated


def _visual_summary(metadata: dict[str, Any]) -> str:
    names = [
        *list(metadata.get("characters") or []),
        *list(metadata.get("locations") or []),
        *list(metadata.get("props") or []),
    ]
    return ", ".join(str(name) for name in names if str(name).strip())


def _row_from_segment(segment: Any) -> ContinuousVideoSegmentRow:
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
        title=str(
            getattr(segment, "title", "") or f"Segmento {int(segment.segment_number):02d}"
        ),
        prompt=str(getattr(segment, "prompt", "") or ""),
        action=str(metadata.get("action") or ""),
        visual_summary=_visual_summary(metadata),
        duration_seconds=int(getattr(segment, "duration_seconds", 0) or 0),
        status=status,
        status_label=continuous_video_status_label(status),
        progress_state=state,
        cost_estimate=_segment_cost(segment),
        asset_id=getattr(segment, "asset_id", None),
        model=str(getattr(segment, "model", "") or "veo-3.1-fast-generate-preview"),
        validation_errors=continuous_video_segment_validation_errors(segment),
    )


def build_continuous_video_view_model(summary: dict[str, Any]) -> ContinuousVideoViewModel:
    settings = summary.get("production_settings")
    workflow_mode = production_workflow_mode(settings)
    rows = [
        _row_from_segment(segment)
        for segment in sorted(
            list(summary.get("continuous_video_segments", [])),
            key=lambda item: int(getattr(item, "segment_number", 0) or 0),
        )
    ]
    generated = sum(
        1 for row in rows if row.status in {"ready_for_review", "approved", "succeeded"}
    )
    failed = sum(1 for row in rows if row.status in {"failed", "rejected"})
    running = sum(1 for row in rows if row.status in {"generating", "running"})
    pending = len(rows) - generated
    next_row = next(
        (
            row
            for row in rows
            if row.status in {"pending", "retry_scheduled", "failed", "rejected"}
        ),
        None,
    )
    remaining_rows = [
        row
        for row in rows
        if row.status in {"pending", "retry_scheduled", "failed", "rejected"}
    ]
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
        remaining_seconds=sum(row.duration_seconds for row in remaining_rows),
        total_cost=sum((row.cost_estimate for row in rows), Decimal("0.000000")),
        remaining_cost=sum((row.cost_estimate for row in remaining_rows), Decimal("0.000000")),
        next_segment_id=next_row.id if next_row is not None else None,
        can_plan=True,
        can_generate_next=next_row is not None and running <= 0,
        can_generate_all=bool(remaining_rows) and running <= 0,
        can_continue=failed > 0 and running <= 0,
        can_pause=running > 0,
    )
