"""Router para a etapa de finalização: concatenação e download do vídeo final."""

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.projects.repository import ProjectRepository
from app.storage.service import resolve_storage_path
from app.video_generation.finalization import (
    concatenate_videos,
    delete_final_video,
    get_final_video_asset,
    get_finalization_status,
)

router = APIRouter(prefix="/video-finalization", tags=["video-finalization"])
logger = logging.getLogger(__name__)


@router.get("/{project_id}/status")
async def get_status(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Retorna o status da finalização do projeto."""
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")
    
    return await get_finalization_status(session, project_id)


@router.post("/{project_id}/finalize")
async def finalize_video(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Concatena todos os vídeos em um único vídeo final."""
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")
    
    try:
        asset = await concatenate_videos(session, project_id)
        await session.commit()
        
        return {
            "success": True,
            "message": "Vídeo final criado com sucesso",
            "asset_id": str(asset.id),
            "storage_uri": asset.storage_uri,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("video_finalization_failed project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao finalizar vídeo.",
        ) from exc


@router.get("/{project_id}/download")
async def download_final_video(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Baixa o vídeo final."""
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")
    
    asset = await get_final_video_asset(session, project_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vídeo final não encontrado. Finalize primeiro.",
        )
    
    storage_uri = getattr(asset, "storage_uri", None)
    if not storage_uri:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo de vídeo não encontrado",
        )
    
    file_path = resolve_storage_path(storage_uri)
    if file_path is None or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo de vídeo não encontrado no disco",
        )
    
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=f"video_final_{project_id}.mp4",
    )


@router.delete("/{project_id}/finalize")
async def delete_final(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Deleta o vídeo final (para regenerar)."""
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")
    
    deleted = await delete_final_video(session, project_id)
    await session.commit()
    
    return {
        "success": True,
        "message": "Vídeo final deletado" if deleted else "Nenhum vídeo final para deletar",
    }
