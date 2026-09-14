# ruff: noqa: E501, F401, I001

import asyncio
import logging
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.settings import get_settings
from app.costs.service import estimate_operation_cost
from app.database.session import AsyncSessionLocal
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.jobs.service import cancel_generation_job, create_or_get_media_job, dispatch_media_job
from app.production.service import get_or_create_production_settings, update_production_settings
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    is_deleted_ui_context_error,
    loading_status_message,
    safe_close_ui_element,
    show_ai_error_popup,
)
from app.ui.visual.helpers import asset_url
from app.ui.workspace.continuous_video_view_model import (
    build_continuous_video_view_model,
    continuous_video_status_label,
)
from app.ui.workspace.continuous_video_view_model import (
    CONTINUOUS_VIDEO_WORKFLOW_MODE,
)
from app.ui.workspace.video_progress_components import (
    render_continuity_checks as _render_continuity_checks,
    render_generation_progress_summary as _render_generation_progress_summary,
)
from app.video_generation.continuous import (
    _refresh_auto_segment_prompt,
    approve_continuous_video_segment,
    continuous_video_segment_validation_errors,
    delete_all_continuous_video_segments,
    delete_continuous_video_segment,
    delete_continuous_video_variant_assets,
    list_continuous_video_segments,
    plan_continuous_video_segments,
    prepare_continuous_video_package,
    regenerate_continuous_video_segment_frame,
    regenerate_continuous_video_segment_frames,
    reject_continuous_video_segment,
    remove_continuous_video_segment_frame,
    segment_frame_prompts,
    update_continuous_video_segment_frame_prompt,
    update_continuous_video_segment_prompt,
)
from app.video_generation.models import ContinuousVideoSegment, GenerationJob
from app.video_generation.continuous_review import (
    select_continuous_video_segment_variant,
)

logger = logging.getLogger(__name__)

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, Any], Any]


