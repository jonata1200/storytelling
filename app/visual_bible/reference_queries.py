from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.visual_bible.models import VisualReference


async def approved_visual_references(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> list[tuple[VisualReference, Asset]]:
    result = await session.execute(
        select(VisualReference, Asset)
        .join(Asset, Asset.id == VisualReference.asset_id)
        .where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
            VisualReference.status == "approved",
        )
        .order_by(VisualReference.is_canonical.desc(), VisualReference.created_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def canonical_visual_reference(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
) -> tuple[VisualReference, Asset] | None:
    references = await approved_visual_references(
        session, project_id, target_kind, target_id
    )
    return next((item for item in references if item[0].is_canonical), None)
