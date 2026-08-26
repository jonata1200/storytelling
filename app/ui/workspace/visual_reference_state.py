"""Pure state helpers for visual-reference generation in the workspace UI."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.enums import GenerationJobStatus

ACTIVE_VISUAL_REFERENCE_JOB_STATUSES = {
    GenerationJobStatus.PENDING,
    GenerationJobStatus.RUNNING,
    GenerationJobStatus.RETRY_SCHEDULED,
}


@dataclass(frozen=True)
class VisualReferencePollStatus:
    has_new_reference: bool
    has_active_generation: bool
    error: str | None = None
    # Progresso do lote mais recente (para o pop-up de acompanhamento).
    completed: int = 0
    total: int = 0
    active_kind: str = ""


def visual_reference_poll_decision(
    known_reference_ids: frozenset[UUID],
    references: list[Any],
    jobs: list[Any],
) -> tuple[bool, bool]:
    has_new_reference = any(reference.id not in known_reference_ids for reference in references)
    has_active_generation = any(
        job.status in ACTIVE_VISUAL_REFERENCE_JOB_STATUSES
        and str((job.request_payload or {}).get("operation") or "") == "generate_visual_reference"
        for job in jobs
    )
    return has_new_reference, has_active_generation


def visual_reference_generation_key(
    target_kind: object,
    target_id: object,
    view_type: object,
) -> tuple[str, str, str]:
    return str(target_kind), str(target_id), str(view_type)


def visual_reference_resume_keys(
    references: list[Any],
    jobs: list[Any],
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Return completed and currently active items for resumable batch generation."""

    completed = {
        visual_reference_generation_key(
            reference.target_kind,
            reference.target_id,
            reference.view_type,
        )
        for reference in references
        if str(getattr(reference, "status", "generated")) != "rejected"
        and getattr(reference, "asset_id", None) is not None
    }
    active: set[tuple[str, str, str]] = set()
    for job in jobs:
        payload = job.request_payload or {}
        if (
            job.status not in ACTIVE_VISUAL_REFERENCE_JOB_STATUSES
            or str(payload.get("operation") or "") != "generate_visual_reference"
        ):
            continue
        active.add(
            visual_reference_generation_key(
                payload.get("target_kind"),
                payload.get("target_id"),
                payload.get("view_type"),
            )
        )
    return completed, active


def visual_reference_batch_progress(
    completed_keys: set[tuple[str, str, str]],
    active_keys: set[tuple[str, str, str]],
    requested_keys: set[tuple[str, str, str]],
) -> tuple[int, int, str]:
    """Progresso do lote para o pop-up: (concluídas, total, rótulo em geração).

    O total do lote é o número de referências solicitadas na geração atual;
    concluídas conta as desse lote que já têm asset. O rótulo do item em
    andamento evita o pop-up "congelado" enquanto a referência atual é gerada.
    """

    requested = len(requested_keys)
    if not requested:
        return 0, 0, ""
    batch_completed = len(requested_keys & completed_keys)
    active_label = "personagem" if any(key[0] == "character" for key in active_keys) else "local"
    return batch_completed, requested, active_label
