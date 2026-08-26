from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.generation.shot_generation_spec import ShotGenerationSpec
from app.providers.media_utils import local_uri_to_data_url
from app.storytelling.models import Scene, Shot
from app.video_generation.models import ContinuousVideoSegment
from app.visual_bible.models import Character, Location, VisualReference

CHARACTER_STATE_KEYS = (
    "outfit",
    "hair_state",
    "injuries",
    "carried_props",
    "emotional_state",
    "position",
    "condition",
    "time_of_day",
    "continuity_notes",
)


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


async def build_shot_generation_spec(
    session: AsyncSession,
    project_id: UUID,
    shot_id: UUID,
) -> ShotGenerationSpec:
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise ValueError("Shot não encontrado no projeto")
    scene = await session.get(Scene, shot.scene_id)
    if scene is None:
        raise ValueError("Scene obrigatória do Shot não foi encontrada")
    payload = dict(shot.payload or {})
    character_names = _names(payload.get("characters"))
    location_name = str(payload.get("location") or "").strip() or None
    props = _names(payload.get("props"))
    continuity = dict(payload.get("continuity") or {})
    continuity.setdefault("spatial_orientation", payload.get("spatial_continuity") or "")
    continuity.setdefault("continuity_break", bool(payload.get("continuity_break")))
    raw_states = payload.get("character_states")
    states: dict[str, dict[str, Any]] = {}
    if isinstance(raw_states, dict):
        for name, raw_state in raw_states.items():
            if not isinstance(raw_state, dict):
                continue
            states[str(name)] = {
                key: raw_state[key]
                for key in CHARACTER_STATE_KEYS
                if raw_state.get(key) is not None
            }

    targets: list[tuple[str, UUID]] = []
    if character_names:
        result = await session.execute(select(Character).where(Character.project_id == project_id))
        wanted = {name.casefold() for name in character_names}
        targets.extend(
            ("character", item.id)
            for item in result.scalars().all()
            if item.name.casefold() in wanted
        )
    if location_name:
        result = await session.execute(select(Location).where(Location.project_id == project_id))
        targets.extend(
            ("location", item.id)
            for item in result.scalars().all()
            if item.name.casefold() == location_name.casefold()
        )

    references: list[str] = []
    ingredient_ids: list[str] = []
    if targets:
        target_ids = [target_id for _kind, target_id in targets]
        reference_result = await session.execute(
            select(VisualReference)
            .where(
                VisualReference.project_id == project_id,
                VisualReference.target_id.in_(target_ids),
                VisualReference.status == "approved",
            )
            .order_by(VisualReference.is_canonical.desc(), VisualReference.created_at.desc())
        )
        for reference in reference_result.scalars().all():
            asset = await session.get(Asset, reference.asset_id)
            data_url = local_uri_to_data_url(asset.storage_uri) if asset else None
            if data_url and data_url not in references:
                references.append(data_url)
            vibes = dict((reference.metadata_json or {}).get("vibes") or {})
            ingredient_id = str(vibes.get("ingredient_id") or "").strip()
            if vibes.get("sync_status") == "synced" and ingredient_id:
                ingredient_ids.append(ingredient_id)

    previous_frame: str | None = None
    if not continuity["continuity_break"]:
        segment_result = await session.execute(
            select(ContinuousVideoSegment)
            .where(
                ContinuousVideoSegment.project_id == project_id,
                ContinuousVideoSegment.shot_id.is_not(None),
                ContinuousVideoSegment.final_frame_asset_id.is_not(None),
            )
            .order_by(ContinuousVideoSegment.segment_number)
        )
        candidates = segment_result.scalars().all()
        current_number = _segment_number(shot, candidates)
        previous = next(
            (item for item in reversed(candidates) if item.segment_number < current_number),
            None,
        )
        if previous and previous.final_frame_asset_id:
            asset = await session.get(Asset, previous.final_frame_asset_id)
            previous_frame = local_uri_to_data_url(asset.storage_uri) if asset else None

    warnings: list[str] = []
    if targets and not references:
        warnings.append("Shot possui entidades sem referência visual aprovada")
    if not character_names:
        warnings.append("Shot sem personagem; geração será orientada pela ação e pelo local")
    return ShotGenerationSpec(
        shot_id=shot.id,
        scene_id=scene.id,
        scene_title=scene.title,
        scene_summary=scene.summary,
        scene_context=str(payload.get("scene_context") or scene.summary),
        continuity_state=str(payload.get("continuity_state") or ""),
        duration_seconds=float(shot.duration_seconds),
        characters=character_names,
        location=location_name,
        props=props,
        action=shot.action,
        emotion=shot.emotion,
        camera=shot.camera_movement,
        camera_movement=shot.camera_movement,
        visual_composition=shot.visual_composition,
        lighting=str(payload.get("lighting") or ""),
        character_states=states,
        continuity=continuity,
        visual_references=references,
        ingredient_ids=ingredient_ids,
        previous_frame_reference=previous_frame,
        warnings=warnings,
    )


def _segment_number(shot: Shot, segments: Sequence[ContinuousVideoSegment]) -> int:
    current = next((item for item in segments if item.shot_id == shot.id), None)
    return int(current.segment_number) if current else 2**31 - 1
