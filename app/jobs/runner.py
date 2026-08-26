import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import GenerationJobStatus, ProjectStep
from app.database.session import AsyncSessionLocal
from app.jobs.service import (
    get_job,
    mark_job_failed,
    mark_job_progress,
    mark_job_running,
    mark_job_succeeded,
    project_job_can_run,
)
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact
from app.projects.service import sync_project_title
from app.projects.versioning import (
    INACTIVE_DERIVED_STATUSES,
)
from app.storytelling.models import Briefing, Scene, Script, StoryIdea
from app.storytelling.service import (
    coerce_script_duration_minutes,
    create_story_idea_from_payload,
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
)
from app.video_generation.models import GenerationJob

logger = logging.getLogger(__name__)


async def _latest(session: AsyncSession, model: type[Any], project_id: UUID) -> Any | None:
    result = await session.execute(
        select(model).where(model.project_id == project_id).order_by(model.created_at.desc())
    )
    return result.scalars().first()


async def _emit_step_event(
    session: AsyncSession,
    job: GenerationJob,
    *,
    step: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=job.project_id,
            job_id=job.id,
            event_type="project_step",
            status=status,
            provider=job.provider,
            model=job.model,
            operation=step,
            message=message,
            details=details or {},
        ),
    )
    await session.commit()


async def _apply_target_duration_to_briefing(
    session: AsyncSession,
    project_id: UUID,
    payload: dict[str, Any],
) -> None:
    if payload.get("target_duration_minutes") is None:
        return
    result = await session.execute(
        select(Briefing)
        .where(Briefing.project_id == project_id)
        .order_by(Briefing.created_at.desc())
    )
    briefing = result.scalars().first()
    if briefing is None:
        return
    briefing.desired_duration_minutes = Decimal(
        str(coerce_script_duration_minutes(payload.get("target_duration_minutes")))
    )
    await session.flush()


async def _sync_project_title_from_script(
    session: AsyncSession,
    project_id: UUID,
    script: Script,
) -> None:
    title = str(getattr(script, "title", "") or "").strip()
    if not title:
        return
    await sync_project_title(
        session,
        project_id,
        title,
        change_note="Project title synchronized from generated script title",
    )


async def _run_initial_script(
    session: AsyncSession,
    project_id: UUID,
    payload: dict,
) -> dict[str, Any]:
    await _apply_target_duration_to_briefing(session, project_id, payload)
    source_idea = payload.get("source_idea")
    if isinstance(source_idea, dict):
        idea = await create_story_idea_from_payload(session, project_id, source_idea)
        if idea is None:
            raise ValueError("não foi possível registrar a ideia selecionada")
    else:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            raise ValueError("não foi possível gerar ideias iniciais")
        idea = ideas[0]
    script = await generate_script(
        session,
        project_id,
        idea.id,
        payload.get("target_duration_minutes"),
        story_hook=payload.get("story_hook"),
    )
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    await _sync_project_title_from_script(session, project_id, script)
    return {"script_id": str(script.id)}


async def _run_script(
    session: AsyncSession, project_id: UUID, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    await _apply_target_duration_to_briefing(session, project_id, payload)
    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        source_idea = metadata.get("source_idea") if isinstance(metadata, dict) else None
        if isinstance(source_idea, dict):
            idea = await create_story_idea_from_payload(session, project_id, source_idea)
            if idea is None:
                raise ValueError("não foi possível registrar a ideia selecionada")
        else:
            ideas = await generate_story_ideas(session, project_id)
            if not ideas:
                raise ValueError("não foi possível gerar uma ideia base")
            idea = ideas[0]
    script = await generate_script(
        session,
        project_id,
        idea.id,
        payload.get("target_duration_minutes"),
        story_hook=payload.get("story_hook"),
    )
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    await _sync_project_title_from_script(session, project_id, script)
    return {"script_id": str(script.id)}


async def _run_scenes(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    script = await _latest(session, Script, project_id)
    if script is None:
        raise ValueError("gere o roteiro primeiro")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("não foi possível gerar cenas e planos")
    return {"script_id": str(script.id), "scene_count": len(scenes)}


async def _active_scene_count_for_script(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(Scene)
        .join(Artifact, Artifact.id == Scene.artifact_id)
        .where(
            Scene.project_id == project_id,
            Scene.script_id == script_id,
            Artifact.status.notin_(INACTIVE_DERIVED_STATUSES),
        )
    )
    return int(value or 0)


async def run_project_step_job(job_id: UUID) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        job = await get_job(session, job_id)
        if job is None:
            raise ValueError("Job não encontrado.")
        step = str(job.request_payload.get("step") or "")
        payload = job.request_payload.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        if not project_job_can_run(job):
            return dict(job.response_payload or {})

        await mark_job_running(
            session,
            job,
            message=f"Executor interno iniciou a etapa {step}.",
        )
        await _emit_step_event(
            session,
            job,
            step=step,
            status="started",
            message=f"Executor interno iniciou a etapa {step}.",
            details={"attempt": job.attempts},
        )
        response: dict[str, Any] | None = None
        try:
            await mark_job_progress(session, job, progress=20, message=f"Executando {step}.")
            if step == ProjectStep.INITIAL_SCRIPT:
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Criando roteiro inicial.",
                )
                response = await _run_initial_script(session, job.project_id, payload)
            elif step == ProjectStep.IDEAS:
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Criando ideias narrativas.",
                )
                ideas = await generate_story_ideas(session, job.project_id)
                response = {"idea_count": len(ideas or [])}
            elif step == ProjectStep.SCRIPT:
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Escrevendo roteiro cinematográfico.",
                )
                response = await _run_script(session, job.project_id, payload)
            elif step == ProjectStep.SCENES:
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Separando roteiro em cenas e planos.",
                )
                response = await _run_scenes(session, job.project_id)
            else:
                await mark_job_failed(
                    session,
                    job,
                    error=f"Etapa de job inválida: {step or '<vazia>'}",
                    message=f"Etapa {step or '<vazia>'} invalida e ignorada.",
                )
                await _emit_step_event(
                    session,
                    job,
                    step=step,
                    status="failed",
                    message=f"Etapa {step or '<vazia>'} invalida e ignorada.",
                    details={"error": f"Etapa invalida: {step or '<vazia>'}"},
                )
                return {}
        except Exception as exc:
            await session.rollback()
            await mark_job_failed(
                session,
                job,
                error=str(exc),
                message=f"Etapa {step} falhou.",
            )
            await _emit_step_event(
                session,
                job,
                step=step,
                status="failed",
                message=f"Etapa {step} falhou.",
                details={"error": str(exc), "attempt": job.attempts},
            )
            raise
        # Re-checa o status no banco antes de marcar sucesso: o cancelamento é
        # distribuído (outro processo pode ter marcado CANCELLED via
        # cancel_generation_job enquanto esta etapa longa rodava). Sem esta
        # guarda, mark_job_succeeded sobrescreveria o cancelamento.
        await session.refresh(job)
        if job.status == GenerationJobStatus.CANCELLED:
            logger.info("project_step_cancelled_after_run job_id=%s", job.id)
            return dict(job.response_payload or {})
        await mark_job_succeeded(
            session,
            job,
            response_payload=response,
            message=f"Etapa {step} concluida.",
        )
        await _emit_step_event(
            session,
            job,
            step=step,
            status="succeeded",
            message=f"Etapa {step} concluida.",
            details=response,
        )
        return response
