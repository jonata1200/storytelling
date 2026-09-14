import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.enums import GenerationJobStatus, ProjectStatus
from app.projects.repository import ProjectRepository
from app.storage.service import resolve_storage_path
from app.video_generation.continuous import (
    CONTINUOUS_VIDEO_REVIEW_APPROVED,
    CONTINUOUS_VIDEO_REVIEW_FAILED,
    CONTINUOUS_VIDEO_REVIEW_PENDING,
    CONTINUOUS_VIDEO_REVIEW_READY,
    CONTINUOUS_VIDEO_REVIEW_REJECTED,
    ContinuousVideoProgressCallback,
    _emit_continuous_video_segment_event,
    _set_continuous_video_review_status,
    continuous_video_request_fingerprint,
    continuous_video_segment_idempotency_key,
    continuous_video_segment_is_approved,
    get_continuous_video_segment_by_number,
    get_or_create_continuous_video_plan,
    list_continuous_video_segments,
    normalize_continuous_video_review_status,
    plan_continuous_video_segments,
    prepare_continuous_video_package,
)
from app.video_generation.models import ContinuousVideoSegment
from app.workflows.state_machine import advance_project_status


def _sync_continuous_api() -> None:
    """Mantem monkeypatches aplicados em continuous.py visiveis neste modulo."""
    from app.video_generation import continuous

    for name in (
        "ProjectRepository",
        "_emit_continuous_video_segment_event",
        "advance_project_status",
        "get_continuous_video_segment_by_number",
        "get_or_create_continuous_video_plan",
        "list_continuous_video_segments",
        "plan_continuous_video_segments",
        "prepare_continuous_video_package",
    ):
        globals()[name] = getattr(continuous, name)


async def approve_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    """Conclui o segmento: o usuário criou o vídeo manualmente e marcou como feito."""
    _sync_continuous_api()
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if (
        segment.review_status != CONTINUOUS_VIDEO_REVIEW_READY
        or segment.final_frame_asset_id is None
    ):
        raise ValueError("Somente segmentos com pacote pronto podem ser concluidos.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_APPROVED, note=note)
    segment.status = GenerationJobStatus.SUCCEEDED
    metadata = dict(segment.metadata_json or {})
    metadata["review_decision"] = CONTINUOUS_VIDEO_REVIEW_APPROVED
    metadata["review_decision_at"] = datetime.now(UTC).isoformat()
    metadata["review_previous_status"] = previous_status
    if note is not None:
        metadata["review_note"] = note
    metadata["continuity_summary"] = continuous_video_segment_continuity_summary(segment)
    segment.metadata_json = metadata
    next_segment = await get_continuous_video_segment_by_number(
        session,
        project_id,
        segment.segment_number + 1,
    )
    if next_segment is not None:
            # CORREÇÃO: a propagação automática do frame extraído para o
            # próximo segmento foi REMOVIDA. Apenas registramos uma referência
            # leve (continuity_source_summary) para o toggle do próximo
            # segmento decidir se o frame é herdado.
            next_metadata = dict(next_segment.metadata_json or {})
            next_metadata["continuity_source_summary"] = metadata["continuity_summary"]
            next_segment.metadata_json = next_metadata
    await _emit_continuous_video_segment_event(
        session,
        segment=segment,
        status="done",
        provider=segment.provider,
        model=segment.model,
        message="Segmento concluido: vídeo concluído manualmente.",
    )
    await _advance_project_when_all_flow_segments_done(session, project_id, segment)
    await session.flush()
    return segment


async def mark_continuous_video_segment_done(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    _sync_continuous_api()
    return await approve_continuous_video_segment(
        session,
        project_id,
        segment_id,
        note=note,
    )


async def _advance_project_when_all_flow_segments_done(
    session: AsyncSession,
    project_id: UUID,
    changed_segment: ContinuousVideoSegment,
) -> None:
    _sync_continuous_api()
    if not continuous_video_segment_is_approved(changed_segment):
        return
    segments = await list_continuous_video_segments(session, project_id)
    if not segments or not all(continuous_video_segment_is_approved(item) for item in segments):
        return
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return
    plan = await get_or_create_continuous_video_plan(session, project_id)
    plan.status = "completed"
    advance_project_status(project, ProjectStatus.COMPLETED)


def continuous_video_segment_continuity_summary(segment: ContinuousVideoSegment) -> str:
    metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
    parts = [
        f"Segmento {int(getattr(segment, 'segment_number', 0) or 0):02d}",
        str(getattr(segment, "title", "") or "").strip(),
        str(metadata.get("action") or "").strip(),
        str(metadata.get("continuity") or "").strip(),
    ]
    names = [
        *list(metadata.get("characters") or []),
        *list(metadata.get("locations") or []),
        *list(metadata.get("props") or []),
    ]
    visual_anchor = ", ".join(str(name) for name in names if str(name).strip())
    if visual_anchor:
        parts.append(f"Referencias: {visual_anchor}")
    summary = " | ".join(part for part in parts if part)
    return summary[:800]


async def reject_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    note: str | None = None,
) -> ContinuousVideoSegment | None:
    """Rejeita o pacote: pede para refazer os frames do segmento e downstream."""
    _sync_continuous_api()
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.review_status not in {
        CONTINUOUS_VIDEO_REVIEW_READY,
        CONTINUOUS_VIDEO_REVIEW_APPROVED,
    }:
        raise ValueError("Somente segmentos com pacote pronto podem ser rejeitados.")
    previous_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_REJECTED, note=note)
    segment.status = GenerationJobStatus.PENDING
    segment.final_frame_asset_id = None
    metadata = dict(segment.metadata_json or {})
    metadata["review_decision"] = CONTINUOUS_VIDEO_REVIEW_REJECTED
    metadata["review_decision_at"] = datetime.now(UTC).isoformat()
    metadata["review_previous_status"] = previous_status
    for key in (
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
    ):
        metadata.pop(key, None)
    if note is not None:
        metadata["review_note"] = note
    segment.metadata_json = metadata
    await invalidate_continuous_video_downstream_segments(
        session,
        project_id,
        segment.segment_number,
        reason="upstream_rejected",
    )
    await session.flush()
    return segment