async def _select_continuous_video_variant_from_ui(
    project_id: UUID,
    segment_id: UUID,
    asset_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await select_continuous_video_segment_variant(
                session, project_id, segment_id, asset_id
            )
            await session.commit()
        if segment is None:
            _safe_notify("Shot não encontrado.", color="warning")
            return
        _safe_notify(
            "Vídeo escolhido. O frame de continuidade liberou o próximo segmento.",
            color="positive",
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


def _copy_text_to_clipboard(text: str) -> None:
    import json

    # Serializa o texto do usuário com json.dumps para o payload JS inteiro,
    # evitando injeção de script via concatenação manual de strings.
    payload = json.dumps(str(text))
    ui.run_javascript(
        f"navigator.clipboard.writeText({payload})"
        + ".then(() => {"
        + "  const el = document.createElement('div');"
        + "  el.textContent = 'Prompt copiado!';"
        + "  el.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;"
        + "background:#1c221d;color:#d8dbd8;border:1px solid #343934;border-radius:10px;"
        + "padding:10px 14px;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.4);';"
        + "  document.body.appendChild(el);"
        + "  setTimeout(() => el.remove(), 1800);"
        + "}).catch(() => { window.prompt('Copie o prompt manualmente (Ctrl+C):', "
        + payload
        + "); })"
    )


def _download_continuous_video_segment_frames(
    segment_title: str,
    initial_frame_url: str,
    final_frame_url: str,
) -> None:
    import json
    import re

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(segment_title or "segmento").strip()).strip("-")
    if not slug:
        slug = "segmento"
    downloads = [
        {"url": initial_frame_url, "filename": f"{slug}-frame-inicial.jpg"},
        {"url": final_frame_url, "filename": f"{slug}-frame-final.jpg"},
    ]
    ui.run_javascript(
        "(async () => {"
        f"  const downloads = {json.dumps(downloads)};"
        "  for (const item of downloads) {"
        "    const link = document.createElement('a');"
        "    link.href = item.url;"
        "    link.download = item.filename;"
        "    link.rel = 'noopener';"
        "    link.style.display = 'none';"
        "    document.body.appendChild(link);"
        "    link.click();"
        "    link.remove();"
        "    await new Promise(resolve => setTimeout(resolve, 250));"
        "  }"
        "})()"
    )


def _safe_notify(message: str, **kwargs: Any) -> bool:
    try:
        ui.notify(message, **kwargs)
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    return True


def _safe_reload() -> bool:
    try:
        ui.navigate.reload()
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    return True


def _safe_close_ui_element_quietly(element: object | None) -> None:
    if element is None:
        return
    try:
        close = getattr(element, "close", None)
        if callable(close):
            close()
    except (AssertionError, RuntimeError) as exc:
        if not is_deleted_ui_context_error(exc):
            raise


async def _open_loading_dialog_quietly(element: object | None) -> bool:
    if element is None:
        return False
    try:
        open_dialog = getattr(element, "open", None)
        if callable(open_dialog):
            open_dialog()
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    await asyncio.sleep(0.1)
    return True


def _show_ai_error_unless_context_gone(exc: Exception) -> None:
    if is_deleted_ui_context_error(exc):
        return
    show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


def _video_job_status(job: GenerationJob) -> str:
    status = getattr(job, "status", "")
    return str(getattr(status, "value", status) or "").upper()


def _video_generation_outcome(jobs: list[GenerationJob]) -> tuple[str, str]:
    failed = [job for job in jobs if _video_job_status(job) == GenerationJobStatus.FAILED.value]
    cancelled = [
        job for job in jobs if _video_job_status(job) == GenerationJobStatus.CANCELLED.value
    ]
    succeeded = [
        job for job in jobs if _video_job_status(job) == GenerationJobStatus.SUCCEEDED.value
    ]
    if failed:
        detail = str(getattr(failed[0], "error", "") or "").strip()
        message = "Não foi possível gerar o vídeo."
        if detail:
            message = f"{message} {friendly_ai_error(RuntimeError(detail))}"
        return message, "negative"
    if cancelled:
        return "A geração de vídeo foi cancelada.", "warning"
    if len(succeeded) == 1:
        return "As opções de vídeo do Shot foram criadas com sucesso!", "positive"
    return f"Os vídeos de {len(succeeded)} Shots foram criados com sucesso!", "positive"


def _show_video_generation_result_popup(message: str, color: str) -> bool:
    try:
        is_success = color == "positive"
        with (
            ui.dialog().props(BLOCKING_DIALOG_PROPS) as result_dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(520px,92vw)] gap-4"),
        ):
            with ui.row().classes("items-start gap-3 w-full"):
                ui.icon("check_circle" if is_success else "error_outline").classes(
                    "text-3xl text-lime-200 shrink-0"
                    if is_success
                    else "text-3xl text-red-300 shrink-0"
                )
                with ui.column().classes("gap-1 flex-1"):
                    ui.label("Vídeos criados" if is_success else "Falha na geração").classes(
                        "brand-type text-2xl font-bold"
                    )
                    ui.label(message).classes("text-sm text-[#d8dbd8] leading-6")

            def close_and_reload() -> None:
                result_dialog.close()
                _safe_reload()

            with ui.row().classes("w-full justify-end"):
                ui.button(
                    "Ver resultados" if is_success else "Fechar e atualizar",
                    icon="arrow_forward" if is_success else "refresh",
                    on_click=close_and_reload,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
        result_dialog.open()
    except (AssertionError, RuntimeError) as exc:
        if is_deleted_ui_context_error(exc):
            return False
        raise
    return True


async def _wait_for_video_generation_jobs(
    job_ids: list[UUID],
    *,
    progress_callback: Callable[[int, int, str], Any] | None = None,
    poll_interval_seconds: float = 2.0,
) -> list[GenerationJob]:
    """Acompanha jobs do worker para que a UI comunique o resultado real ao usuário."""
    unique_ids = list(dict.fromkeys(job_ids))
    if not unique_ids:
        return []
    terminal = {
        GenerationJobStatus.SUCCEEDED.value,
        GenerationJobStatus.FAILED.value,
        GenerationJobStatus.CANCELLED.value,
    }
    last_snapshot: tuple[tuple[str, str, int], ...] | None = None
    while True:
        async with AsyncSessionLocal() as session:
            jobs = [await session.get(GenerationJob, job_id) for job_id in unique_ids]
        if any(job is None for job in jobs):
            raise RuntimeError("Um dos jobs de vídeo não foi encontrado durante o acompanhamento.")
        current_jobs = [job for job in jobs if job is not None]
        snapshot = tuple(
            (
                str(job.id),
                _video_job_status(job),
                int(getattr(job, "progress", 0) or 0),
            )
            for job in current_jobs
        )
        statuses = [_video_job_status(job) for job in current_jobs]
        completed = sum(status in terminal for status in statuses)
        # Variantes já extraídas dos jobs em execução: o Vibes gera 4 opções
        # por Shot e o download das variantes acontece DENTRO do job — o
        # response_payload.downloaded_variant_count reflete o progresso real.
        downloaded = sum(
            int((getattr(job, "response_payload", None) or {}).get("downloaded_variant_count") or 0)
            for job in current_jobs
            if _video_job_status(job)
            in {
                GenerationJobStatus.RUNNING.value,
                GenerationJobStatus.RETRY_SCHEDULED.value,
            }
        )
        if snapshot != last_snapshot and progress_callback is not None:
            running = sum(
                status in {
                    GenerationJobStatus.RUNNING.value,
                    GenerationJobStatus.RETRY_SCHEDULED.value,
                }
                for status in statuses
            )
            pending = len(current_jobs) - completed - running
            if completed == len(current_jobs):
                detail = "Geração concluída. Verificando o resultado..."
            elif running:
                variant_note = (
                    f" {downloaded} opção(ões) já extraídas." if downloaded else ""
                )
                detail = (
                    f"Gerando {running} Shot(s); {pending} aguardando. "
                    "O Vibes gera 4 opções de vídeo por Shot e pode levar "
                    f"alguns minutos.{variant_note}"
                )
            else:
                detail = f"{pending} Shot(s) aguardando o worker de vídeo..."
            progress_callback(completed, len(current_jobs), detail)
            last_snapshot = snapshot
        if completed == len(current_jobs):
            return current_jobs
        await asyncio.sleep(max(0.1, poll_interval_seconds))


async def _plan_continuous_video_segments_from_ui(
    project_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            existing_segments = await list_continuous_video_segments(session, project_id)
            preserved_segments = sum(
                bool(
                    getattr(seg, "source_frame_asset_id", None)
                    or getattr(seg, "final_frame_asset_id", None)
                    or getattr(seg, "generated_video_asset_id", None)
                    or getattr(seg, "asset_id", None)
                    or (
                        isinstance(getattr(seg, "metadata_json", {}), dict)
                        and (
                            seg.metadata_json.get("initial_frame_asset_id")
                            or seg.metadata_json.get("final_frame_asset_id")
                            or seg.metadata_json.get("extracted_last_frame_asset_id")
                            or seg.metadata_json.get("video_asset_id")
                        )
                    )
                )
                for seg in existing_segments
            )
            await _open_loading_dialog_quietly(loading_dialog)
            mark_dialog_task_cancelable(loading_dialog)
            _plan, segments, validation_errors = await plan_continuous_video_segments(
                session,
                project_id,
                replace_existing=True,
            )
            await session.commit()
        if validation_errors:
            ui.notify("Segmentos criados com pontos para revisar.", color="warning")
        elif preserved_segments:
            ui.notify(
                f"Planejamento atualizado; {preserved_segments} segmento(s) com trabalho "
                "existente foram preservados.",
                color="positive",
            )
        else:
            ui.notify(f"{len(segments)} segmento(s) planejado(s).", color="positive")
        ui.navigate.reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _delete_all_continuous_video_segments_from_ui(
    project_id: UUID,
) -> None:
    """Deleta todos os segmentos, prompts e conteudos de producao de video."""
    try:
        async with AsyncSessionLocal() as session:
            count = await delete_all_continuous_video_segments(session, project_id)
            await session.commit()
        if count == 0:
            _safe_notify("Nenhum segmento para remover.", color="info")
        else:
            _safe_notify(
                f"{count} segmento(s) removido(s).",
                color="positive",
            )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _delete_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    """Deleta um único segmento (e seus assets) sem tocar nos demais."""
    try:
        async with AsyncSessionLocal() as session:
            deleted = await delete_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if not deleted:
            _safe_notify("Segmento não encontrado.", color="warning")
        else:
            _safe_notify("Segmento removido.", color="positive")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _save_continuous_video_segment_prompts_from_ui(
    project_id: UUID,
    segment_id: UUID,
    video_prompt: str,
    *,
    initial_frame_prompt: str | None = None,
) -> None:
    """Save the media-specific prompts shown together in the Video step."""
    try:
        async with AsyncSessionLocal() as session:
            segment = await update_continuous_video_segment_prompt(
                session,
                project_id,
                segment_id,
                prompt=video_prompt,
            )
            if segment is not None and initial_frame_prompt is not None:
                segment = await update_continuous_video_segment_frame_prompt(
                    session,
                    project_id,
                    segment_id,
                    initial_frame_prompt=initial_frame_prompt,
                )
            else:
                await session.commit()
        if segment is None:
            _safe_notify("Segmento não encontrado.", color="warning")
            return
        _safe_notify("Prompts de frame e vídeo salvos.", color="positive")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


def _normalize_video_workflow_mode_from_ui(_value: object) -> str:
    # O modo de producao e unico: sempre o assistente de pacote de vídeo (continuous_fast).
    return CONTINUOUS_VIDEO_WORKFLOW_MODE


async def _set_video_workflow_mode_from_ui(project_id: UUID, workflow_mode: object) -> None:
    try:
        normalized_workflow_mode = _normalize_video_workflow_mode_from_ui(workflow_mode)
        async with AsyncSessionLocal() as session:
            await update_production_settings(
                session,
                project_id,
                {"workflow_mode": normalized_workflow_mode},
            )
        ui.notify("Modo de produção atualizado.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def _set_continuous_frame_strategy_from_ui(project_id: UUID, strategy: object) -> None:
    """Deprecated: the fast/continuity toggle was removed. Always uses continuity."""
    _safe_notify("Modo continuo e sempre ativo.", color="info")
    _safe_reload()


async def _prepare_continuous_video_package_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> None:
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            prepare_kwargs: dict[str, Any] = {"segment_ids": segment_ids}
            if progress_callback is not None:
                prepare_kwargs["progress_callback"] = progress_callback
            segments, validation_errors = await prepare_continuous_video_package(
                session,
                project_id,
                **prepare_kwargs,
            )
        failed = [
            segment
            for segment in segments
            if str(getattr(segment, "review_status", "") or "").lower() == "failed"
        ]
        if failed:
            metadata = failed[0].metadata_json if isinstance(failed[0].metadata_json, dict) else {}
            message = str(metadata.get("error") or "Não foi possível preparar o pacote.")
            notified = _safe_notify(message, color="negative")
        elif validation_errors:
            first_segment_number = min(validation_errors)
            notified = _safe_notify(
                "Revise o planejamento antes de preparar: "
                + "; ".join(validation_errors[first_segment_number]),
                color="warning",
            )
        elif segments:
            notified = _safe_notify(
                "Pacote de vídeo pronto!",
                color="positive",
            )
        else:
            notified = _safe_notify("Nenhum segmento pendente para preparar.", color="info")
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _generate_continuous_video_from_ui(
    project_id: UUID,
    *,
    segment_ids: list[UUID] | None = None,
    loading_dialog: Any | None = None,
    progress_callback: Callable[[int, int, str], Any] | None = None,
    client: Any | None = None,
) -> None:
    """Enfileira um lote Vibes usando somente o frame inicial de cada segmento."""
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            all_segments = await list_continuous_video_segments(session, project_id)
            segments = list(all_segments)
            if segment_ids is not None:
                requested = set(segment_ids)
                segments = [segment for segment in segments if segment.id in requested]
            validation_errors: dict[int, list[str]] = {}
            queued = []
            settings = get_settings()
            for segment in segments:
                # Segurança para jobs disparados sem recarregar a página após uma
                # atualização do formato de prompt.
                _refresh_auto_segment_prompt(segment)
                if segment.source_frame_asset_id is None:
                    validation_errors[segment.segment_number] = [
                        "Gere o frame inicial ou escolha o vídeo do segmento anterior."
                    ]
                    continue
                metadata = dict(segment.metadata_json or {})
                existing_variants = list(metadata.get("variants") or [])
                # Contador persistente de lotes: garante attempt_key único mesmo
                # depois de as variantes antigas serem removidas (o novo lote
                # SUBSTITUI as opções anteriores, não as acumula).
                batch_number = max(
                    int(metadata.get("video_batch_count") or 0) + 1,
                    (len(existing_variants) // 4) + 1,
                )
                metadata["video_batch_count"] = batch_number
                if existing_variants:
                    downstream_with_video = any(
                        item.segment_number > segment.segment_number
                        and (
                            item.generated_video_asset_id is not None
                            or bool((item.metadata_json or {}).get("variants"))
                        )
                        for item in all_segments
                    )
                    if downstream_with_video:
                        validation_errors[segment.segment_number] = [
                            "Não é possível gerar um novo lote porque a cadeia posterior já "
                            "possui vídeos."
                        ]
                        continue
                    old_continuity_frame_id = metadata.get("extracted_last_frame_asset_id")
                    for next_segment in all_segments:
                        if next_segment.segment_number != segment.segment_number + 1:
                            continue
                        if str(next_segment.source_frame_asset_id or "") == str(
                            old_continuity_frame_id or ""
                        ):
                            next_segment.source_frame_asset_id = None
                            next_metadata = dict(next_segment.metadata_json or {})
                            next_metadata.pop("initial_frame_asset_id", None)
                            next_metadata.pop("continuity_source_variant_asset_id", None)
                            next_segment.metadata_json = next_metadata
                    # Coleta os assets das opções antigas para removê-los (banco +
                    # disco): o novo lote substitui as opções anteriores.
                    old_variant_asset_ids: set[UUID] = set()
                    for variant in existing_variants:
                        raw_id = variant.get("asset_id")
                        if raw_id:
                            try:
                                old_variant_asset_ids.add(UUID(str(raw_id)))
                            except (ValueError, TypeError):
                                pass
                    current_video_id = segment.generated_video_asset_id or segment.asset_id
                    if current_video_id is not None:
                        old_variant_asset_ids.add(current_video_id)
                    segment.asset_id = None
                    segment.generated_video_asset_id = None
                    segment.final_frame_asset_id = None
                    segment.external_operation_id = None
                    segment.generation_job_id = None
                    for key in (
                        "selected_variant_asset_id",
                        "selected_variant_storage_uri",
                        "extracted_last_frame_asset_id",
                        "video_job_id",
                        "video_polling_url",
                        "video_unsigned_urls",
                        "variants",
                    ):
                        metadata.pop(key, None)
                    metadata["awaiting_variant_selection"] = False
                    segment.metadata_json = metadata
                    await delete_continuous_video_variant_assets(
                        session, old_variant_asset_ids
                    )
                decision = await create_or_get_media_job(
                    session,
                    project_id,
                    job_type=GenerationJobType.VIDEO,
                    operation="generate_shot",
                    payload={"segment_id": str(segment.id), "shot_id": str(segment.shot_id)},
                    provider=settings.video_provider or "vibes",
                    model=segment.model,
                    attempt_key=f"batch-{batch_number}",
                    # O job precisa sobreviver a até N regenerações via QA
                    # (cada uma consome 1 attempt): submit + N = N + 1.
                    max_attempts=settings.shot_auto_regeneration_max_attempts + 1,
                )
                if decision.should_dispatch:
                    await dispatch_media_job(decision.job)
                segment.generation_job_id = decision.job.id
                queued.append(decision.job)
            await session.commit()
        if validation_errors:
            notified = _safe_notify(
                "Alguns Shots não foram enfileirados. Revise os erros antes de continuar.",
                color="warning",
                timeout=10000,
                close_button=True,
            )
        elif queued:
            if progress_callback is not None:
                progress_callback(
                    0,
                    len(queued),
                    f"{len(queued)} Shot(s) enviados. O Vibes gera 4 opções de vídeo "
                    "por Shot; aguardando o worker de vídeo...",
                )
            # Espelha a Bíblia Visual: um watcher independente da página acompanha
            # os jobs e recarrega a página assim que cada vídeo fica pronto,
            # mesmo que o usuário feche o diálogo de progresso (allow_background).
            if client is not None and getattr(client, "id", None) is not None:
                from app.ui.workspace.video_reference_state import start_video_generation_watch

                start_video_generation_watch(
                    project_id,
                    frozenset(
                        str(getattr(segment, "generated_video_asset_id", "") or "")
                        for segment in all_segments
                    ),
                    client,
                )
            completed_jobs = await _wait_for_video_generation_jobs(
                [job.id for job in queued],
                progress_callback=progress_callback,
            )
            message, color = _video_generation_outcome(completed_jobs)
            _safe_close_ui_element_quietly(loading_dialog)
            notified = _show_video_generation_result_popup(message, color)
            if notified:
                return
        else:
            notified = _safe_notify(
                "Nenhum segmento pendente para gerar vídeo.",
                color="info",
                timeout=8000,
                close_button=True,
            )
        if notified:
            _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _cancel_continuous_video_segment_from_ui(project_id: UUID, segment_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await session.get(ContinuousVideoSegment, segment_id)
            if (
                segment is None
                or segment.project_id != project_id
                or segment.generation_job_id is None
            ):
                _safe_notify("Job do Shot não encontrado.", color="warning")
                return
            await cancel_generation_job(session, segment.generation_job_id)
        _safe_notify(
            "Cancelamento local registrado; o provider pode não aceitar cancelamento remoto.",
            color="warning",
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _approve_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await approve_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if segment is None:
            _safe_notify("Segmento não encontrado.", color="warning")
            return
        _safe_notify(
            "Segmento concluído. O próximo bloco já pode continuar daqui.", color="positive"
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _reject_continuous_video_segment_from_ui(
    project_id: UUID,
    segment_id: UUID,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await reject_continuous_video_segment(session, project_id, segment_id)
            await session.commit()
        if segment is None:
            _safe_notify("Segmento não encontrado.", color="warning")
            return
        _safe_notify(
            "Segmento marcado para refazer. O pacote será preparado novamente.", color="warning"
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _regenerate_continuous_video_segment_frames_from_ui(
    project_id: UUID,
    segment_id: UUID,
    *,
    loading_dialog: Any | None = None,
) -> None:
    """Regenerate the initial and final frames for a single segment."""
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segment = await regenerate_continuous_video_segment_frames(
                session, project_id, segment_id
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        _safe_notify("Frames regenerados com sucesso.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


async def _remove_continuous_video_segment_frame_from_ui(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            segment = await remove_continuous_video_segment_frame(
                session,
                project_id,
                segment_id,
                frame_kind,
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        frame_label = "inicial" if frame_kind == "initial" else "final"
        _safe_notify(
            f"Frame {frame_label} removido. Use Gerar frames para criar apenas o que falta.",
            color="warning",
        )
        _safe_reload()
    except Exception as exc:
        _show_ai_error_unless_context_gone(exc)


async def _regenerate_continuous_video_segment_frame_from_ui(
    project_id: UUID,
    segment_id: UUID,
    frame_kind: str,
    *,
    loading_dialog: Any | None = None,
    client: Any | None = None,
) -> None:
    """Regenerate only the initial or final frame for a single segment."""
    if block_if_missing_api_keys_for_step("continuous_video"):
        return
    await _open_loading_dialog_quietly(loading_dialog)
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            segment = await regenerate_continuous_video_segment_frame(
                session,
                project_id,
                segment_id,
                frame_kind,
            )
        if segment is None:
            _safe_notify("Segmento nao encontrado.", color="warning")
            return
        frame_label = "inicial" if frame_kind == "initial" else "final"
        _safe_notify(f"Frame {frame_label} regenerado com sucesso.", color="positive")
        _safe_reload()
    except asyncio.CancelledError:
        _safe_notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        _safe_reload()
    except Exception as exc:
        # A geração de frame roda sincronamente na UI (sem job na fila) e pode
        # levar minutos no Meta AI. Se o usuário fechar o diálogo ou a conexão
        # cair, o acompanhamento continua pelo watcher independente — que
        # recarrega a página quando o asset chega ou notifica a falha.
        if client is not None and getattr(client, "id", None) is not None:
            from app.ui.workspace.video_reference_state import start_frame_generation_watch

            known_asset_id = ""
            try:
                async with AsyncSessionLocal() as session:
                    from sqlalchemy import select

                    from app.video_generation.models import ContinuousVideoSegment

                    result = await session.execute(
                        select(ContinuousVideoSegment).where(ContinuousVideoSegment.id == segment_id)
                    )
                    current = result.scalars().first()
                    if current is not None:
                        known_asset_id = str(
                            (
                                current.source_frame_asset_id
                                if frame_kind == "initial"
                                else current.final_frame_asset_id
                            )
                            or ""
                        )
            except Exception:
                logger.warning(
                    "frame_watch_known_asset_failed project_id=%s segment=%s: %s",
                    project_id,
                    segment_id,
                    exc,
                )
            start_frame_generation_watch(
                project_id,
                segment_id,
                frame_kind,
                known_asset_id=known_asset_id,
                client=client,
            )
        _show_ai_error_unless_context_gone(exc)
    finally:
        _safe_close_ui_element_quietly(loading_dialog)


def _video_clip_asset_url(clip: Any) -> str:
    asset_id = getattr(clip, "asset_id", None)
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"


def _asset_content_url(asset_id: Any) -> str:
    if asset_id is None:
        return ""
    return f"/api/v1/assets/{asset_id}/content"




def _render_continuous_media_preview(
    title: str,
    media_url: str,
    *,
    media_kind: str,
    large: bool = False,
    remove_on_click: Callable[[], Any] | None = None,
) -> None:
    if large:
        # A caixa precisa derivar a LARGURA da ALTURA (max 72vh) mantendo 9:16.
        # Usar w-full + aspect-[9/16] + max-h juntos distorce: o max-height
        # limita a altura, a largura fica 100% e a caixa vira panorâmica
        # (medido: 520x450, ratio 1.16) e o object-cover recorta a imagem
        # 9:16 como se fosse 16:9. height + aspect-ratio resolve.
        container_classes = (
            "visual-placeholder h-[min(72vh,142vw)] aspect-[9/16] mx-auto flex items-center "
            "justify-center bg-black overflow-hidden"
        )
    else:
        container_classes = (
            "visual-placeholder max-w-[200px] aspect-[9/16] flex items-center "
            "justify-center bg-black overflow-hidden"
        )
    media_classes = "w-full h-full object-cover"
    with ui.element("div").classes("min-w-0 w-full"):
        ui.label(title).classes("text-xs text-[#8d938e]")
        with ui.element("div").classes(f"{container_classes} relative"):
            if media_url and media_kind == "video":
                ui.video(media_url, controls=True).classes("w-full h-full object-cover")
            elif media_url:
                ui.image(media_url).classes(media_classes)
                if remove_on_click is not None:
                    ui.button(
                        icon="close",
                        on_click=remove_on_click,
                    ).props("round dense unelevated").classes(
                        "absolute top-2 right-2 z-10 bg-[#d94a4a] text-white shadow-lg"
                    )
            else:
                ui.label("Indisponível").classes("text-xs text-[#8d938e]")
