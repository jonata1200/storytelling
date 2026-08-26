from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, DependencyKind
from app.projects.models import Artifact
from app.projects.versioning import create_artifact_version
from app.visual_bible.artifacts import _add_dependency, _create_artifact
from app.visual_bible.models import Character, Location
from app.visual_bible.profiles import (
    _fingerprint,
    _profile_sha256,
    _visual_key,
    _visual_profile_identity,
)
from app.workflows.models import ArtifactDependency


def _match_visual_target(
    existing: list[Character] | list[Location], profile: dict
) -> Character | Location | None:
    identity = _visual_profile_identity(profile)
    name_key = _visual_key(profile.get("name"))
    for item in existing:
        item_profile = item.canonical_profile or {}
        if identity and _visual_profile_identity(item_profile) == identity:
            return item
        if name_key and _visual_key(item.name) == name_key:
            return item
    return None


async def _restore_current_artifact_if_stale(session: AsyncSession, artifact_id: UUID) -> None:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is not None and artifact.status == ArtifactStatus.STALE:
        artifact.status = ArtifactStatus.READY_FOR_REVIEW
    reference_result = await session.execute(
        select(Artifact)
        .join(
            ArtifactDependency,
            ArtifactDependency.downstream_artifact_id == Artifact.id,
        )
        .where(
            ArtifactDependency.upstream_artifact_id == artifact_id,
            ArtifactDependency.dependency_kind == DependencyKind.DERIVED_FROM,
            Artifact.artifact_type == ArtifactType.VISUAL_REFERENCE,
            Artifact.status == ArtifactStatus.STALE,
        )
    )
    for reference_artifact in reference_result.scalars():
        reference_artifact.status = ArtifactStatus.READY_FOR_REVIEW


async def _upsert_character_profile(
    session: AsyncSession,
    project_id: UUID,
    source_artifact_id: UUID,
    profile: dict,
    existing_characters: list[Character],
) -> Character:
    existing = _match_visual_target(existing_characters, profile)
    if isinstance(existing, Character):
        if _profile_sha256(existing.canonical_profile or {}) != _profile_sha256(profile):
            existing = await session.get(Character, existing.id, with_for_update=True)
            if existing is None:
                raise ValueError("Character disappeared during upsert")
            existing.name = str(profile["name"])
            existing.role = str(profile["role"])
            existing.canonical_profile = profile
            existing.character_fingerprint = _fingerprint(profile)
            artifact = await session.get(Artifact, existing.artifact_id)
            if artifact is not None:
                artifact.name = existing.name
                await create_artifact_version(
                    session,
                    artifact,
                    profile,
                    change_note="Canonical character profile updated from script",
                )
        else:
            await _restore_current_artifact_if_stale(session, existing.artifact_id)
        await _add_dependency(session, source_artifact_id, existing.artifact_id)
        return existing

    artifact = await _create_artifact(
        session, project_id, ArtifactType.CHARACTER, profile["name"], profile
    )
    await _add_dependency(session, source_artifact_id, artifact.id)
    character = Character(
        project_id=project_id,
        artifact_id=artifact.id,
        name=profile["name"],
        role=profile["role"],
        canonical_profile=profile,
        character_fingerprint=_fingerprint(profile),
    )
    session.add(character)
    await session.flush()
    existing_characters.append(character)
    return character


async def _upsert_location_profile(
    session: AsyncSession,
    project_id: UUID,
    source_artifact_id: UUID,
    profile: dict,
    existing_locations: list[Location],
) -> Location:
    existing = _match_visual_target(existing_locations, profile)
    if isinstance(existing, Location):
        if _profile_sha256(existing.canonical_profile or {}) != _profile_sha256(profile):
            existing = await session.get(Location, existing.id, with_for_update=True)
            if existing is None:
                raise ValueError("Location disappeared during upsert")
            existing.name = str(profile["name"])
            existing.description = str(profile["description"])
            existing.canonical_profile = profile
            artifact = await session.get(Artifact, existing.artifact_id)
            if artifact is not None:
                artifact.name = existing.name
                await create_artifact_version(
                    session,
                    artifact,
                    profile,
                    change_note="Canonical location profile updated from script",
                )
        else:
            await _restore_current_artifact_if_stale(session, existing.artifact_id)
        await _add_dependency(session, source_artifact_id, existing.artifact_id)
        return existing

    artifact = await _create_artifact(
        session, project_id, ArtifactType.LOCATION, profile["name"], profile
    )
    await _add_dependency(session, source_artifact_id, artifact.id)
    location = Location(
        project_id=project_id,
        artifact_id=artifact.id,
        name=profile["name"],
        description=profile["description"],
        canonical_profile=profile,
    )
    session.add(location)
    await session.flush()
    existing_locations.append(location)
    return location
