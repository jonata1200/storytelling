import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.projects.service import sync_project_title
from app.storytelling.models import Briefing, Scene, Script, StoryIdea
from app.storytelling.service import (
    create_story_idea_from_payload,
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
)
from app.ui.project.data import latest as _latest
from app.ui.project.data import scalar_count as _scalar_count
from app.ui.shared.page_config import friendly_ai_error as _friendly_ai_error

logger = logging.getLogger(__name__)
_INITIAL_SCRIPT_TASKS: dict[UUID, asyncio.Task[None]] = {}


def schedule_initial_script_generation(
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
) -> asyncio.Task[None]:
    task = asyncio.create_task(_generate_initial_script_in_background(project_id, source_idea))
    _INITIAL_SCRIPT_TASKS[project_id] = task
    task.add_done_callback(lambda _task: _INITIAL_SCRIPT_TASKS.pop(project_id, None))
    return task


def schedule_initial_script_resume(project_id: UUID) -> asyncio.Task[None]:
    task = asyncio.create_task(_resume_initial_script_in_background(project_id))
    _INITIAL_SCRIPT_TASKS[project_id] = task
    task.add_done_callback(lambda _task: _INITIAL_SCRIPT_TASKS.pop(project_id, None))
    return task


async def cancel_initial_script_generation(project_id: UUID) -> None:
    task = _INITIAL_SCRIPT_TASKS.pop(project_id, None)
    if task is not None and not task.done():
        task.cancel()
    async with AsyncSessionLocal() as session:
        await _set_project_ai_action_status(
            session,
            project_id,
            status="cancelled",
            message="Geracao de roteiro cancelada pelo usuario.",
            error=None,
        )


async def _sync_project_title_from_story(
    session: AsyncSession,
    project_id: UUID,
    title: object,
    *,
    source: str,
) -> None:
    clean_title = str(title or "").strip()
    if not clean_title:
        return
    await sync_project_title(
        session,
        project_id,
        clean_title,
        change_note=f"Project title synchronized from {source}",
    )


def _log_ai_background_failure(message: str, identifier: UUID, exc: Exception) -> None:
    normalized = str(exc).lower()
    expected_terms = (
        "demorou mais",
        "timeout",
        "timed out",
        "rate limit",
        "429",
        "network",
        "connection",
        "dns",
    )
    if any(term in normalized for term in expected_terms):
        logger.warning("%s %s: %s", message, identifier, _friendly_ai_error(exc))
        return
    logger.exception("%s %s", message, identifier)


async def _generate_initial_script(
    session: AsyncSession,
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
    progress: Callable[[str], Awaitable[None]] | None = None,
) -> Script:
    if source_idea is not None:
        if progress is not None:
            await progress("Vou registrar a ideia escolhida dentro deste projeto.")
        idea = await create_story_idea_from_payload(session, project_id, source_idea)
        if idea is None:
            raise ValueError("não foi possível registrar a ideia selecionada")
    else:
        if progress is not None:
            await progress("Vou criar uma ideia base para orientar o roteiro.")
        generated_ideas = await generate_story_ideas(session, project_id)
        if not generated_ideas:
            raise ValueError("não foi possível gerar ideias iniciais")
        idea = generated_ideas[0]
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(idea, "title", ""),
        source="story idea",
    )

    if progress is not None:
        await progress("Vou escrever o roteiro cinematográfico a partir da ideia escolhida.")
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(script, "title", ""),
        source="script title",
    )
    return script


async def _set_project_ai_action_status(
    session: AsyncSession,
    project_id: UUID,
    *,
    status: str,
    message: str,
    action: str = "create_initial_script",
    error: str | None = None,
    record_event: bool = True,
) -> None:
    settings = await get_or_create_production_settings(session, project_id)
    metadata = dict(settings.metadata_json or {})
    previous_action = metadata.get("ai_action")
    previous_events = (
        previous_action.get("events", []) if isinstance(previous_action, dict) else []
    )
    events = [event for event in previous_events if isinstance(event, dict)]
    if (
        record_event
        and (
            not events
            or events[-1].get("message") != message
            or events[-1].get("status") != status
        )
    ):
        events.append(
            {
                "id": f"{action}:{len(events) + 1}",
                "action": action,
                "status": status,
                "message": message,
            }
        )
    metadata["ai_action"] = {
        "action": action,
        "status": status,
        "message": message,
        "error": error,
        "updated_at": datetime.now(UTC).isoformat(),
        "events": events[-60:],
    }
    settings.metadata_json = metadata
    await session.commit()


async def _generate_initial_script_in_background(
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="A IA está criando o roteiro inicial com base na ideia.",
                record_event=False,
            )

            async def report_progress(message: str) -> None:
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="running",
                    message=message,
                    record_event=False,
                )

            await _generate_initial_script(session, project_id, source_idea, report_progress)
            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Roteiro inicial criado.",
                record_event=False,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log_ai_background_failure(
            "Não foi possível gerar roteiro inicial do projeto",
            project_id,
            exc,
        )
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA não conseguiu criar o roteiro inicial.",
                error=_friendly_ai_error(exc),
            )


