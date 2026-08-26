"""Text-only character and location profile service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.storytelling.models import Script, StoryIdea
from app.visual_bible.models import Character, Location
from app.visual_bible.profiles import (
    _character_profile,
    _location_profile,
    _looks_like_non_character_name,
    _raise_visual_profile_errors,
    _repair_missing_character_names,
    _script_character_names,
    _semantic_deduplicate_locations,
    _story_idea_protagonist_name,
)
from app.visual_bible.script_profiles import _llm_extract_characters_and_locations
from app.visual_bible.upsert import _upsert_character_profile, _upsert_location_profile


def _fallback_character_item(
    protagonist_hint: str, script_content: str, source_payload: dict
) -> dict | None:
    names = [protagonist_hint, *_script_character_names(script_content)]
    fallback_name = next(
        (name for name in names if name and not _looks_like_non_character_name(name)), ""
    )
    if not fallback_name:
        return None
    return {
        "name": fallback_name,
        "role": "protagonista",
        "desire": source_payload.get("protagonist_desire") or "cumprir seu objetivo",
        "arc": source_payload.get("emotional_need") or "transformação emocional visível",
    }


async def generate_visual_bible(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> tuple[list[Character], list[Location]] | None:
    """Create text-only canonical profiles; no image assets are generated."""
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None
    story_idea = await session.get(StoryIdea, script.story_idea_id)
    source_payload = story_idea.payload if story_idea is not None else {}
    protagonist_hint = _story_idea_protagonist_name(
        story_idea.protagonist if story_idea is not None else ""
    )
    character_items, location_items = await _llm_extract_characters_and_locations(
        session, project_id, script.content
    )
    if not character_items:
        fallback = _fallback_character_item(protagonist_hint, script.content, source_payload)
        character_items = [fallback] if fallback else []
    character_items = _repair_missing_character_names(
        character_items, script.content, protagonist_hint
    )
    character_items = [
        item
        for item in character_items
        if not _looks_like_non_character_name(str(item.get("name") or ""))
    ]
    character_profiles = [_character_profile(item) for item in character_items]
    location_profiles = [
        _location_profile(item) for item in _semantic_deduplicate_locations(location_items)
    ]
    _raise_visual_profile_errors("character", character_profiles)
    _raise_visual_profile_errors("location", location_profiles)

    existing_characters = list(
        (
            await session.execute(select(Character).where(Character.project_id == project_id))
        ).scalars()
    )
    existing_locations = list(
        (
            await session.execute(select(Location).where(Location.project_id == project_id))
        ).scalars()
    )
    characters = [
        await _upsert_character_profile(
            session, project_id, script.artifact_id, profile, existing_characters
        )
        for profile in character_profiles
    ]
    locations = [
        await _upsert_location_profile(
            session, project_id, script.artifact_id, profile, existing_locations
        )
        for profile in location_profiles
    ]
    await _delete_obsolete_profiles(
        session,
        characters,
        locations,
        existing_characters,
        existing_locations,
    )
    await session.commit()
    for item in [*characters, *locations]:
        await session.refresh(item)
    return characters, locations


async def _delete_obsolete_profiles(
    session: AsyncSession,
    characters: list[Character],
    locations: list[Location],
    existing_characters: list[Character],
    existing_locations: list[Location],
) -> None:
    active_character_ids = {item.id for item in characters}
    active_location_ids = {item.id for item in locations}
    for character in existing_characters:
        if character.id not in active_character_ids:
            artifact = await session.get(Artifact, character.artifact_id)
            if artifact is not None:
                await session.delete(artifact)
            await session.delete(character)
    for location in existing_locations:
        if location.id not in active_location_ids:
            artifact = await session.get(Artifact, location.artifact_id)
            if artifact is not None:
                await session.delete(artifact)
            await session.delete(location)


async def _get_visual_target(
    session: AsyncSession, project_id: UUID, target_kind: str, target_id: UUID
) -> tuple[dict, UUID] | None:
    target: Character | Location | None
    if target_kind == "character":
        target = await session.get(Character, target_id)
    elif target_kind == "location":
        target = await session.get(Location, target_id)
    else:
        return None
    if target is None or target.project_id != project_id:
        return None
    return dict(target.canonical_profile or {}), target.artifact_id
