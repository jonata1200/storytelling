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
from app.ui.shared.page_config import friendly_ai_error, show_ai_error_popup

ProgressCallback = Any


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
        await generate_animatic_bundle(session, project_id, script_id)
    return len(frames)


async def approve_storyboard_prompts_from_ui(
    project_id: UUID,
    script_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
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
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()


async def approve_storyboard_prompt_from_ui(
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    *,
    loading_dialog: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            approved = await approve_storyboard_prompt(session, project_id, script_id, shot_id)
            generated_count = (
                await generate_storyboards_when_prompts_are_ready(
                    session,
                    project_id,
                    script_id,
                    progress_callback=progress_callback,
                )
                if approved
                else None
            )
        if generated_count is not None:
            ui.notify(
                f"Ultimo prompt aprovado. {generated_count} storyboard(s) gerado(s).",
                color="positive",
            )
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
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()


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
    if loading_dialog is not None:
        loading_dialog.open()
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
                await generate_animatic_bundle(session, project_id, script_id)
        ui.notify(
            (
                f"Amostra de {len(frames)} storyboard(s) gerada."
                if sample_limit is not None
                else "Storyboards gerados."
            ),
            color="positive",
        )
        ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()