def _reset_continuous_video_segment_for_regeneration(
    segment: ContinuousVideoSegment,
    *,
    reason: str,
) -> None:
    metadata = dict(segment.metadata_json or {})
    previous_asset_id = segment.generated_video_asset_id or segment.asset_id
    if previous_asset_id is not None:
        variants = list(metadata.get("variants") or [])
        snapshot = {
            "asset_id": str(previous_asset_id),
            "provider": segment.provider,
            "model": segment.model,
            "review_status": segment.review_status,
            "review_note": metadata.get("review_note"),
            "archived_at": datetime.now(UTC).isoformat(),
        }
        if not any(item.get("asset_id") == snapshot["asset_id"] for item in variants):
            variants.append(snapshot)
        metadata["variants"] = variants
    if segment.final_frame_asset_id is not None:
        metadata["previous_final_frame_asset_id"] = str(segment.final_frame_asset_id)
    if metadata.get("initial_frame_asset_id"):
        metadata["previous_initial_frame_asset_id"] = str(metadata["initial_frame_asset_id"])
    for key in (
        "initial_frame_asset_id",
        "initial_frame_storage_uri",
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
        "package_error",
        "error",
        "video_job_id",
        "video_polling_url",
        "video_generation_started_at",
    ):
        metadata.pop(key, None)
    metadata["regeneration_reason"] = reason
    metadata["regeneration_requested_at"] = datetime.now(UTC).isoformat()
    segment.status = GenerationJobStatus.PENDING
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.final_frame_asset_id = None
    segment.generated_video_asset_id = None
    segment.asset_id = None
    segment.generation_job_id = None
    segment.external_operation_id = None
    metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata


