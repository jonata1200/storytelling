from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
)
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
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic
from app.storyboards.service import generate_animatic_bundle, generate_storyboard_frames
from app.storytelling.models import Script, StoryIdea
from app.storytelling.service import (
    create_story_idea_from_payload,
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
)
from app.video_generation.models import GenerationJob
from app.video_generation.service import generate_video_clips
from app.visual_bible.service import (
    generate_visual_bible,
    visual_reference_completion_message,
    visual_reference_completion_report,
)


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


async def _run_initial_script(
    session: AsyncSession,
    project_id: UUID,
    payload: dict,
) -> dict[str, Any]:
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
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    return {"script_id": str(script.id)}


async def _run_script(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            raise ValueError("não foi possível gerar uma ideia base")
        idea = ideas[0]
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        raise ValueError("não foi possível gerar roteiro")
    return {"script_id": str(script.id)}


async def _run_scenes(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    script = await _latest(session, Script, project_id)
    if script is None:
        raise ValueError("gere o roteiro primeiro")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("não foi possível gerar cenas e planos")
    return {"script_id": str(script.id), "scene_count": len(scenes)}


async def _run_visual(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    script = await _latest(session, Script, project_id)
    if script is None:
        raise ValueError("gere o roteiro primeiro")
    visual = await generate_visual_bible(session, project_id, script.id)
    if visual is None:
        raise ValueError("não foi possível criar a Biblioteca visual")
    characters, locations, props = visual
    return {
        "characters": len(characters),
        "locations": len(locations),
        "props": len(props),
    }


async def _run_storyboard(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    script = await _latest(session, Script, project_id)
    if script is None:
        raise ValueError("gere o roteiro primeiro")
    visual_report = await visual_reference_completion_report(session, project_id)
    if not visual_report["complete"]:
        raise ValueError(visual_reference_completion_message(visual_report))
    frames = await generate_storyboard_frames(session, project_id, script.id)
    if frames is None:
        raise ValueError("não foi possível gerar storyboard")
    animatic_bundle = await generate_animatic_bundle(session, project_id, script.id)
    animatic = animatic_bundle[0] if animatic_bundle is not None else None
    return {
        "frame_count": len(frames),
        "animatic_id": str(animatic.id) if animatic is not None else None,
    }


async def _run_video(
    session: AsyncSession,
    project_id: UUID,
    payload: dict,
) -> dict[str, Any]:
    raw_frame_ids = payload.get("frame_ids")
    frame_ids = (
        [UUID(str(item)) for item in raw_frame_ids]
        if isinstance(raw_frame_ids, list)
        else None
    )
    result = await generate_video_clips(session, project_id, frame_ids=frame_ids)
    if result is None:
        raise ValueError("não encontrei o projeto para gerar os clipes")
    jobs, clips = result
    return {"job_count": len(jobs), "clip_count": len(clips)}


async def _run_finalization(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    animatic = await _latest(session, Animatic, project_id)
    timeline = await create_final_timeline(session, project_id, animatic.id if animatic else None)
    if timeline is None:
        raise ValueError("gere clipes de video primeiro")
    export = await export_timeline(
        session,
        project_id,
        timeline.id,
    )
    return {
        "timeline_id": str(timeline.id),
        "export_id": str(export.id) if export is not None else None,
    }


async def _run_quality(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    check = await run_quality_check(session, project_id)
    return {"quality_check_id": str(check.id) if check is not None else None}


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
            message=f"Worker iniciou a etapa {step}.",
        )
        await _emit_step_event(
            session,
            job,
            step=step,
            status="started",
            message=f"Worker iniciou a etapa {step}.",
            details={"attempt": job.attempts},
        )
        try:
            await mark_job_progress(session, job, progress=20, message=f"Executando {step}.")
            if step == "initial_script":
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Criando roteiro inicial.",
                )
                response = await _run_initial_script(session, job.project_id, payload)
            elif step == "ideas":
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Criando ideias narrativas.",
                )
                ideas = await generate_story_ideas(session, job.project_id)
                response = {"idea_count": len(ideas or [])}
            elif step == "script":
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Escrevendo roteiro cinematográfico.",
                )
                response = await _run_script(session, job.project_id)
            elif step == "scenes":
                await mark_job_progress(
                    session,
                    job,
                    progress=35,
                    message="Separando roteiro em cenas e planos.",
                )
                response = await _run_scenes(session, job.project_id)
            elif step == "visual":
                response = await _run_visual(session, job.project_id)
            elif step == "storyboard":
                response = await _run_storyboard(session, job.project_id)
            elif step == "video":
                response = await _run_video(session, job.project_id, payload)
            elif step == "finalization":
                response = await _run_finalization(session, job.project_id)
            elif step == "quality":
                response = await _run_quality(session, job.project_id)
            else:
                raise ValueError(f"Etapa de job inválida: {step}")
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
        except Exception as exc:
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
