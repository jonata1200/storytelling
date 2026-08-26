import asyncio
from typing import Any
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.jobs.service import enqueue_project_step
from app.storytelling.models import Script
from app.ui.project.data import latest as _latest
from app.ui.shared.assistant_state import (
    append_assistant_message_to_chat as _append_assistant_message_to_chat,
)
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    safe_close_ui_element,
    show_ai_error_popup,
)


async def _run_step(
    project_id: UUID,
    step_key: str,
    loading_dialog: Any | None = None,
) -> None:
    step_messages = {
        "ideas": "Criando ideias.",
        "script": "Criando roteiro.",
        "scenes": "Criando cenas e planos.",
        "visual": "Criando prompts visuais.",
        "storyboard": "Criando storyboard.",
        "video": "Preparando pacote de vídeo.",
    }
    if block_if_missing_api_keys_for_step(step_key):
        return
    if loading_dialog is not None:
        loading_dialog.open()
    mark_dialog_task_cancelable(loading_dialog)
    try:
        _append_assistant_message_to_chat(
            project_id,
            step_messages.get(step_key, "Executando etapa."),
        )
        async with AsyncSessionLocal() as session:
            if step_key == "video":
                from app.video_generation.continuous import (
                    plan_continuous_video_segments,
                )

                _plan, segments, validation_errors = await plan_continuous_video_segments(
                    session,
                    project_id,
                    replace_existing=False,
                )
                if validation_errors:
                    first_segment_number = min(validation_errors)
                    raise ValueError(
                        "Revise o planejamento dos segmentos: "
                        + "; ".join(validation_errors[first_segment_number])
                    )
                await session.commit()
                ui.notify(
                    f"Planejamento de vídeo pronto ({len(segments)} segmento(s)). "
                    "Abra a aba Produção de Vídeo para gerar os frames e vídeos manualmente.",
                    color="positive",
                )
                ui.navigate.reload()
                return

            if step_key not in {
                "ideas",
                "script",
                "scenes",
                "visual",
                "storyboard",
            }:
                raise ValueError("etapa sem acao automatica")

            script = await _latest(session, Script, project_id)
            if step_key in {"scenes", "visual", "storyboard"} and script is None:
                raise ValueError("gere o roteiro primeiro")
            await enqueue_project_step(session, project_id, step_key)
        ui.notify("Etapa agendada para execução interna.", color="positive")
        ui.navigate.reload()
    except asyncio.CancelledError:
        ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
    except Exception as exc:
        message = friendly_ai_error(exc)
        _append_assistant_message_to_chat(project_id, f"Não consegui concluir a etapa: {message}")
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)
        show_ai_error_popup(message, details=str(exc))
    finally:
        if loading_dialog is not None:
            safe_close_ui_element(loading_dialog)
