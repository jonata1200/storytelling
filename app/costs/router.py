from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_basic_auth
from app.costs.schemas import (
    CostEntryCreate,
    CostEntryRead,
    CostEstimateRead,
    CostEstimateRequest,
)
from app.costs.service import create_cost_entry, estimate_batch_cost
from app.database.session import get_session

router = APIRouter(
    prefix="/costs",
    tags=["costs"],
    dependencies=[Depends(require_basic_auth)],
)


@router.post("/estimate", response_model=CostEstimateRead)
async def post_cost_estimate(payload: CostEstimateRequest) -> CostEstimateRead:
    return CostEstimateRead(
        **estimate_batch_cost(
            payload.generation_count,
            payload.average_units,
            payload.unit_cost,
            payload.uncertainty_ratio,
        )
    )


@router.post("", response_model=CostEntryRead, status_code=status.HTTP_201_CREATED)
async def post_cost_entry(
    payload: CostEntryCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CostEntryRead:
    entry = await create_cost_entry(session, payload)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return CostEntryRead.model_validate(entry)
