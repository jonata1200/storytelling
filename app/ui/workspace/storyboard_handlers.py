import asyncio
import inspect
from typing import Any
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.storyboards.service import (
    approve_storyboard_prompt,
    approve_storyboard_prompts,
    generate_animatic_bundle,
    generate_storyboard_frames,
    storyboard_frames_need_generation,
    storyboard_prompts_need_approval,
    update_storyboard_prompt,
)
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    block_if_missing_api_keys_for_channels,
    friendly_ai_error,
    play_completion_sound,
    safe_close_ui_element,
    show_ai_error_popup,
)

ProgressCallback = Any


def _is_partial_storyboard_generation_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "continuar de onde parou" in message or "quadro(s) já ficaram salvo" in message


async def _emit_progress(
    callback: ProgressCallback | None,
    completed: int,
    total: int,
    detail: str,
) -> None:
    if callback is None:
        return
    result = callback(completed, total, detail)
    if inspect.isawaitable(result):
        await result


async def generate_storyboards_when_prompts_are_ready(
    session: Any,
    project_id: UUID,
    script_id: UUID,
    *,
    progress_callback: ProgressCallback | None = None,
) -> int | None:
    if await storyboard_prompts_need_approval(session, project_id, script_id):
        return None
    kwargs: dict[str, Any] = {}
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
    frames = await generate_storyboard_frames(session, project_id, script_id, **kwargs)
    if frames is None:
        return None
    if not await storyboard_frames_need_generation(session, project_id, script_id):
        await _emit_progress(
            progress_callback,
            len(frames),
            len(frames),
            (
                "Agora: atualizando o animatic com todos os quadros gerados.\n"
                "Falta: recarregar a etapa de storyboard."
            ),
        )
        await generate_animatic_bundle(session, project_id, script_id)
    return len(frames)


async def approve_storyboard_prompts_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if block_if_missing_api_keys_for_channels(("image",)):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            await _emit_progress(
                progress_callback,
                0,
                1,
                (
                    "Agora: aprovando todos os prompts pendentes.\n"
                    "Falta: liberar a geracao dos quadros."
                ),
            )
            approved_count = await approve_storyboard_prompts(session, project_id, script_id)
            generated_count = await generate_storyboards_when_prompts_are_ready(
                session,
                project_id,
                script_id,
                progress_callback=progress_callback,
            )
        if generated_count is not None:
            ui.notify(
                (
                    f"{approved_count} prompt(s) aprovado(s). "
                    f"{generated_count} storyboard(s) gerado(s)."
                ),
                color="positive",
            )
            play_completion_sound()
            ui.navigate.reload()
            return
        ui.notify(
            (
                f"{approved_count} prompt(s) de storyboard aprovado(s)."
                if approved_count
                else "Os prompts de storyboard ja estavam aprovados."
            ),
            color="positive",
        )
        if approved_count:
            play_completion_sound()
        ui.navigate.reload()
    except asyncio.CancelledError:
        ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
        if _is_partial_storyboard_generation_error(exc):
            ui.navigate.reload()
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


async def approve_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if block_if_missing_api_keys_for_channels(("image",)):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        async with AsyncSessionLocal() as session:
            await _emit_progress(
                progress_callback,
                0,
                1,
                (
                    "Agora: aprovando o prompt selecionado.\n"
                    "Falta: verificar se todos os prompts ja podem gerar quadros."
                ),
            )
            approved = await approve_storyboard_prompt(session, project_id, script_id, shot_id)
            if approved:
                frames = await generate_storyboard_frames(
                    session,
                    project_id,
                    script_id,
                    shot_id=shot_id,
                    approved_only=True,
                    progress_callback=progress_callback,
                )
                generated_count = len(frames or [])
                if not await storyboard_frames_need_generation(session, project_id, script_id):
                    await _emit_progress(
                        progress_callback,
                        generated_count,
                        max(generated_count, 1),
                        (
                            "Agora: atualizando o animatic com todos os quadros gerados.\n"
                            "Falta: recarregar a etapa de storyboard."
                        ),
                    )
                    await generate_animatic_bundle(session, project_id, script_id)
            else:
                generated_count = None
        if generated_count is not None:
            ui.notify(
                f"Prompt aprovado. {generated_count} storyboard(s) gerado(s).",
                color="positive",
            )
            play_completion_sound()
            ui.navigate.reload()
            return
        ui.notify(
            (
                "Prompt de storyboard aprovado."
                if approved
                else "Este prompt de storyboard ja estava aprovado."
            ),
            color="positive",
        )
        if approved:
            play_completion_sound()
        ui.navigate.reload()
    except asyncio.CancelledError:
        ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
        if _is_partial_storyboard_generation_error(exc):
            ui.navigate.reload()
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)


async def save_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    prompt: str,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            updated = await update_storyboard_prompt(
                session,
                project_id,
                script_id,
                shot_id,
                prompt,
            )
        ui.notify(
            (
                "Prompt de storyboard atualizado."
                if updated
                else "Nao encontrei o prompt de storyboard selecionado."
            ),
            color="positive" if updated else "warning",
        )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))


async def generate_storyboards_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    shot_id: UUID | None = None,
    approved_only: bool = False,
    force: bool = False,
    sample_limit: int | None = None,
    loading_dialog: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if block_if_missing_api_keys_for_channels(("image",)):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        should_refresh_animatic = shot_id is None
        async with AsyncSessionLocal() as session:
            kwargs: dict[str, Any] = {
                "shot_id": shot_id,
                "force": force,
                "approved_only": approved_only,
            }
            if sample_limit is not None:
                kwargs["sample_limit"] = sample_limit
            if progress_callback is not None:
                kwargs["progress_callback"] = progress_callback
            frames = await generate_storyboard_frames(session, project_id, script_id, **kwargs)
            if not frames:
                ui.notify("Nao foi possivel gerar storyboards.", color="negative")
                return
            if should_refresh_animatic and not await storyboard_frames_need_generation(
                session,
                project_id,
                script_id,
            ):
                await _emit_progress(
                    progress_callback,
                    len(frames),
                    len(frames),
                    (
                        "Agora: atualizando o animatic com os quadros prontos.\n"
                        "Falta: recarregar a etapa de storyboard."
                    ),
                )
                await generate_animatic_bundle(session, project_id, script_id)
        ui.notify(
            (
                f"Amostra de {len(frames)} storyboard(s) gerada."
                if sample_limit is not None
                else "Storyboards gerados."
            ),
            color="positive",
        )
        play_completion_sound()
        ui.navigate.reload()
    except asyncio.CancelledError:
        ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
        if _is_partial_storyboard_generation_error(exc):
            ui.navigate.reload()
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)
