import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from app.assets.models import Asset
from app.config.settings import get_settings
from app.core.enums import GenerationJobType
from app.database.session import AsyncSessionLocal
from app.generation.shot_spec_builder import build_shot_generation_spec
from app.jobs.service import create_or_get_media_job, dispatch_media_job
from app.production.service import get_or_create_production_settings
from app.vibes.ingredients import mark_ingredient_synced
from app.video_generation.continuous_generation import generate_video_for_segment
from app.video_generation.continuous_review import _reset_continuous_video_segment_for_regeneration
from app.video_generation.models import ContinuousVideoSegment, GenerationJob
from app.video_generation.qa import (
    analyze_with_meta,
    extract_video_keyframes,
    persist_qa_result,
    qa_correction_instruction,
)
from app.visual_bible.image_generation import generate_visual_reference
from app.visual_bible.models import VisualReference


async def handle_image_job(job: GenerationJob) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        reference = await generate_visual_reference(
            session,
            job.project_id,
            str(job.request_payload["target_kind"]),
            UUID(str(job.request_payload["target_id"])),
            str(job.request_payload["view_type"]),
            prompt_override=job.request_payload.get("prompt_override"),
        )
        return {
            "visual_reference_id": str(reference.id),
            "asset_id": str(reference.asset_id),
            "external_job_id": str(
                (reference.metadata_json or {}).get("external_generation_id") or ""
            ),
        }


async def handle_ingredient_job(job: GenerationJob) -> dict[str, Any]:
    """Persiste o vínculo retornado por uma sincronização Vibes autorizada."""
    async with AsyncSessionLocal() as session:
        reference = await session.get(
            VisualReference, UUID(str(job.request_payload["reference_id"]))
        )
        if reference is None or reference.project_id != job.project_id:
            raise ValueError("Referência visual não encontrada")
        changed = mark_ingredient_synced(
            reference,
            ingredient_id=str(job.request_payload["ingredient_id"]),
            ingredient_type=str(job.request_payload["ingredient_type"]),
        )
        await session.commit()
        return {
            "reference_id": str(reference.id),
            "ingredient_id": str(job.request_payload["ingredient_id"]),
            "changed": changed,
        }


async def handle_video_job(job: GenerationJob) -> dict[str, Any]:
    segment_id = UUID(str(job.request_payload["segment_id"]))
    async with AsyncSessionLocal() as session:
        segment = await session.get(ContinuousVideoSegment, segment_id)
        if segment is None or segment.project_id != job.project_id:
            raise ValueError("Segmento/Shot não encontrado para geração")
        if segment.generated_video_asset_id is not None:
            existing_asset = await session.get(Asset, segment.generated_video_asset_id)
            if existing_asset is not None:
                return {
                    "segment_id": str(segment.id),
                    "shot_id": str(segment.shot_id) if segment.shot_id else None,
                    "asset_id": str(existing_asset.id),
                    "external_job_id": segment.external_operation_id,
                    "recovered_existing_download": True,
                }
        settings = await get_or_create_production_settings(session, job.project_id)
        succeeded, message = await generate_video_for_segment(
            session, job.project_id, segment, settings
        )
        await session.commit()
        if not succeeded:
            raise RuntimeError(message)
        if segment.generated_video_asset_id is None:
            raise RuntimeError("Geração terminou sem asset de vídeo")
        asset = await session.get(Asset, segment.generated_video_asset_id)
        if asset is None:
            raise RuntimeError("Asset de vídeo não encontrado após geração")
        qa_decision = await create_or_get_media_job(
            session,
            job.project_id,
            job_type=GenerationJobType.QA,
            operation="qa_shot",
            payload={
                "segment_id": str(segment.id),
                "shot_id": str(segment.shot_id),
                "video_path": asset.storage_uri,
                "source_generation_job_id": str(job.id),
            },
            provider="meta",
            model="multimodal",
            attempt_key=str(job.request_payload.get("attempt_key") or "initial"),
            max_attempts=2,
        )
        if qa_decision.should_dispatch:
            await dispatch_media_job(qa_decision.job)
        return {
            "segment_id": str(segment.id),
            "shot_id": str(segment.shot_id) if segment.shot_id else None,
            "asset_id": str(segment.generated_video_asset_id),
            "external_job_id": segment.external_operation_id,
            "qa_job_id": str(qa_decision.job.id),
        }


