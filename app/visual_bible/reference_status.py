from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.prompts import default_views_for_profile


async def _existing_visual_reference_views(
    session: AsyncSession, project_id: UUID, target_kind: str, target_id: UUID
) -> set[str]:
    result = await session.execute(
        select(VisualReference.view_type).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
        )
    )
    return set(result.scalars())


async def _visual_generation_reference_uris(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    profile: dict,
    view_type: str,
) -> list[str]:
    if target_kind != "character":
        return []

    identity_base = str(profile.get("identity_base_name") or "").strip().casefold()
    if not identity_base:
        return []

    reference_uris: list[str] = []
    seen_uris: set[str] = set()

    async def append_reference_uri(reference: VisualReference) -> None:
        if reference.asset_id is None:
            return
        asset = await session.get(Asset, reference.asset_id)
        storage_uri = str(getattr(asset, "storage_uri", "") or "").strip()
        if storage_uri and storage_uri not in seen_uris:
            seen_uris.add(storage_uri)
            reference_uris.append(storage_uri)

    if view_type == "character_reference_sheet":
        current_result = await session.execute(
            select(VisualReference)
            .where(
                VisualReference.project_id == project_id,
                VisualReference.target_kind == target_kind,
                VisualReference.target_id == target_id,
                VisualReference.view_type == "front_portrait",
            )
            .order_by(VisualReference.created_at.desc())
            .limit(1)
        )
        current_reference = current_result.scalars().first()
        if current_reference is not None:
            await append_reference_uri(current_reference)

    characters_result = await session.execute(
        select(Character).where(
            Character.project_id == project_id,
            Character.id != target_id,
        )
    )
    related_character_ids = [
        character.id
        for character in characters_result.scalars()
        if str((character.canonical_profile or {}).get("identity_base_name") or "")
        .strip()
        .casefold()
        == identity_base
    ]
    if related_character_ids:
        related_refs_result = await session.execute(
            select(VisualReference)
            .where(
                VisualReference.project_id == project_id,
                VisualReference.target_kind == target_kind,
                VisualReference.target_id.in_(related_character_ids),
            )
            .order_by(VisualReference.created_at.desc())
        )
        related_references = sorted(
            related_refs_result.scalars(),
            key=lambda reference: (
                0 if reference.view_type == "front_portrait" else 1,
                -reference.created_at.timestamp(),
            ),
        )
        for reference in related_references:
            await append_reference_uri(reference)
            if len(reference_uris) >= 2:
                break

    return reference_uris[:2]


async def visual_reference_completion_report(
    session: AsyncSession, project_id: UUID
) -> dict[str, object]:
    target_specs = (
        ("character", "characters", "personagens", Character),
        ("location", "locations", "locais", Location),
        ("prop", "props", "objetos", Prop),
    )
    counts: dict[str, int] = {}
    missing_categories: list[str] = []
    expected_references = 0
    existing_references = 0
    missing_views = 0

    for target_kind, count_key, label, model in target_specs:
        result = await session.execute(select(model).where(model.project_id == project_id))
        targets = list(result.scalars())
        counts[count_key] = len(targets)
        if not targets:
            missing_categories.append(label)
            continue

        for target in targets:
            profile = getattr(target, "canonical_profile", {}) or {}
            expected_views = set(default_views_for_profile(target_kind, profile))
            expected_references += len(expected_views)
            existing_views = await _existing_visual_reference_views(
                session, project_id, target_kind, target.id
            )
            valid_existing_views = existing_views & expected_views
            existing_references += len(valid_existing_views)
            missing_views += len(expected_views - valid_existing_views)

    complete = not missing_categories and missing_views == 0
    return {
        "complete": complete,
        "counts": counts,
        "missing_categories": missing_categories,
        "expected_references": expected_references,
        "existing_references": existing_references,
        "missing_views": missing_views,
    }


def visual_reference_completion_message(report: Mapping[str, object]) -> str:
    raw_missing_categories = report.get("missing_categories", [])
    missing_categories = (
        [str(item) for item in raw_missing_categories if str(item).strip()]
        if isinstance(raw_missing_categories, list)
        else []
    )
    if missing_categories:
        return (
            "Conclua a Biblioteca Visual antes do storyboard. Ainda faltam: "
            f"{', '.join(missing_categories)}."
        )
    raw_missing_views = report.get("missing_views", 0)
    missing_views = raw_missing_views if isinstance(raw_missing_views, int) else 0
    if missing_views > 0:
        return (
            "Conclua a Biblioteca Visual antes do storyboard. "
            f"Ainda falta gerar {missing_views} referência(s) visual(is)."
        )
    return "Biblioteca Visual completa."
