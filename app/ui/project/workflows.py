import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nicegui import background_tasks, ui
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.storytelling.models import Briefing, Scene, Script, StoryIdea
from app.storytelling.service import (
    create_story_idea_from_payload,
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
)
from app.ui.project.data import latest as _latest
from app.ui.project.data import latest_many as _latest_many
from app.ui.project.data import scalar_count as _scalar_count
from app.ui.shared.page_config import friendly_ai_error as _friendly_ai_error

logger = logging.getLogger(__name__)

def _log_ai_background_failure(message: str, identifier: UUID, exc: Exception) -> None:
    normalized = str(exc).lower()
    expected_terms = (
        "demorou mais",
        "timeout",
        "timed out",
        "openrouter",
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
            raise ValueError("nao foi possivel registrar a ideia selecionada")
    else:
        if progress is not None:
            await progress("Vou criar uma ideia base para orientar o roteiro.")
        generated_ideas = await generate_story_ideas(session, project_id)
        if not generated_ideas:
            raise ValueError("nao foi possivel gerar ideias iniciais")
        idea = generated_ideas[0]

    if progress is not None:
        await progress("Vou escrever o roteiro cinematografico a partir da ideia escolhida.")
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("nao foi possivel gerar roteiro")
    if progress is not None:
        await progress("Roteiro criado. Agora vou separar a historia em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("nao foi possivel gerar cenas e planos")
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
                message="A IA esta criando o roteiro inicial com base na ideia.",
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
    except Exception as exc:
        _log_ai_background_failure(
            "Nao foi possivel gerar roteiro inicial do projeto",
            project_id,
            exc,
        )
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA nao conseguiu criar o roteiro inicial.",
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
                    message="A IA nao conseguiu criar o roteiro inicial.",
                    error="Projeto nao encontrado ou foi apagado.",
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
                existing_scenes = await _latest_many(session, Scene, project_id, 1)
                if not existing_scenes:
                    await _set_project_ai_action_status(
                        session,
                        project_id,
                        status="running",
                        message="Roteiro encontrado. Vou criar cenas e planos.",
                    )
                    generated_scenes = await generate_scenes_and_shots(
                        session, project_id, script.id
                    )
                    if generated_scenes is None:
                        raise ValueError("nao foi possivel gerar cenas e planos")
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="completed",
                    message="Roteiro inicial criado.",
                )
                return

            story_idea = await _latest(session, StoryIdea, project_id)
            if story_idea is None:
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="running",
                    message="Vou criar uma ideia base para orientar o roteiro.",
                )
                generated_ideas = await generate_story_ideas(session, project_id)
                if not generated_ideas:
                    raise ValueError("nao foi possivel gerar ideias iniciais")
                story_idea = generated_ideas[0]

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="Vou escrever o roteiro cinematografico a partir da ideia aprovada.",
            )
            script = await generate_script(session, project_id, story_idea.id)
            if script is None:
                raise ValueError("nao foi possivel gerar roteiro")

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="Roteiro criado. Agora vou separar a historia em cenas e planos.",
            )
            generated_scenes = await generate_scenes_and_shots(session, project_id, script.id)
            if generated_scenes is None:
                raise ValueError("nao foi possivel gerar cenas e planos")

            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Roteiro inicial criado.",
            )
    except Exception as exc:
        _log_ai_background_failure(
            "Nao foi possivel retomar roteiro inicial do projeto",
            project_id,
            exc,
        )
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA nao conseguiu criar o roteiro inicial.",
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
                    message="Cenas e planos ja estavam criados.",
                    action="create_script_scenes",
                )
                return

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="A IA esta criando cenas e planos para o roteiro.",
                action="create_script_scenes",
            )
            scenes = await generate_scenes_and_shots(session, project_id, script_id)
            if scenes is None:
                raise ValueError("nao foi possivel gerar cenas e planos")
            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Cenas e planos criados para o roteiro.",
                action="create_script_scenes",
            )
    except Exception as exc:
        _log_ai_background_failure("Nao foi possivel gerar cenas do roteiro", script_id, exc)
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA nao conseguiu criar cenas e planos.",
                action="create_script_scenes",
                error=_friendly_ai_error(exc),
            )


async def _reload_project_when_script_ready(project_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        script = await _latest(session, Script, project_id)
        scene_count = await _scalar_count(session, Scene, project_id)
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        action = metadata.get("ai_action") if isinstance(metadata, dict) else None
        status = str(action.get("status") or "") if isinstance(action, dict) else ""
    if status in {"completed", "failed"} or (script is not None and scene_count > 0):
        ui.navigate.reload()


def _retry_initial_script_from_ui(project_id: UUID, loading_dialog: Any) -> None:
    loading_dialog.open()
    background_tasks.create(
        _resume_initial_script_in_background(project_id),
        name=f"retry initial script {project_id}",
    )
    ui.timer(5.0, lambda: _reload_project_when_script_ready(project_id))
    ui.notify("Retomando a criação do roteiro.", color="positive")


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
            "Este projeto ainda nao tem briefing. Crie o projeto pelo chat inicial ou "
            "preencha o briefing primeiro.",
            False,
        )

    script = await _latest(session, Script, project_id)
    if script is not None:
        scenes_count = await _scalar_count(session, Scene, project_id)
        if scenes_count == 0:
            await generate_scenes_and_shots(session, project_id, script.id)
            return "O roteiro ja existia; criei as cenas e planos para ele.", True
        return (
            "Este projeto ja tem roteiro e cenas. Posso ajudar a revisar ou ajustar a estrutura.",
            False,
        )

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return "Nao consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return "Nao consegui gerar o roteiro para este projeto.", False
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return "O roteiro foi criado, mas nao consegui gerar as cenas e planos.", True
    return "Roteiro criado e dividido em cenas e planos.", True