async def select_continuous_video_segment_variant(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    asset_id: UUID,
) -> ContinuousVideoSegment | None:
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    metadata = dict(segment.metadata_json or {})
    variants = list(metadata.get("variants") or [])
    known = {str(item.get("asset_id")) for item in variants}
    current = segment.generated_video_asset_id or segment.asset_id
    if current:
        known.add(str(current))
    if str(asset_id) not in known:
        raise ValueError("Asset não pertence ao histórico de variantes deste Shot")

    previous_selected_id = str(metadata.get("selected_variant_asset_id") or "")
    if previous_selected_id and previous_selected_id != str(asset_id):
        downstream = [
            item
            for item in await list_continuous_video_segments(session, project_id)
            if item.segment_number > segment.segment_number
            and (
                item.generated_video_asset_id is not None
                or bool((item.metadata_json or {}).get("variants"))
            )
        ]
        if downstream:
            raise ValueError(
                "A escolha não pode ser trocada porque já existem vídeos nos segmentos "
                "seguintes. Remova ou regenere a cadeia posterior primeiro."
            )

    segment.asset_id = asset_id
    segment.generated_video_asset_id = asset_id
    metadata["selected_variant_asset_id"] = str(asset_id)
    selected_asset = await session.get(Asset, asset_id)
    selected_uri = str(getattr(selected_asset, "storage_uri", "") or "").strip()
    if selected_uri:
        metadata["selected_variant_storage_uri"] = selected_uri
        from app.video_generation.continuous_generation import _extract_last_frame_from_video

        selected_path = resolve_storage_path(selected_uri)
        if selected_path is None:
            raise ValueError("O arquivo da opção escolhida não está disponível no armazenamento.")
        extracted_frame_id = await _extract_last_frame_from_video(
            session,
            project_id,
            segment,
            selected_path,
        )
        if extracted_frame_id is None:
            raise ValueError("Não foi possível extrair o frame de continuidade do vídeo escolhido.")
        previous_frame_id = metadata.get("extracted_last_frame_asset_id")
        if previous_frame_id and str(previous_frame_id) != str(extracted_frame_id):
            history = list(metadata.get("continuity_frame_history") or [])
            history.append(str(previous_frame_id))
            metadata["continuity_frame_history"] = history
        segment.final_frame_asset_id = extracted_frame_id
        metadata["extracted_last_frame_asset_id"] = str(extracted_frame_id)

    # A propagação automática do frame extraído para o próximo segmento
    # foi removida: cada segmento sempre gera seu próprio frame inicial.
    next_segment = next(
        (
            item
            for item in await list_continuous_video_segments(session, project_id)
            if item.segment_number == segment.segment_number + 1
        ),
        None,
    )
    if next_segment is not None:
        # A propagação automática do frame extraído para o próximo
        # segmento foi removida. Apenas o segmento atual mantém o frame
        # extraído (segment.final_frame_asset_id); o próximo segmento
        # sempre gera um frame inicial novo.
        pass
    metadata["variant_selected_at"] = datetime.now(UTC).isoformat()
    metadata["awaiting_variant_selection"] = False
    segment.metadata_json = metadata
    _set_continuous_video_review_status(segment, CONTINUOUS_VIDEO_REVIEW_READY)
    await session.flush()
    return segment




async def invalidate_continuous_video_downstream_segments(
    session: AsyncSession,
    project_id: UUID,
    segment_number: int,
    *,
    reason: str = "upstream_regeneration",
) -> list[ContinuousVideoSegment]:
    _sync_continuous_api()
    segments = await list_continuous_video_segments(session, project_id)
    invalidated: list[ContinuousVideoSegment] = []
    for segment in segments:
        if segment.segment_number <= segment_number:
            continue
        if continuous_video_segment_is_approved(segment):
            continue
        _reset_continuous_video_segment_for_regeneration(segment, reason=reason)
        segment.source_segment_id = None
        segment.source_video_asset_id = None
        segment.source_frame_asset_id = None
        invalidated.append(segment)
    await session.flush()
    return invalidated


