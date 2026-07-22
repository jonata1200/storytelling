from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from app.assets.models import Asset
from app.config.settings import get_settings
from app.visual_bible.models import VisualReference
from app.visual_bible.service import default_views_for


def visual_reference_views_for(
    summary: dict[str, Any], target_kind: str, target_id: UUID
) -> set[str]:
    return {
        reference.view_type
        for reference in summary["visual_refs"]
        if reference.target_kind == target_kind and reference.target_id == target_id
    }


def visual_references_for(
    summary: dict[str, Any], target_kind: str, target_id: UUID
) -> list[VisualReference]:
    view_order = {view: index for index, view in enumerate(default_views_for(target_kind))}
    references = [
        reference
        for reference in summary["visual_refs"]
        if reference.target_kind == target_kind and reference.target_id == target_id
    ]
    return sorted(
        references,
        key=lambda reference: (
            view_order.get(reference.view_type, len(view_order)),
            -reference.created_at.timestamp(),
        ),
    )


def asset_url(storage_uri: str, storage_root: Path | None = None) -> str:
    if not storage_uri:
        return ""
    storage_root = (storage_root or get_settings().local_storage_path).resolve()
    candidate = Path(storage_uri)
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(storage_root)
    except ValueError:
        return ""
    return "/storage/" + "/".join(quote(part) for part in relative.parts)


def visual_reference_asset(
    asset_map: dict[UUID, Asset], reference: VisualReference
) -> Asset | None:
    return asset_map.get(reference.asset_id)


def clean_profile_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def visual_card_detail(target_kind: str, profile: dict, fallback: str = "") -> str:
    explicit = clean_profile_text(
        profile.get("description")
        or profile.get("summary")
        or profile.get("visual_description")
        or profile.get("mood")
    )
    if explicit:
        return explicit

    if target_kind == "character":
        parts = [
            clean_profile_text(profile.get("apparent_age")),
            clean_profile_text(profile.get("eyes")),
            clean_profile_text(profile.get("hair")),
            clean_profile_text(profile.get("base_outfit")),
        ]
        text = ", ".join(part for part in parts if part)
        return text or fallback or "Perfil visual pronto para revisar e gerar imagens."

    if target_kind == "location":
        parts = [
            clean_profile_text(profile.get("lighting")),
            clean_profile_text(profile.get("materials")),
            clean_profile_text(profile.get("layout")),
        ]
        text = ", ".join(part for part in parts if part)
        return text or fallback or "Cenario pronto para revisar e gerar referências."

    parts = [
        clean_profile_text(profile.get("narrative_importance")),
        clean_profile_text(profile.get("material")),
        clean_profile_text(profile.get("color")),
        clean_profile_text(profile.get("state")),
    ]
    text = ", ".join(part for part in parts if part)
    return text or fallback or "Objeto pronto para revisar e gerar referências."
