import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from app.assets.models import Asset
from app.config.settings import get_settings
from app.core.enums import (
    MEDIA_MAX_ATTEMPTS,
    GenerationJobType,
)
from app.video_generation.models import GenerationJob
from app.database.session import AsyncSessionLocal
from app.storage.bridge_job_lifecycle import (
    prune_old_diagnostics,
)
from app.visual_bible.image_generation import generate_visual_reference
from app.visual_bible.models import VisualReference


def _lifecycle_roots() -> list[Path]:
    """Roots de storage varridos pela limpeza de diagnósticos (ARQ-02)."""
    storage_root = get_settings().local_storage_path.resolve()
    return [storage_root]


async def handle_image_job(job: GenerationJob) -> dict[str, Any]:
    # ARQ-05: o cache_clear central mora em MediaWorker.process — este handler
    # não precisa (e não deve) limpar o cache por conta própria.
    # ARQ-02: screenshots/dumps de diagnóstico crescem sem limite; a cada
    # job de imagem, mantemos apenas os mais recentes em todo o storage.
    async with AsyncSessionLocal() as session:
        reference = await generate_visual_reference(
            session,
            job.project_id,
            str(job.request_payload["target_kind"]),
            UUID(str(job.request_payload["target_id"])),
            str(job.request_payload["view_type"]),
            prompt_override=job.request_payload.get("prompt_override"),
        )
        diagnostics_pruned = len(
            prune_old_diagnostics(_lifecycle_roots(), dry_run=False).removed_diagnostics
        )
        return {
            "visual_reference_id": str(reference.id),
            "asset_id": str(reference.asset_id),
            "external_job_id": str(
                (reference.metadata_json or {}).get("external_generation_id") or ""
            ),
            "diagnostics_pruned": diagnostics_pruned,
        }


def default_handlers() -> dict[Any, Any]:
    return {
        GenerationJobType.IMAGE: handle_image_job,
    }
