"""Geração de vídeo dos segmentos contínuos via OpenRouter.

A etapa de Produção de vídeo gera o vídeo real de cada segmento usando o
modelo ``bytedance/seedance-2.0-mini`` do OpenRouter. O fluxo é:

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
from app.providers.video.openrouter import OpenRouterVideoProvider
from app.providers.video.types import VideoGenerationRequest, VideoImageInput, VideoJob
from app.storage.service import apply_asset_storage_metadata
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_REVIEW_FAILED,
    CONTINUOUS_VIDEO_REVIEW_GENERATING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    _emit_continuous_video_segment_event,
    _set_continuous_video_review_status,
)
from app.video_generation.models import ContinuousVideoSegment

OPENROUTER_VIDEO_POLL_INTERVAL_SECONDS = 10.0
OPENROUTER_VIDEO_MAX_POLL_ATTEMPTS = 180  # ~30 minutos por rodada de polling
TERMINAL_VIDEO_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}
VIDEO_OPERATION = "video_generation"

VideoProgressCallback = Callable[[int, int, str], Awaitable[None] | None]

logger = logging.getLogger(__name__)


def _effective_video_model(production_settings: Any) -> str:
    """Retorna o modelo de vídeo: usa seedance-2.0-mini do OpenRouter."""
    per_project = str(getattr(production_settings, "video_model", "") or "").strip()
    if per_project and per_project not in {"", "manual_package"}:
        return per_project
    return str(get_settings().openrouter_video_model or "").strip() or (
        "bytedance/seedance-2.0-mini"
    )


def _resolve_video_provider() -> str:
    from app.config.provider_policy import effective_provider_for_channel

    return effective_provider_for_channel(get_settings(), "video")


def _video_provider() -> OpenRouterVideoProvider:
    provider_name = _resolve_video_provider()
    if provider_name != "openrouter":
        raise ValueError(
            "Provedor de vídeo não suportado para geração real: "
            f"{provider_name or '(vazio)'}. Configure VIDEO_PROVIDER=openrouter."
        )
    return OpenRouterVideoProvider()


async def _submit_video_job(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    production_settings: Any,
) -> str:
    """Submete o job de vídeo do segmento e retorna o job id do OpenRouter."""
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="generating",
        provider="openrouter",
        model=_effective_video_model(production_settings),
        message=(
            f"Enviando Segmento {segment.segment_number:02d} para geração "
            "de vídeo no OpenRouter (seedance-2.0-mini)."
        ),
        operation=VIDEO_OPERATION,
    )
    request = await _build_video_request(session, project_id, segment, production_settings)
    provider = _video_provider()
    job = await provider.submit(request)
    segment.external_operation_id = job.id
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
    """Constrói a requisição de vídeo para o OpenRouter.

    O primeiro segmento usa somente texto. Segmentos seguintes podem usar o
    último frame extraído do vídeo anterior como first_frame.
    """
    settings = get_settings()
    model = _effective_video_model(production_settings)

    # Preparar frames de referência
    frame_images: list[VideoImageInput] = []

    # Usar frame inicial do segmento (que vem do storyboard ou do último frame do vídeo anterior)
    initial_url = await _asset_data_url(session, segment.source_frame_asset_id)
    if initial_url:
        frame_images.append(VideoImageInput(url=initial_url, frame_type="first_frame"))

    output_dir = settings.local_storage_path / "openrouter_videos" / str(project_id)

    return VideoGenerationRequest(
        model=model,
        prompt=str(segment.prompt or "").strip(),
        duration=max(1, int(getattr(segment, "duration_seconds", 0) or 0) or 8),
        aspect_ratio=str(production_settings.aspect_ratio or "9:16").strip(),
        resolution=str(production_settings.video_resolution or "720p").strip(),
        generate_audio=bool(getattr(settings, "openrouter_video_generate_audio", True)),
        frame_images=frame_images,
        input_references=[],
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


async def _removed_video_reference_data_urls(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
) -> list[VideoImageInput]:
    """Retorna referências visuais para o vídeo, filtrando apenas locais.

    Imagens de personagens (fotorrealistas) são excluídas porque ativam
    o filtro de conteúdo do OpenRouter (InputImageSensitiveContentDetected).
    """
    from app.visual_bible.models import Location, VisualReference

    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    loc_names = [
        str(name or "").strip()
        for name in (metadata.get("locations") or [])
        if str(name or "").strip()
    ]
    if not loc_names:
        return []

    loc_result = await session.execute(select(Location).where(Location.project_id == project_id))
    wanted = {name.casefold() for name in loc_names}
    loc_ids = [
        loc.id
        for loc in loc_result.scalars().all()
        if str(getattr(loc, "name", "") or "").strip().casefold() in wanted
    ]
    if not loc_ids:
        return []

    ref_result = await session.execute(
        select(VisualReference).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == "location",
            VisualReference.target_id.in_(loc_ids),
            VisualReference.asset_id.is_not(None),
        )
    )
    references: list[VideoImageInput] = []
    seen: set[str] = set()
    for ref in ref_result.scalars().all():
        asset = await session.get(Asset, ref.asset_id)
        uri = str(getattr(asset, "storage_uri", "") or "").strip() if asset else ""
        if not uri:
            continue
        data_url = local_uri_to_data_url(uri)
        if not data_url or data_url in seen:
            continue
        seen.add(data_url)
        references.append(VideoImageInput(url=data_url))
        if len(references) >= 2:
            break
    return references


async def _poll_video_job(job: Any) -> Any:
    provider = _video_provider()
    return await provider.poll(job)


async def _download_video_job(job: Any, output_dir: Path) -> Any:
    provider = _video_provider()
    return await provider.download(job, output_dir)


async def _finalize_segment_video(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    job: Any,
    usage_cost: Decimal | None,
) -> None:
    """Finaliza o vídeo do segmento: baixa, salva como Asset e extrai último frame."""
    settings = get_settings()
    output_dir = settings.local_storage_path / "openrouter_videos" / str(project_id)
    result = await _download_video_job(job, output_dir)
    model = _effective_video_model(await get_or_create_production_settings(session, project_id))

    # Salvar vídeo como Asset
    estimate = estimate_operation_cost(
        VIDEO_OPERATION,
        Decimal(max(1, segment.duration_seconds)),
        provider="openrouter",
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
            "openrouter_job_id": job.id,
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
            next_segment.source_frame_asset_id = last_frame_asset_id
            metadata_next = dict(next_segment.metadata_json or {})
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
    """Gera o vídeo para um segmento usando OpenRouter (seedance-2.0-mini).

    Retorna (sucesso, mensagem).
    """
    try:
        # Submeter job
        job_id = await _submit_video_job(session, project_id, segment, production_settings)

        if progress_callback:
            result = progress_callback(0, 1, f"Segmento {segment.segment_number:03d} submetido")
            if asyncio.iscoroutine(result):
                await result

        # Polling até completar
        job = VideoJob(
            id=job_id,
            polling_url=f"{get_settings().openrouter_video_base_url}/videos/{job_id}",
            status="pending",
        )

        poll_count = 0
        while True:
            if poll_count >= OPENROUTER_VIDEO_MAX_POLL_ATTEMPTS:
                raise RuntimeError("OpenRouter excedeu tempo limite de polling")

            await asyncio.sleep(OPENROUTER_VIDEO_POLL_INTERVAL_SECONDS)
            job_update = await _poll_video_job(job)
            poll_count += 1
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
            provider="openrouter",
            model=_effective_video_model(
                await get_or_create_production_settings(session, project_id)
            ),
            message=str(exc),
        )
        await session.flush()

        return False, str(exc)
