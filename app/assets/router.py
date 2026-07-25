from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.schemas import AssetCreate, AssetRead
from app.assets.service import create_asset
from app.database.session import get_session

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def post_asset(
    payload: AssetCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetRead:
    asset = await create_asset(session, payload)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return AssetRead.model_validate(asset)
