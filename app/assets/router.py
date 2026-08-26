from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.assets.schemas import AssetCreate, AssetRead
from app.assets.service import create_asset
from app.database.session import get_session
from app.storage.service import resolve_local_asset_path

router = APIRouter(prefix="/assets", tags=["assets"])


def _local_asset_path(storage_uri: str) -> Path:
    path = resolve_local_asset_path(storage_uri)
    if path is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found")
    return path


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def post_asset(
    payload: AssetCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetRead:
    asset = await create_asset(session, payload)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return AssetRead.model_validate(asset)


@router.get("/{asset_id}/content", include_in_schema=False)
async def get_asset_content(
    asset_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    path = _local_asset_path(asset.storage_uri)
    return FileResponse(
        path,
        media_type=asset.content_type or "application/octet-stream",
        filename=path.name,
    )