async def _resume_initial_script_in_background(project_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await ProjectRepository(session).get_project(project_id)
            if project is None:
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="failed",
                    message="A IA não conseguiu criar o roteiro inicial.",
                    error="Projeto não encontrado ou foi apagado.",
                )
                return

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="Retomando a criação do roteiro inicial.",
            )

            script = await _latest(session, Script, project_id)
            if script is not None:
                await _sync_project_title_from_story(
                    session,
                    project_id,
                    getattr(script, "title", ""),
                    source="script title",
                )
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="completed",
                    message="Roteiro inicial criado.",
                )
                return

            story_idea = await _latest(session, StoryIdea, project_id)
            if story_idea is None:
                settings = await get_or_create_production_settings(session, project_id)
                metadata = settings.metadata_json or {}
                source_idea = (
                    metadata.get("source_idea") if isinstance(metadata, dict) else None
                )
                if isinstance(source_idea, dict):
                    await _set_project_ai_action_status(
                        session,
                        project_id,
                        status="running",
                        message="Vou registrar a ideia escolhida dentro deste projeto.",
                    )
                    story_idea = await create_story_idea_from_payload(
                        session, project_id, source_idea
                    )
                    if story_idea is None:
                        raise ValueError("não foi possível registrar a ideia selecionada")
                else:
                    await _set_project_ai_action_status(
                        session,
                        project_id,
                        status="running",
                        message="Vou criar uma ideia base para orientar o roteiro.",
                    )
                    generated_ideas = await generate_story_ideas(session, project_id)
                    if not generated_ideas:
                        raise ValueError("não foi possível gerar ideias iniciais")
                    story_idea = generated_ideas[0]
            await _sync_project_title_from_story(
                session,
                project_id,
                getattr(story_idea, "title", ""),
                source="story idea",
            )

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="Vou escrever o roteiro cinematográfico a partir da ideia aprovada.",
            )
            script = await generate_script(session, project_id, story_idea.id)
            if script is None:
                raise ValueError("não foi possível gerar roteiro")
            await _sync_project_title_from_story(
                session,
                project_id,
                getattr(script, "title", ""),
                source="script title",
            )

            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Roteiro inicial criado.",
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log_ai_background_failure(
            "Não foi possível retomar roteiro inicial do projeto",
            project_id,
            exc,
        )
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA não conseguiu criar o roteiro inicial.",
                error=_friendly_ai_error(exc),
            )


async def _generate_missing_scenes_in_background(project_id: UUID, script_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            settings = await get_or_create_production_settings(session, project_id)
            metadata = settings.metadata_json or {}
            action = metadata.get("ai_action") if isinstance(metadata, dict) else None
            status = str(action.get("status") or "") if isinstance(action, dict) else ""
            if status in {"queued", "running"}:
                return

            scene_count = await _scalar_count(session, Scene, project_id)
            if scene_count > 0:
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="completed",
                    message="Cenas e planos já estávam criados.",
                    action="create_script_scenes",
                )
                return

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="A IA está criando cenas e planos para o roteiro.",
                action="create_script_scenes",
            )
            scenes = await generate_scenes_and_shots(session, project_id, script_id)
            if scenes is None:
                raise ValueError("não foi possível gerar cenas e planos")
            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Cenas e planos criados para o roteiro.",
                action="create_script_scenes",
            )
    except Exception as exc:
        _log_ai_background_failure("Não foi possível gerar cenas do roteiro", script_id, exc)
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA não conseguiu criar cenas e planos.",
                action="create_script_scenes",
                error=_friendly_ai_error(exc),
            )


async def _reload_project_when_script_ready(project_id: UUID) -> bool:
    async with AsyncSessionLocal() as session:
        script = await _latest(session, Script, project_id)
        scene_count = await _scalar_count(session, Scene, project_id)
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        action = metadata.get("ai_action") if isinstance(metadata, dict) else None
        status = str(action.get("status") or "") if isinstance(action, dict) else ""
    if status in {"completed", "failed", "cancelled"} or script is not None or scene_count > 0:
        ui.navigate.reload()
        return True
    return False


def _requests_script_generation(message: str, active: str) -> bool:
    normalized = message.lower()
    generation_terms = (
        "crie",
        "criar",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "monte",
        "montar",
        "produza",
        "produzir",
    )
    script_terms = ("roteiro", "cena", "cenas", "historia", "história")
    if not any(term in normalized for term in generation_terms):
        return False
    return active == "script" or any(term in normalized for term in script_terms)


async def _develop_script_for_existing_project(
    session: AsyncSession, project_id: UUID
) -> tuple[str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return (
            "Este projeto ainda não tem briefing. Crie o projeto pelo chat inicial ou "
            "preencha o briefing primeiro.",
            False,
        )

    script = await _latest(session, Script, project_id)
    if script is not None:
        return (
            "Este projeto já tem roteiro. Posso ajudar a revisar ou seguir para a próxima etapa.",
            False,
        )

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return "Não consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(idea, "title", ""),
        source="story idea",
    )

    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return "Não consegui gerar o roteiro para este projeto.", False
    await _sync_project_title_from_story(
        session,
        project_id,
        getattr(script, "title", ""),
        source="script title",
    )
    return "Roteiro criado.", True


