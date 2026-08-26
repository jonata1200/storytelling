"""Leitura legada de clipes de vídeo.

A geração de vídeo por IA foi desativada: a etapa de pacote de vídeo agora
prede vídeo (ver ``app.video_generation.continuous``).
Este módulo mantém apenas a leitura dos clipes/jobs já gerados em projetos antigos.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.repository import ProjectRepository
from app.video_generation.models import GenerationJob, VideoClip

logger = logging.getLogger(__name__)


async def list_video_clips(session: AsyncSession, project_id: UUID) -> list[VideoClip]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return []
    result = await session.execute(
        select(VideoClip).where(VideoClip.project_id == project_id).order_by(VideoClip.created_at)
    )
    return list(result.scalars())


async def get_job_status(session: AsyncSession, job_id: UUID) -> GenerationJob | None:
    job = await session.get(GenerationJob, job_id)
    if job is None:
        return None
    project = await ProjectRepository(session).get_project(job.project_id)
    if project is None:
        return None
    return job