async def handle_qa_job(job: GenerationJob) -> dict[str, Any]:
    segment_id = UUID(str(job.request_payload["segment_id"]))
    video_path, storage_root, video_size = await asyncio.to_thread(
        _resolve_qa_video,
        str(job.request_payload["video_path"]),
        get_settings().local_storage_path,
    )
    try:
        video_path.relative_to(storage_root)
    except ValueError as exc:
        raise ValueError("Vídeo de QA fora do storage autorizado") from exc
    if video_size <= 0:
        raise ValueError("Vídeo parcial ou vazio não pode passar por QA")
    async with AsyncSessionLocal() as session:
        segment = await session.get(ContinuousVideoSegment, segment_id)
        if segment is None or segment.shot_id is None:
            raise ValueError("QA exige segmento vinculado a Shot")
        spec = await build_shot_generation_spec(session, job.project_id, segment.shot_id)
        frame_dir = video_path.parent / ".qa" / str(segment.id)
        frames = await extract_video_keyframes(video_path, frame_dir)
        assessment = await analyze_with_meta(spec, frames)
        result = await persist_qa_result(
            session,
            project_id=job.project_id,
            shot_id=segment.shot_id,
            segment_id=segment.id,
            generation_job_id=job.id,
            assessment=assessment,
            compiler_version=str(
                (segment.metadata_json or {}).get("prompt_compiler_version") or "unknown"
            ),
        )
        await session.commit()
        regeneration_job_id: str | None = None
        app_settings = get_settings()
        source_job_id = job.request_payload.get("source_generation_job_id")
        source_job = (
            await session.get(GenerationJob, UUID(str(source_job_id))) if source_job_id else None
        )
        if (
            result.decision == "objective_failure"
            and app_settings.shot_auto_regeneration_enabled
            and source_job is not None
            and source_job.attempts < source_job.max_attempts
        ):
            original_prompt = segment.prompt
            correction = qa_correction_instruction(result)
            _reset_continuous_video_segment_for_regeneration(
                segment, reason="qa_objective_failure"
            )
            segment.prompt = f"{original_prompt.rstrip()}\nQA correction: {correction}"
            metadata = dict(segment.metadata_json or {})
            metadata["original_prompt"] = metadata.get("original_prompt") or original_prompt
            metadata["qa_rejection_reason"] = list(result.reasons)
            segment.metadata_json = metadata
            decision = await create_or_get_media_job(
                session,
                job.project_id,
                job_type=GenerationJobType.VIDEO,
                operation="generate_shot",
                payload={"segment_id": str(segment.id), "shot_id": str(segment.shot_id)},
                provider=source_job.provider,
                model=source_job.model,
                attempt_key=f"qa-regeneration-{source_job.attempts + 1}",
                max_attempts=source_job.max_attempts,
            )
            segment.generation_job_id = decision.job.id
            await session.commit()
            if decision.should_dispatch:
                await dispatch_media_job(decision.job)
            regeneration_job_id = str(decision.job.id)
        return {
            "qa_result_id": str(result.id),
            "total_score": result.total_score,
            "decision": result.decision,
            "frame_count": len(frames),
            "regeneration_job_id": regeneration_job_id,
        }


def default_handlers() -> dict[Any, Any]:
    return {
        GenerationJobType.IMAGE: handle_image_job,
        GenerationJobType.VIDEO: handle_video_job,
        GenerationJobType.INGREDIENT: handle_ingredient_job,
        GenerationJobType.QA: handle_qa_job,
    }


def _resolve_qa_video(raw_path: str, storage_path: Path) -> tuple[Path, Path, int]:
    video_path = Path(raw_path).resolve(strict=True)
    storage_root = storage_path.resolve()
    return video_path, storage_root, video_path.stat().st_size
