"""Text-only character and location profile service."""

import json
import logging
import re
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.storytelling.models import Briefing, Script, StoryIdea
from app.visual_bible.manual_references import (
    load_visual_exclusions,
)
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
from app.visual_bible.script_profiles import (
    _llm_extract_characters_and_locations,
)
from app.visual_bible.upsert import _upsert_character_profile, _upsert_location_profile
from app.workflows.models import ArtifactDependency

logger = logging.getLogger(__name__)


async def _filter_excluded_items(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    items: list[dict],
) -> list[dict]:
    """Remove da extração os perfis excluídos manualmente (tombstones).

    As exclusões vivem nas production settings e sobrevivem à regeneração: um
    card excluído pelo usuário não volta em "Criar Bíblia Visual". A chave do
    item é derivada do `permanent_id` (sha1 determinístico do nome — ver
    `_character_profile`/`_location_profile`) com fallback por nome
    normalizado, cobrindo variações de caixa/acentuação entre extrações.
    """
    from app.visual_bible.profiles import _visual_key

    exclusions = await load_visual_exclusions(session, project_id)
    excluded_keys: set[str] = set()
    for entry in exclusions:
        excluded_keys.add(str(entry.get("key") or ""))
        excluded_keys.update(str(alt) for alt in entry.get("alt_keys") or [])
    excluded_keys.discard("")
    if not excluded_keys:
        return items

    def _item_keys(item: dict) -> set[str]:
        name = str(item.get("name") or "").strip()
        permanent_id = str(item.get("permanent_id") or item.get("id") or "").strip()
        keys = set()
        if permanent_id:
            keys.add(f"{target_kind}:{_visual_key(permanent_id)}")
        if name:
            keys.add(f"{target_kind}:{_visual_key(name)}")
        return keys

    filtered = [item for item in items if not (_item_keys(item) & excluded_keys)]
    dropped = len(items) - len(filtered)
    if dropped:
        logger.info(
            "visual_bible_excluded_profiles target_kind=%s dropped=%d", target_kind, dropped
        )
    return filtered


def _visual_story_context(
    story_idea: StoryIdea | None,
    briefing: Briefing | None = None,
) -> str:
    """Return compact canonical context used to ground location extraction."""
    if story_idea is None and briefing is None:
        return ""
    payload = dict(story_idea.payload or {}) if story_idea is not None else {}
    context = {
        "title": getattr(story_idea, "title", None),
        "hook": getattr(story_idea, "hook", None),
        "premise": getattr(story_idea, "premise", None),
        "genre": payload.get("genre") or getattr(briefing, "genre", None),
        "tone": payload.get("tone"),
        "time_period": payload.get("time_period") or payload.get("epoca"),
        "country_context": payload.get("country_context")
        or payload.get("pais")
        or getattr(briefing, "country_context", None),
        "visual_style": payload.get("visual_style") or getattr(briefing, "visual_style", None),
        "primary_emotion": payload.get("primary_emotion")
        or getattr(briefing, "primary_emotion", None),
        "locations": payload.get("locations")
        or payload.get("locais")
        or payload.get("cenarios")
        or payload.get("cenários"),
        "props": payload.get("props") or payload.get("objetos"),
        "constraints": payload.get("constraints") or payload.get("forbidden_elements"),
    }
    compact = {key: value for key, value in context.items() if value not in (None, "", [], {})}
    return json.dumps(compact, ensure_ascii=False, default=str)


def _apply_script_gender_evidence(character_items: list[dict], script_content: str) -> list[dict]:
    """Prefer explicit screenplay evidence over guessed visual gender."""
    for item in character_items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        introduction = re.search(
            rf"\b{re.escape(name)}\b[^.\n]{{0,100}}\b(um homem|uma mulher)\b",
            script_content,
            flags=re.IGNORECASE,
        )
        if introduction is None:
            continue
        evidence = introduction.group(0).strip()
        item["gender"] = (
            "masculino" if introduction.group(1).casefold() == "um homem" else "feminino"
        )
        existing_evidence = item.get("evidence_text")
        evidence_items = list(existing_evidence) if isinstance(existing_evidence, list) else []
        item["evidence_text"] = list(dict.fromkeys([*evidence_items, evidence]))
    return character_items


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
    briefing = (
        await session.execute(
            select(Briefing)
            .where(Briefing.project_id == project_id)
            .order_by(Briefing.created_at.desc())
        )
    ).scalars().first()
    source_payload = story_idea.payload if story_idea is not None else {}
    protagonist_hint = _story_idea_protagonist_name(
        story_idea.protagonist if story_idea is not None else ""
    )
    character_items, location_items = await _llm_extract_characters_and_locations(
        session,
        project_id,
        script.content,
        story_context=_visual_story_context(story_idea, briefing),
    )
    character_items = await _filter_excluded_items(
        session, project_id, "character", character_items
    )
    location_items = await _filter_excluded_items(
        session, project_id, "location", location_items
    )
    if not character_items:
        fallback = _fallback_character_item(protagonist_hint, script.content, source_payload)
        character_items = [fallback] if fallback else []
    character_items = _repair_missing_character_names(
        character_items, script.content, protagonist_hint
    )
    character_items = _apply_script_gender_evidence(character_items, script.content)
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
        (await session.execute(select(Location).where(Location.project_id == project_id))).scalars()
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
                await _delete_artifact_with_dependencies(session, artifact.id)
                await session.delete(artifact)
            await session.delete(character)
    for location in existing_locations:
        if location.id not in active_location_ids:
            artifact = await session.get(Artifact, location.artifact_id)
            if artifact is not None:
                await _delete_artifact_with_dependencies(session, artifact.id)
                await session.delete(artifact)
            await session.delete(location)


async def _delete_artifact_with_dependencies(session: AsyncSession, artifact_id: UUID) -> None:
    """Remove edges de dependência em ambas as pontas antes de deletar o artifact.

    Perfis visuais participam do grafo como upstream (artefatos derivados
    deles, ex.: referências visuais) e como downstream (ex.: dependency do
    script). Deletar o artifact sem limpar as edges viola a FK de
    artifact_dependencies e derruba a regeneração dos perfis.
    """
    await session.execute(
        delete(ArtifactDependency).where(
            or_(
                ArtifactDependency.upstream_artifact_id == artifact_id,
                ArtifactDependency.downstream_artifact_id == artifact_id,
            )
        )
    )


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
