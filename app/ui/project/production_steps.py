from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.jobs.service import enqueue_project_step
from app.storyboards.models import AudioTrack, StoryboardFrame
from app.storytelling.models import Script
from app.ui.project.data import latest as _latest
from app.ui.shared.assistant_state import (
    append_assistant_message_to_chat as _append_assistant_message_to_chat,
)
from app.ui.shared.page_config import friendly_ai_error, show_ai_error_popup
from app.visual_bible.service import (
    visual_reference_completion_message,
    visual_reference_completion_report,
)


async def _run_step(
    project_id: UUID,
    step_key: str,
    loading_dialog: Any | None = None,
) -> None:
    step_messages = {
        "ideas": "Criando ideias.",
        "script": "Criando roteiro.",
        "visual": "Criando prompts visuais.",
        "storyboard": "Criando storyboard.",
        "video": "Preparando video.",
        "finalization": "Finalizando projeto.",
        "quality": "Revisando qualidade.",
    }
    if loading_dialog is not None:
        loading_dialog.open()
    try:
        _append_assistant_message_to_chat(
            project_id,
            step_messages.get(step_key, "Executando etapa."),
        )
        async with AsyncSessionLocal() as session:
            if step_key == "video":
                result = await session.execute(
                    select(StoryboardFrame)
                    .where(StoryboardFrame.project_id == project_id)
                    .order_by(StoryboardFrame.frame_number)
                )
                frames = list(result.scalars())
                if not frames:
                    raise ValueError("gere o storyboard primeiro")
                ui.notify(
                    "Prompts de video prontos. Aprove-os na aba Video para gerar os clipes.",
                    color="info",
                )
                ui.navigate.reload()
                return

            if step_key not in {
                "ideas",
                "script",
                "visual",
                "storyboard",
                "finalization",
                "quality",
            }:
                raise ValueError("etapa sem acao automatica")

            script = await _latest(session, Script, project_id)
            if step_key in {"visual", "storyboard"} and script is None:
                raise ValueError("gere o roteiro primeiro")
            if step_key == "storyboard":
                visual_report = await visual_reference_completion_report(session, project_id)
                if not visual_report["complete"]:
                    raise ValueError(visual_reference_completion_message(visual_report))
            if step_key == "finalization":
                source_audio = await _latest(session, AudioTrack, project_id)
                if source_audio is None:
                    raise ValueError("gere o animatic primeiro")

            await enqueue_project_step(session, project_id, step_key)
        ui.notify("Etapa enfileirada para execucao pelo worker.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        message = friendly_ai_error(exc)
        _append_assistant_message_to_chat(project_id, f"Nao consegui concluir a etapa: {message}")
        if loading_dialog is not None:
            loading_dialog.close()
        show_ai_error_popup(message, details=str(exc))
    finally:
        if loading_dialog is not None:
            loading_dialog.close()
