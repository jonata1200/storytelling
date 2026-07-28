from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.costs.schemas import (
    BudgetCheckRead,
    BudgetCheckRequest,
    CostBudgetRead,
    CostBudgetUpdate,
    CostEntryCreate,
    CostEntryRead,
    CostEstimateRead,
    CostEstimateRequest,
    OperationCostEstimateRead,
    OperationCostEstimateRequest,
    OperationCostPolicyRead,
    ProjectCostSummaryRead,
)
from app.costs.service import (
    check_project_budget,
    create_cost_entry,
    estimate_batch_cost,
    estimate_operation_cost,
    get_project_cost_budget,
    operation_cost_policies,
    project_cost_summary,
    update_project_cost_budget,
)
from app.database.session import get_session

router = APIRouter(prefix="/costs", tags=["costs"])


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


@router.get("/policies", response_model=list[OperationCostPolicyRead])
async def get_cost_policies() -> list[OperationCostPolicyRead]:
    return operation_cost_policies()


@router.post("/operation-estimate", response_model=OperationCostEstimateRead)
async def post_operation_cost_estimate(
    payload: OperationCostEstimateRequest,
) -> OperationCostEstimateRead:
    try:
        return estimate_operation_cost(
            payload.operation,
            payload.quantity,
            payload.provider,
            payload.model,
            payload.uncertainty_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=CostEntryRead, status_code=status.HTTP_201_CREATED)
async def post_cost_entry(
    payload: CostEntryCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CostEntryRead:
    entry = await create_cost_entry(session, payload)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return CostEntryRead.model_validate(entry)


@router.get("/projects/{project_id}/budget", response_model=CostBudgetRead)
async def get_cost_budget(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CostBudgetRead:
    return await get_project_cost_budget(session, project_id)


@router.patch("/projects/{project_id}/budget", response_model=CostBudgetRead)
async def patch_cost_budget(
    project_id: UUID,
    payload: CostBudgetUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CostBudgetRead:
    budget = await update_project_cost_budget(session, project_id, payload)
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return budget


@router.post("/budget-check", response_model=BudgetCheckRead)
async def post_budget_check(
    payload: BudgetCheckRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BudgetCheckRead:
    return await check_project_budget(
        session,
        payload.project_id,
        payload.estimated_cost,
        payload.stage,
    )


@router.get("/projects/{project_id}/summary", response_model=ProjectCostSummaryRead)
async def get_project_cost_summary(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectCostSummaryRead:
    return await project_cost_summary(session, project_id)
