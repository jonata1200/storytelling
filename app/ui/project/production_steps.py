import asyncio
from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame
from app.storyboards.service import generate_animatic_bundle, generate_storyboard_frames
from app.storytelling.models import Script, StoryIdea
from app.storytelling.service import (
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
)
from app.ui.project.data import latest as _latest
from app.ui.shared.assistant_state import (
    append_assistant_message_to_chat as _append_assistant_message_to_chat,
)
from app.ui.shared.page_config import UI_GENERATION_TIMEOUT_SECONDS
from app.visual_bible.service import generate_visual_bible


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
            if step_key == "ideas":
                await asyncio.wait_for(
                    generate_story_ideas(session, project_id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
            elif step_key == "script":
                idea = await _latest(session, StoryIdea, project_id)
                if idea is None:
                    ideas = await asyncio.wait_for(
                        generate_story_ideas(session, project_id),
                        timeout=UI_GENERATION_TIMEOUT_SECONDS,
                    )
                    if not ideas:
                        raise ValueError("nao foi possivel gerar uma ideia base")
                    idea = ideas[0]
                script = await asyncio.wait_for(
                    generate_script(session, project_id, idea.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                if script is None:
                    raise ValueError("nao foi possivel gerar roteiro")
                await asyncio.wait_for(
                    generate_scenes_and_shots(session, project_id, script.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
            elif step_key == "visual":
                script = await _latest(session, Script, project_id)
                if script is None:
                    raise ValueError("gere o roteiro primeiro")
                visual = await asyncio.wait_for(
                    generate_visual_bible(session, project_id, script.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                if visual is None:
                    raise ValueError("nao foi possivel criar a Biblioteca visual")
                ui.notify(
                    "Prompts visuais criados. Revise e aprove para gerar as imagens.",
                    color="info",
                )
                ui.navigate.reload()
                return
            elif step_key == "storyboard":
                script = await _latest(session, Script, project_id)
                if script is None:
                    raise ValueError("gere o roteiro primeiro")
                await asyncio.wait_for(
                    generate_storyboard_frames(session, project_id, script.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                await asyncio.wait_for(
                    generate_animatic_bundle(session, project_id, script.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
            elif step_key == "video":
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
            elif step_key == "finalization":
                source_audio = await _latest(session, AudioTrack, project_id)
                if source_audio is None:
                    raise ValueError("gere o animatic primeiro")
                final_audio = await asyncio.wait_for(
                    synthesize_narration(
                        session, project_id, source_audio.id, "pt-br-warm-narrator"
                    ),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                if final_audio is None:
                    raise ValueError("nao foi possivel gerar narracao")
                subtitle = await asyncio.wait_for(
                    generate_subtitles(session, project_id, final_audio.id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                animatic = await _latest(session, Animatic, project_id)
                timeline = await asyncio.wait_for(
                    create_final_timeline(
                        session, project_id, animatic.id if animatic else None
                    ),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
                if timeline is None:
                    raise ValueError("gere clipes de video primeiro")
                await asyncio.wait_for(
                    export_timeline(
                        session,
                        project_id,
                        timeline.id,
                        subtitle.id if subtitle else None,
                    ),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
            elif step_key == "quality":
                await asyncio.wait_for(
                    run_quality_check(session, project_id),
                    timeout=UI_GENERATION_TIMEOUT_SECONDS,
                )
            else:
                raise ValueError("etapa sem acao automatica")
        ui.notify("Etapa executada com sucesso.", color="positive")
        ui.navigate.reload()
    except TimeoutError:
        message = f"Etapa demorou mais de {UI_GENERATION_TIMEOUT_SECONDS}s e foi interrompida."
        _append_assistant_message_to_chat(project_id, message)
        ui.notify(message, color="warning")
    except Exception as exc:
        _append_assistant_message_to_chat(project_id, f"Nao consegui concluir a etapa: {exc}")
        ui.notify(f"Acao interrompida: {exc}", color="warning")
    finally:
        if loading_dialog is not None:
            loading_dialog.close()



