from typing import Any
from uuid import UUID

from nicegui import ui

from app.config.model_policy import validate_openrouter_model_name
from app.database.session import AsyncSessionLocal
from app.generation.model_settings import ensure_default_model_settings, set_model_setting
from app.production.service import get_or_create_production_settings, update_production_settings
from app.projects.repository import ProjectRepository
from app.projects.schemas import ProjectCreate
from app.projects.service import (
    create_project,
    hard_delete_all_story_ideas,
    hard_delete_project,
    hard_delete_story_idea_by_payload_id_status,
    purge_application_data,
    rename_project,
)
from app.storytelling.idea_lab import delete_all_ideas, delete_generated_idea, delete_saved_idea
from app.storytelling.models import Briefing
from app.storytelling.schemas import BriefingCreate
from app.storytelling.service import create_briefing
from app.ui.project.data import latest as _latest
from app.ui.shared.page_config import SETTINGS_DATA_URL


async def _rename_project_from_ui(project_id: UUID, title: str, redirect_to: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await rename_project(session, project_id, title)
        if project is None:
            ui.notify("Projeto não encontrado.", color="negative")
            return
        ui.notify("Projeto renomeado.", color="positive")
        ui.navigate.to(redirect_to)
    except Exception as exc:
        ui.notify(f"Não foi possível renomear o projeto: {exc}", color="negative")


async def _delete_project_from_ui(project_id: UUID, redirect_to: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            deleted = await hard_delete_project(session, project_id)
        if not deleted:
            ui.notify("Projeto não encontrado.", color="negative")
            return
        ui.notify("Projeto excluido definitivamente.", color="positive")
        ui.navigate.to(redirect_to)
    except Exception as exc:
        ui.notify(f"Não foi possível excluir o projeto: {exc}", color="negative")


async def _purge_application_data_from_ui() -> None:
    try:
        async with AsyncSessionLocal() as session:
            counts = await purge_application_data(session)
        deleted_ideas = delete_all_ideas()
        projects = counts.get("projects", 0)
        artifacts = counts.get("artifacts", 0)
        ui.notify(
            (
                f"Limpeza definitiva concluida: {projects} projeto(s), "
                f"{artifacts} artefato(s) e {deleted_ideas} ideia(s) do laboratório removidos."
            ),
            color="positive",
        )
        ui.navigate.to(SETTINGS_DATA_URL)
    except Exception as exc:
        ui.notify(f"Não foi possível limpar definitivamente os dados: {exc}", color="negative")


async def _purge_all_ideas_from_ui() -> None:
    try:
        async with AsyncSessionLocal() as session:
            counts = await hard_delete_all_story_ideas(session)
        deleted_local_ideas = delete_all_ideas()
        story_ideas = counts.get("story_ideas", 0)
        ui.notify(
            (
                f"Ideias apagadas definitivamente: {story_ideas} registro(s) do banco "
                f"e {deleted_local_ideas} ideia(s) do laboratório removidos."
            ),
            color="positive",
        )
        ui.navigate.to(SETTINGS_DATA_URL)
    except Exception as exc:
        ui.notify(f"Não foi possível apagar definitivamente as ideias: {exc}", color="negative")


async def _purge_all_projects_from_ui() -> None:
    try:
        async with AsyncSessionLocal() as session:
            counts = await purge_application_data(session)
        projects = counts.get("projects", 0)
        artifacts = counts.get("artifacts", 0)
        ui.notify(
            (
                f"Projetos apagados definitivamente: {projects} projeto(s) "
                f"e {artifacts} artefato(s) removidos do banco."
            ),
            color="positive",
        )
        ui.navigate.to(SETTINGS_DATA_URL)
    except Exception as exc:
        ui.notify(f"Não foi possível apagar definitivamente os projetos: {exc}", color="negative")


async def _delete_lab_idea_from_ui(idea_id: str, source: str) -> bool:
    try:
        async with AsyncSessionLocal() as session:
            delete_status = await hard_delete_story_idea_by_payload_id_status(session, idea_id)
        if delete_status == "blocked":
            ui.notify(
                "Esta ideia já está vinculada a um roteiro/projeto e não foi apagada do banco.",
                color="warning",
            )
            return False
        if source == "saved":
            delete_saved_idea(idea_id)
        else:
            delete_generated_idea(idea_id)
        return True
    except Exception as exc:
        ui.notify(f"Não foi possível apagar definitivamente a ideia: {exc}", color="negative")
        return False


async def _save_model_setting(
    project_id: UUID, task: str, provider: str | None, model: str | None
) -> None:
    try:
        if not provider or not model:
            raise ValueError("informe provider e modelo")
        model = validate_openrouter_model_name(model)
        async with AsyncSessionLocal() as session:
            await set_model_setting(session, project_id, task, provider, model)
        ui.notify("Modelo salvo para está etapa.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Não foi possível salvar modelo: {exc}", color="negative")


async def _save_production_setup(project_id: UUID, payload: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await update_production_settings(session, project_id, payload)
        ui.notify("Core Setup salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Não foi possível salvar Core Setup: {exc}", color="negative")


async def _create_next_episode(project_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await ProjectRepository(session).get_project(project_id)
            briefing = await _latest(session, Briefing, project_id)
            settings = await get_or_create_production_settings(session, project_id)
            if project is None or briefing is None:
                raise ValueError("projeto sem briefing base")
            next_project = await create_project(
                session,
                ProjectCreate(
                    title=f"{project.title} - Episodio {settings.episode_number + 1}",
                    description="Continuidade episodica herdada do projeto anterior.",
                ),
            )
            await update_production_settings(
                session,
                next_project.id,
                {
                    "parent_project_id": project.id,
                    "episode_number": settings.episode_number + 1,
                    "content_type": settings.content_type,
                    "aspect_ratio": settings.aspect_ratio,
                    "image_resolution": settings.image_resolution,
                    "video_resolution": settings.video_resolution,
                    "workflow_mode": settings.workflow_mode,
                    "image_model": settings.image_model,
                    "video_model": settings.video_model,
                    "audio_mode": settings.audio_mode,
                    "motion_intensity": settings.motion_intensity,
                    "metadata_json": {
                        "inherits_from_project_id": str(project.id),
                        "one_line_idea": (
                            f"Continuar a história de {project.title}, mantendo "
                            "personagens, tom emocional e conflitos em aberto."
                        ),
                    },
                },
            )
            await create_briefing(
                session,
                next_project.id,
                BriefingCreate(
                    theme=briefing.theme,
                    audience=briefing.audience,
                    genre=briefing.genre,
                    primary_emotion=briefing.primary_emotion,
                    emotional_intensity=briefing.emotional_intensity,
                    ending_type="continuidade episodica com novo gancho",
                    language=briefing.language,
                    country_context=briefing.country_context,
                    desired_duration_minutes=briefing.desired_duration_minutes,
                    has_narrator=briefing.has_narrator,
                    visual_style=briefing.visual_style,
                    content_objective=briefing.content_objective,
                    call_to_action=briefing.call_to_action,
                    constraints=briefing.constraints,
                ),
            )
            await ensure_default_model_settings(session, next_project.id)
        ui.notify("Próximo episódio criado.", color="positive")
        ui.navigate.to(f"/projects/{next_project.id}")
    except Exception as exc:
        ui.notify(f"Não foi possível criar próximo episódio: {exc}", color="negative")



