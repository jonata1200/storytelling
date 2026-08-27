"""Geração de vídeo dos segmentos contínuos via provider configurado.

A etapa de Produção gera o vídeo real de cada segmento usando o provider e o
modelo configurados. O fluxo é:

1. Primeiro segmento: usa apenas o prompt para gerar vídeo
2. Segmentos seguintes: extrai último frame do vídeo anterior + prompt → gera vídeo

Isso torna o processo mais eficiente, consistente e barato.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.provider_policy import (
    effective_provider_for_channel,
    provider_display_name,
    provider_model,
)
from app.config.settings import get_settings
from app.core.enums import AssetKind, CostEntryType, GenerationJobStatus
from app.costs.models import CostEntry
from app.costs.service import (
    cost_audit_metadata,
    estimate_operation_cost,
    final_budget_cost,
)
from app.production.service import get_or_create_production_settings
from app.providers.media_utils import (
    extract_last_frame_from_video,
    local_uri_to_data_url,
)
from app.providers.registry import resolve_video_provider
from app.providers.storage import generated_output_dir
from app.providers.video.types import (
    VideoGenerationRequest,
    VideoImageInput,
    VideoIngredientInput,
    VideoJob,
    VideoProvider,
)
from app.storage.service import apply_asset_storage_metadata
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_REVIEW_FAILED,
    CONTINUOUS_VIDEO_REVIEW_GENERATING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    _emit_continuous_video_segment_event,
    _set_continuous_video_review_status,
)
from app.video_generation.models import ContinuousVideoSegment, GenerationJob

VIDEO_POLL_INTERVAL_SECONDS = 10.0
VIDEO_MAX_POLL_ATTEMPTS = 180  # ~30 minutos por rodada de polling
TERMINAL_VIDEO_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}
VIDEO_OPERATION = "video_generation"

VideoProgressCallback = Callable[[int, int, str], Awaitable[None] | None]

logger = logging.getLogger(__name__)


def _effective_video_model(production_settings: Any, provider_name: str | None = None) -> str:
    """Retorna o modelo do projeto ou do provider de vídeo configurado."""
    per_project = str(getattr(production_settings, "video_model", "") or "").strip()
    if per_project and per_project not in {"", "manual_package"}:
        return per_project
    settings = get_settings()
    provider = provider_name or effective_provider_for_channel(settings, "video")
    return provider_model(settings, provider, "video")


def _resolve_video_provider() -> str:
    return effective_provider_for_channel(get_settings(), "video")


def _video_provider(provider_name: str | None = None) -> VideoProvider:
    return resolve_video_provider(get_settings(), provider_name or _resolve_video_provider())


async def _submit_video_job(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    production_settings: Any,
) -> str:
    """Submete o job de vídeo do segmento e retorna seu identificador externo."""
    provider_name = _resolve_video_provider()
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="generating",
        provider=provider_name,
        model=_effective_video_model(production_settings),
        message=(
            f"Enviando Segmento {segment.segment_number:02d} para geração "
            f"de vídeo no {provider_display_name(provider_name)}."
        ),
        operation=VIDEO_OPERATION,
    )
    request = await _build_video_request(session, project_id, segment, production_settings)
    provider = _video_provider()
    job = await provider.submit(request)
    segment.external_operation_id = job.id
    if segment.generation_job_id is not None:
        generation_job = await session.get(GenerationJob, segment.generation_job_id)
        if generation_job is not None:
            generation_job.external_job_id = job.id
            response_payload = dict(generation_job.response_payload or {})
            response_payload["polling_url"] = job.polling_url
            response_payload["submitted_at"] = datetime.now(UTC).isoformat()
            generation_job.response_payload = response_payload
    segment.provider = provider.provider_name
    segment.model = request.model
    segment.status = GenerationJobStatus.RUNNING
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_GENERATING)
    metadata = dict(segment.metadata_json or {})
    metadata.pop("error", None)
    metadata.pop("video_generation_error", None)
    metadata["video_job_id"] = job.id
    metadata["video_polling_url"] = job.polling_url
    metadata["video_generation_started_at"] = datetime.now(UTC).isoformat()
    metadata["video_provider"] = provider.provider_name
    metadata["video_model"] = request.model
    segment.metadata_json = metadata
    await session.commit()
    await session.refresh(segment)
    return job.id


async def _build_video_request(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    production_settings: Any,
) -> VideoGenerationRequest:
    """Constrói uma requisição neutra para o provider de vídeo.

    O primeiro segmento usa somente texto. Segmentos seguintes podem usar o
    último frame extraído do vídeo anterior como first_frame.
    """
    settings = get_settings()
    model = _effective_video_model(production_settings, _resolve_video_provider())

    # Preparar frames de referência
    frame_images: list[VideoImageInput] = []

    # Usar frame inicial do segmento (que vem do storyboard ou do último frame do vídeo anterior)
    initial_url = await _asset_data_url(session, segment.source_frame_asset_id)
    if initial_url:
        frame_images.append(VideoImageInput(url=initial_url, frame_type="first_frame"))

    output_dir = generated_output_dir("video", project_id, settings.local_storage_path)
    provider_name = _resolve_video_provider()

    input_references, ingredients = await _approved_video_inputs(session, project_id, segment)
    return VideoGenerationRequest(
        model=model,
        prompt=str(segment.prompt or "").strip(),
        duration=max(1, int(getattr(segment, "duration_seconds", 0) or 0) or 8),
        aspect_ratio=str(production_settings.aspect_ratio or "9:16").strip(),
        resolution=str(production_settings.video_resolution or "720p").strip(),
        generate_audio=bool(getattr(settings, f"{provider_name}_video_generate_audio", True)),
        frame_images=frame_images,
        input_references=input_references,
        ingredients=ingredients,
        output_dir=output_dir,
    )


async def _asset_data_url(session: AsyncSession, asset_id: UUID | None) -> str | None:
    if asset_id is None:
        return None
    asset = await session.get(Asset, asset_id)
    if asset is None:
        return None
    uri = str(getattr(asset, "storage_uri", "") or "").strip()
    if not uri:
        return None
    return local_uri_to_data_url(uri)


async def _approved_video_inputs(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
) -> tuple[list[VideoImageInput], list[VideoIngredientInput]]:
    """Mapeia somente referências aprovadas e ingredients sincronizados."""
    from app.visual_bible.models import Character, Location, VisualReference

    raw_metadata = getattr(segment, "metadata_json", {})
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    target_names = [
        str(name or "").strip()
        for name in [
            *(metadata.get("locations") or []),
            *(metadata.get("characters") or []),
        ]
        if str(name or "").strip()
    ]
    if not target_names:
        return [], []

    loc_result = await session.execute(select(Location).where(Location.project_id == project_id))
    char_result = await session.execute(select(Character).where(Character.project_id == project_id))
    wanted = {name.casefold() for name in target_names}
    target_ids = {
        item.id
        for item in loc_result.scalars().all()
        if str(item.name or "").strip().casefold() in wanted
    }
    target_ids.update(
        item.id
        for item in char_result.scalars().all()
        if str(item.name or "").strip().casefold() in wanted
    )
    if not target_ids:
        return [], []

    ref_result = await session.execute(
        select(VisualReference)
        .where(
            VisualReference.project_id == project_id,
            VisualReference.target_id.in_(target_ids),
            VisualReference.asset_id.is_not(None),
            VisualReference.status == "approved",
        )
        .order_by(VisualReference.is_canonical.desc(), VisualReference.created_at.desc())
    )
    references: list[VideoImageInput] = []
    ingredients: list[VideoIngredientInput] = []
    seen: set[str] = set()
    for ref in ref_result.scalars().all():
        vibes = dict((ref.metadata_json or {}).get("vibes") or {})
        ingredient_id = str(vibes.get("ingredient_id") or "").strip()
        ingredient_type = str(vibes.get("ingredient_type") or "").strip()
        if ingredient_id and ingredient_type and vibes.get("sync_status") == "synced":
            ingredients.append(
                VideoIngredientInput(
                    id=ingredient_id,
                    type=ingredient_type,
                    reference_id=str(ref.id),
                )
            )
        asset = await session.get(Asset, ref.asset_id)
        uri = str(getattr(asset, "storage_uri", "") or "").strip() if asset else ""
        if not uri:
            continue
        data_url = local_uri_to_data_url(uri)
        if not data_url or data_url in seen:
            continue
        seen.add(data_url)
        references.append(VideoImageInput(url=data_url))
        if len(references) >= 4:
            break
    return references, ingredients


async def _poll_video_job(job: Any) -> Any:
    provider = _video_provider(str(getattr(job, "provider", "") or "") or None)
    return await provider.poll(job)


async def _download_video_job(job: Any, output_dir: Path) -> Any:
    provider = _video_provider(str(getattr(job, "provider", "") or "") or None)
    return await provider.download(job, output_dir)


async def _finalize_segment_video(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    job: Any,
    usage_cost: Decimal | None,
) -> None:
    """Finaliza o vídeo do segmento: baixa, salva como Asset e extrai último frame."""
    output_dir = generated_output_dir("video", project_id, get_settings().local_storage_path)
    result = await _download_video_job(job, output_dir)
    model = str(getattr(result, "model", "") or getattr(job, "model", "") or "").strip()
    if not model:
        model = _effective_video_model(
            await get_or_create_production_settings(session, project_id), result.provider
        )

    # Salvar vídeo como Asset
    estimate = estimate_operation_cost(
        VIDEO_OPERATION,
        Decimal(max(1, segment.duration_seconds)),
        provider=result.provider,
        model=model,
    )
    provider_cost = Decimal(str(usage_cost or result.estimated_cost or "0.000000"))
    total_cost = final_budget_cost(estimate.estimated, provider_cost)

    asset = Asset(
        project_id=project_id,
        artifact_id=None,
        kind=AssetKind.VIDEO,
        name=f"Vídeo Segmento {segment.segment_number:03d}",
        storage_uri=result.storage_uri,
        content_type=result.content_type,
        sha256=result.sha256,
        metadata_json={
            "provider": result.provider,
            "model": model,
            "segment_id": str(segment.id),
            "segment_number": segment.segment_number,
            "technical_role": "continuous_video_segment",
            "external_job_id": job.id,
            "provider_job_id": job.id,
            "duration_seconds": segment.duration_seconds,
        },
    )
    apply_asset_storage_metadata(asset)
    session.add(asset)
    await session.flush()

    # Registrar versão do asset
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            metadata_json=asset.metadata_json,
        )
    )

    # Registrar custo
    session.add(
        CostEntry(
            project_id=project_id,
            artifact_id=None,
            entry_type=CostEntryType.ESTIMATE,
            provider=result.provider,
            model=model,
            operation=VIDEO_OPERATION,
            quantity=Decimal(max(1, segment.duration_seconds)),
            unit="second",
            unit_cost=estimate.unit_cost,
            total_cost=total_cost,
            currency=estimate.currency,
            metadata_json=cost_audit_metadata(
                estimated_cost=estimate.estimated,
                provider_reported_cost=provider_cost,
                final_budget_cost=total_cost,
                stage="continuous_video_generation",
                extra={
                    "segment_id": str(segment.id),
                    "segment_number": segment.segment_number,
                },
            ),
        )
    )

    # Extrair último frame do vídeo para o próximo segmento
    last_frame_asset_id = await _extract_last_frame_from_video(
        session, project_id, segment, Path(result.storage_uri)
    )

    # Atualizar segmento
    segment.asset_id = asset.id
    segment.generated_video_asset_id = asset.id
    segment.final_frame_asset_id = last_frame_asset_id
    segment.provider = result.provider
    segment.model = model
    segment.status = GenerationJobStatus.SUCCEEDED
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)

    metadata = dict(segment.metadata_json or {})
    metadata.pop("error", None)
    metadata.pop("video_generation_error", None)
    metadata["video_asset_id"] = str(asset.id)
    metadata["video_storage_uri"] = result.storage_uri
    metadata["video_completed_at"] = datetime.now(UTC).isoformat()

    # Salvar referência ao último frame extraído e vincular ao próximo segmento
    if last_frame_asset_id:
        metadata["extracted_last_frame_asset_id"] = str(last_frame_asset_id)
        next_result = await session.execute(
            select(ContinuousVideoSegment).where(
                ContinuousVideoSegment.project_id == project_id,
                ContinuousVideoSegment.segment_number == segment.segment_number + 1,
            )
        )
        next_segment = next_result.scalars().first()
        if next_segment:
            metadata_next = dict(next_segment.metadata_json or {})
            if not bool(metadata_next.get("continuity_break")):
                next_segment.source_frame_asset_id = last_frame_asset_id
                metadata_next["initial_frame_asset_id"] = str(last_frame_asset_id)
                next_segment.metadata_json = metadata_next

    segment.metadata_json = metadata

    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="video_ready",
        provider=result.provider,
        model=model,
        message=f"Vídeo do Segmento {segment.segment_number:03d} gerado com sucesso.",
        estimated_cost=total_cost,
        details={
            "video_asset_id": str(asset.id),
            "has_extracted_frame": last_frame_asset_id is not None,
        },
    )
    await session.flush()


async def _extract_last_frame_from_video(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    video_path: Path,
) -> UUID | None:
    """Extrai o último frame do vídeo e salva como asset para o próximo segmento.

    Retorna o ID do asset criado ou None se falhar.
    """
    try:
        frame_path = extract_last_frame_from_video(video_path)

        # Criar asset do frame extraído
        import hashlib

        frame_bytes = frame_path.read_bytes()

        asset = Asset(
            project_id=project_id,
            artifact_id=None,
            kind=AssetKind.IMAGE,
            name=f"Frame Extraído - Segmento {segment.segment_number:03d}",
            storage_uri=frame_path.as_posix(),
            content_type="image/jpeg",
            sha256=hashlib.sha256(frame_bytes).hexdigest(),
            metadata_json={
                "provider": "ffmpeg",
                "model": "extracted_frame",
                "segment_id": str(segment.id),
                "segment_number": segment.segment_number,
                "technical_role": "extracted_last_frame",
                "source_video_segment": segment.segment_number,
            },
        )
        apply_asset_storage_metadata(asset)
        session.add(asset)
        await session.flush()

        # Registrar versão
        session.add(
            AssetVersion(
                asset_id=asset.id,
                version_number=1,
                storage_uri=asset.storage_uri,
                sha256=asset.sha256,
                metadata_json=asset.metadata_json,
            )
        )

        logger.info(f"Último frame extraído do Segmento {segment.segment_number:03d}: {frame_path}")

        return asset.id

    except Exception as exc:
        logger.warning(
            f"Falha ao extrair último frame do Segmento {segment.segment_number:03d}: {exc}"
        )
        return None


async def generate_video_for_segment(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    production_settings: Any,
    progress_callback: VideoProgressCallback | None = None,
) -> tuple[bool, str]:
    """Gera o vídeo para um segmento usando o provider configurado.

    Retorna (sucesso, mensagem).
    """
    try:
        metadata = dict(segment.metadata_json or {})
        existing_job_id = str(
            segment.external_operation_id or metadata.get("video_job_id") or ""
        ).strip()
        if existing_job_id and metadata.get("video_polling_url"):
            job_id = existing_job_id
            logger.info(
                "video_job_resume project_id=%s shot_id=%s job_id=%s",
                project_id,
                segment.shot_id,
                job_id,
            )
        else:
            # External ID é persistido/commitado por _submit_video_job antes do polling.
            job_id = await _submit_video_job(session, project_id, segment, production_settings)

        if progress_callback:
            result = progress_callback(0, 1, f"Segmento {segment.segment_number:03d} submetido")
            if asyncio.iscoroutine(result):
                await result

        # Polling até completar
        job = VideoJob(
            id=job_id,
            polling_url=str((segment.metadata_json or {}).get("video_polling_url", "")),
            status="pending",
            provider=str(segment.provider or _resolve_video_provider()),
            model=str(segment.model or ""),
            prompt=str(segment.prompt or ""),
        )

        poll_count = 0
        while True:
            if poll_count >= VIDEO_MAX_POLL_ATTEMPTS:
                raise RuntimeError("Provider de vídeo excedeu o tempo limite de polling")

            await asyncio.sleep(VIDEO_POLL_INTERVAL_SECONDS)
            job_update = await _poll_video_job(job)
            poll_count += 1
            await _emit_continuous_video_segment_event(
                session,
                segment=segment,
                status="polling",
                provider=str(segment.provider or _resolve_video_provider()),
                model=str(segment.model or ""),
                message=f"Polling do Shot retornou {job_update.status}.",
                details={
                    "shot_id": str(segment.shot_id) if segment.shot_id else None,
                    "generation_job_id": (
                        str(segment.generation_job_id) if segment.generation_job_id else None
                    ),
                    "provider_job_id": job.id,
                    "poll_attempt": poll_count,
                },
            )
            if job_update.unsigned_urls:
                job.unsigned_urls = job_update.unsigned_urls

            if job_update.status.lower() in TERMINAL_VIDEO_JOB_STATUSES:
                break

            if progress_callback:
                result = progress_callback(
                    0, 1, f"Segmento {segment.segment_number:03d}: aguardando vídeo..."
                )
                if asyncio.iscoroutine(result):
                    await result

        if job_update.status.lower() in {"failed", "cancelled", "expired"}:
            error_msg = job_update.error or "Geração de vídeo falhou"
            raise RuntimeError(error_msg)

        # Finalizar: baixar vídeo, salvar asset, extrair último frame
        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="downloading",
            provider=str(segment.provider or _resolve_video_provider()),
            model=str(segment.model or ""),
            message="Baixando resultado do Shot.",
            details={"shot_id": str(segment.shot_id) if segment.shot_id else None},
        )
        await _finalize_segment_video(session, project_id, segment, job, None)

        return True, f"Segmento {segment.segment_number:03d} concluído com sucesso"

    except Exception as exc:
        logger.warning(f"Erro ao gerar vídeo para Segmento {segment.segment_number:03d}: {exc}")
        segment.status = GenerationJobStatus.FAILED
        _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_FAILED)
        metadata = dict(segment.metadata_json or {})
        metadata["error"] = str(exc)
        metadata["video_generation_error"] = str(exc)
        metadata["failed_at"] = datetime.now(UTC).isoformat()
        segment.metadata_json = metadata

        await _emit_continuous_video_segment_event(
            session,
            segment=segment,
            status="failed",
            provider=_resolve_video_provider(),
            model=_effective_video_model(
                await get_or_create_production_settings(session, project_id)
            ),
            message=str(exc),
        )
        await session.flush()

        return False, str(exc)