async def generate_continuous_video_segments(
    session: AsyncSession,
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    max_segments: int | None = None,
    pause_after_current: Callable[[], bool] | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> tuple[list[ContinuousVideoSegment], dict[int, list[str]]]:
    """Gera os vídeos reais dos segmentos usando o provider configurado.

    Fluxo:
    1. Prepara pacotes (frames) dos segmentos pendentes
    2. Gera vídeos usando o frame inicial + prompt
    3. Extrai último frame para o próximo segmento
    """
    _sync_continuous_api()
    from app.video_generation.continuous import get_or_create_production_settings
    from app.video_generation.continuous_generation import (
        generate_video_for_segment,
    )

    # Primeiro preparar os pacotes (frames)
    segments, _validation_errors = await prepare_continuous_video_package(
        session,
        project_id,
        segment_ids=segment_ids,
    )

    errors: dict[int, list[str]] = (
        dict(_validation_errors) if isinstance(_validation_errors, dict) else {}
    )
    if not segments:
        return [], errors

    # Obter configurações de produção
    production_settings = await get_or_create_production_settings(session, project_id)

    # Gerar vídeos para cada segmento pendente
    generated_segments: list[ContinuousVideoSegment] = []
    pending_segments = [
        seg
        for seg in segments
        if (
            str(getattr(seg, "review_status", "") or "").lower() not in {"done", "approved"}
            and (str(getattr(seg, "review_status", "") or "").lower() != "failed" or retry_failed)
        )
    ]
    total_segments = len(pending_segments)
    for idx, segment in enumerate(pending_segments, 1):
        # Adaptar callback de progresso se fornecido
        video_cb = None
        if progress_callback is not None:
            current_index = idx
            current_segment_number = segment.segment_number

            async def _adapted_video_cb(
                cur: int,
                tot: int,
                msg: str,
                *,
                batch_index: int = current_index,
                segment_number: int = current_segment_number,
            ) -> None:
                try:
                    res = progress_callback(
                        batch_index,
                        total_segments,
                        f"Segmento {segment_number:03d}: {msg} ({cur}/{tot})",
                    )
                    if asyncio.iscoroutine(res):
                        await res
                except TypeError:
                    pass

            video_cb = _adapted_video_cb

        # Para segmentos > 1, vincular o frame final extraído do vídeo anterior
        if segment.segment_number > 1 and segment.source_frame_asset_id is None:
            from app.video_generation.continuous import get_continuous_video_segment_by_number

            previous = await get_continuous_video_segment_by_number(
                session, project_id, segment.segment_number - 1
            )
            if previous is not None and previous.final_frame_asset_id is not None:
                segment.source_frame_asset_id = previous.final_frame_asset_id
                metadata = dict(segment.metadata_json or {})
                metadata["initial_frame_asset_id"] = str(previous.final_frame_asset_id)
                segment.metadata_json = metadata
                await session.flush()

        # Gerar vídeo do segmento
        success, message = await generate_video_for_segment(
            session,
            project_id,
            segment,
            production_settings,
            video_cb,
        )
        await session.commit()
        await session.refresh(segment)
        generated_segments.append(segment)

        # Se falhou e não é para retry, parar
        if not success:
            errors.setdefault(segment.segment_number, []).append(message)
            if not retry_failed:
                break

    return generated_segments, errors


async def generate_next_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: prepara o próximo segmento pendente/rejeitado."""
    _sync_continuous_api()
    _ = (provider_name, model, retry_failed, progress_callback)
    segments = await list_continuous_video_segments(session, project_id)
    if not segments:
        _plan, segments, validation_errors = await plan_continuous_video_segments(
            session,
            project_id,
            replace_existing=False,
        )
        if validation_errors:
            first_segment_number = min(validation_errors)
            raise ValueError(
                "Revise o planejamento antes de gerar: "
                + "; ".join(validation_errors[first_segment_number])
            )
    ordered = sorted(segments, key=lambda item: int(item.segment_number or 0))
    next_segment = next(
        (
            segment
            for segment in ordered
            if segment.review_status
            in {
                CONTINUOUS_VIDEO_REVIEW_PENDING,
                CONTINUOUS_VIDEO_REVIEW_REJECTED,
                CONTINUOUS_VIDEO_REVIEW_FAILED,
            }
        ),
        None,
    )
    if next_segment is None:
        return [], []
    prepared, _validation_errors = await prepare_continuous_video_package(
        session,
        project_id,
        segment_ids=[next_segment.id],
    )
    return [], prepared


async def generate_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    retry_failed: bool = False,
    force: bool = False,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: (re)prepara o pacote de um único segmento."""
    _sync_continuous_api()
    _ = (provider_name, model, retry_failed, progress_callback)
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if force:
        _reset_continuous_video_segment_for_regeneration(segment, reason="force_regeneration")
        await invalidate_continuous_video_downstream_segments(
            session,
            project_id,
            segment.segment_number,
            reason="upstream_force_regeneration",
        )
    prepared, _validation_errors = await prepare_continuous_video_package(
        session,
        project_id,
        segment_ids=[segment_id],
    )
    return [], prepared


async def retry_failed_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: reenvia (prepara) um segmento com falha."""
    _sync_continuous_api()
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    if segment.review_status != CONTINUOUS_VIDEO_REVIEW_FAILED:
        raise ValueError("Somente segmentos com falha podem ser reenviados.")
    return await generate_continuous_video_segment(
        session,
        project_id,
        segment_id,
        provider_name=provider_name,
        model=model,
        retry_failed=True,
        progress_callback=progress_callback,
    )


async def regenerate_rejected_continuous_video_segment(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    provider_name: str = "auto",
    model: str | None = None,
    progress_callback: ContinuousVideoProgressCallback | None = None,
) -> tuple[list[Any], list[ContinuousVideoSegment]]:
    """Compatibilidade: (re)prepara um segmento rejeitado."""
    _sync_continuous_api()
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return [], []
    review_status = normalize_continuous_video_review_status(
        getattr(segment, "review_status", None)
    )
    if review_status != CONTINUOUS_VIDEO_REVIEW_REJECTED:
        raise ValueError("Somente segmentos rejeitados podem ser regenerados por este fluxo.")
    metadata = dict(segment.metadata_json or {})
    note = str(metadata.get("review_note") or "").strip()
    if note:
        segment.prompt = f"{segment.prompt.rstrip()}\nOrientação para a revisão: {note}."
        metadata["rejection_note_applied_to_prompt"] = True
        segment.metadata_json = metadata
    return await generate_continuous_video_segment(
        session,
        project_id,
        segment_id,
        provider_name=provider_name,
        model=model,
        force=True,
        progress_callback=progress_callback,
    )


async def extract_continuous_video_segment_frames(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    force: bool = False,
) -> tuple[ContinuousVideoSegment | None, dict[str, str]]:
    """Compatibilidade: os frames do pacote são gerados (não extraídos de vídeo).

    Mantido apenas para a UI; a Fase 3 remove o uso.
    """
    _sync_continuous_api()
    _ = force
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None, {}
    return segment, {}


async def update_continuous_video_segment_prompt(
    session: AsyncSession,
    project_id: UUID,
    segment_id: UUID,
    *,
    prompt: str,
    title: str | None = None,
) -> ContinuousVideoSegment | None:
    _sync_continuous_api()
    segment = await session.get(ContinuousVideoSegment, segment_id)
    if segment is None or segment.project_id != project_id:
        return None
    if segment.review_status == CONTINUOUS_VIDEO_REVIEW_APPROVED:
        raise ValueError("Segmento ja concluido nao pode ter prompt editado.")
    clean_prompt = prompt.strip()
    if len(clean_prompt.split()) < 4:
        raise ValueError("Prompt do segmento esta generico demais.")
    segment.prompt = clean_prompt
    if title is not None:
        segment.title = title.strip()
    metadata = dict(segment.metadata_json or {})
    metadata["custom_prompt"] = True
    segment.metadata_json = metadata
    segment.request_fingerprint = continuous_video_request_fingerprint(
        project_id=project_id,
        segment_number=segment.segment_number,
        prompt=segment.prompt,
        duration_seconds=segment.duration_seconds,
        provider=segment.provider,
        model=segment.model,
        source_segment_id=segment.source_segment_id,
        source_video_asset_id=segment.source_video_asset_id,
        metadata=metadata,
    )
    segment.idempotency_key = continuous_video_segment_idempotency_key(
        project_id,
        segment.segment_number,
        segment.provider,
        segment.model,
        segment.request_fingerprint,
    )
    # O prompt mudou: o frame final (e o pacote) ficam desatualizados.
    segment.review_status = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.status = GenerationJobStatus.PENDING
    segment.final_frame_asset_id = None
    for key in (
        "final_frame_asset_id",
        "final_frame_storage_uri",
        "package_ready_at",
        "package_error",
        "error",
    ):
        metadata.pop(key, None)
    metadata["review_status"] = CONTINUOUS_VIDEO_REVIEW_PENDING
    segment.metadata_json = metadata
    await invalidate_continuous_video_downstream_segments(
        session,
        project_id,
        segment.segment_number,
        reason="prompt_updated",
    )
    await session.flush()
    return segment


async def attach_continuous_video_segment_result(
    session: AsyncSession,
    segment: ContinuousVideoSegment,
    *,
    asset_id: UUID,
    generation_job_id: UUID | None = None,
    external_operation_id: str | None = None,
) -> ContinuousVideoSegment:
    """Legado: registra um resultado de vídeo já existente no segmento."""
    _sync_continuous_api()
    segment.asset_id = asset_id
    if generation_job_id is not None:
        segment.generation_job_id = generation_job_id
    if external_operation_id is not None:
        segment.external_operation_id = external_operation_id
    segment.status = GenerationJobStatus.SUCCEEDED
    await session.flush()
    return segment
