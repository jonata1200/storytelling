from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.storytelling.models import Shot
from app.visual_bible.image_generation import (
    generate_visual_reference,
    set_visual_reference_status,
)
from app.visual_bible.models import VisualReference
from app.visual_bible.reference_planning import (
    VisualReferencePlan,
    plan_visual_references,
)
from app.visual_bible.schemas import (
    GenerateVisualReferencesRequest,
    RegenerateVisualReferenceRequest,
    VisualReferenceDecisionRequest,
    VisualReferenceRead,
)
from app.visual_bible.service import _get_visual_target

router = APIRouter(prefix="/visual-bible/projects", tags=["visual-bible"])


@router.post("/{project_id}/references/plan", response_model=VisualReferencePlan)
async def post_reference_plan(
    project_id: UUID,
    payload: GenerateVisualReferencesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualReferencePlan:
    target = await _get_visual_target(session, project_id, payload.target_kind, payload.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Entidade visual não encontrada")
    profile, _artifact_id = target
    shots_result = await session.execute(select(Shot.payload).where(Shot.project_id == project_id))
    return plan_visual_references(
        payload.target_kind,
        payload.target_id,
        profile,
        shot_payloads=[dict(row[0] or {}) for row in shots_result.all()],
    )


@router.post(
    "/{project_id}/references/generate",
    response_model=list[VisualReferenceRead],
)
async def post_generate_references(
    project_id: UUID,
    payload: GenerateVisualReferencesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VisualReferenceRead]:
    target = await _get_visual_target(session, project_id, payload.target_kind, payload.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Entidade visual não encontrada")
    profile, _artifact_id = target
    planned = plan_visual_references(payload.target_kind, payload.target_id, profile)
    wanted = set(payload.view_types or [item.view_type for item in planned.items])
    items_by_view = {item.view_type: item for item in planned.items}
    generated: list[VisualReference] = []
    try:
        for view_type in wanted:
            item = items_by_view.get(view_type)
            generated.append(
                await generate_visual_reference(
                    session,
                    project_id,
                    payload.target_kind,
                    payload.target_id,
                    view_type,
                    prompt_override=item.prompt if item else view_type,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [VisualReferenceRead.model_validate(item) for item in generated]


@router.post(
    "/{project_id}/references/{reference_id}/regenerate",
    response_model=VisualReferenceRead,
)
async def post_regenerate_reference(
    project_id: UUID,
    reference_id: UUID,
    payload: RegenerateVisualReferenceRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualReferenceRead:
    original = await session.get(VisualReference, reference_id)
    if original is None or original.project_id != project_id:
        raise HTTPException(status_code=404, detail="Referência visual não encontrada")
    try:
        regenerated = await generate_visual_reference(
            session,
            project_id,
            original.target_kind,
            original.target_id,
            original.view_type,
            prompt_override=payload.prompt or original.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return VisualReferenceRead.model_validate(regenerated)


@router.post(
    "/{project_id}/references/{reference_id}/approve",
    response_model=VisualReferenceRead,
)
async def post_approve_reference(
    project_id: UUID,
    reference_id: UUID,
    payload: VisualReferenceDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualReferenceRead:
    try:
        reference = await set_visual_reference_status(
            session, project_id, reference_id, "approved", canonical=payload.canonical
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VisualReferenceRead.model_validate(reference)


@router.post(
    "/{project_id}/references/{reference_id}/reject",
    response_model=VisualReferenceRead,
)
async def post_reject_reference(
    project_id: UUID,
    reference_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualReferenceRead:
    try:
        reference = await set_visual_reference_status(session, project_id, reference_id, "rejected")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VisualReferenceRead.model_validate(reference)


@router.get("/{project_id}/references", response_model=list[VisualReferenceRead])
async def get_references(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VisualReferenceRead]:
    result = await session.execute(
        select(VisualReference)
        .where(VisualReference.project_id == project_id)
        .order_by(VisualReference.created_at.desc())
    )
    return [VisualReferenceRead.model_validate(item) for item in result.scalars()]
