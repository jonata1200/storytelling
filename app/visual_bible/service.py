from decimal import Decimal
from time import perf_counter
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import record_approval
from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import (
    ApprovalDecision,
    ArtifactStatus,
    ArtifactType,
    AssetKind,
)
from app.generation.models import PromptExecution
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact, ArtifactVersion
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.providers.image.types import ImageGenerationRequest
from app.storytelling.models import Script, StoryIdea
from app.visual_bible.artifacts import _add_dependency, _create_artifact
from app.visual_bible.image_generation import (
    _generate_image_with_provider_fallback,
    _image_provider_for_project,
)
from app.visual_bible.image_generation import (
    _transient_image_provider_error as _transient_image_provider_error,
)
from app.visual_bible.models import (
    Character,
    CharacterVersion,
    Location,
    LocationVersion,
    Prop,
    PropVersion,
    VisualReference,
)
from app.visual_bible.profiles import (
    _character_profile,
    _fingerprint,
    _location_profile,
    _merge_profile_items,
    _payload_section,
    _profile_items,
    _prop_profile,
    _raise_visual_profile_errors,
    _repair_missing_character_names,
    _script_character_names,
    _script_character_profiles,
    _script_location_profiles,
    _script_prop_profiles,
    _story_idea_protagonist_name,
)
from app.visual_bible.profiles import (
    visual_profile_validation_errors as visual_profile_validation_errors,
)
from app.visual_bible.prompts import (
    default_views_for,
    validated_visual_reference_views,
    visual_reference_aspect_ratio,
    visual_reference_prompt,
)
from app.visual_bible.prompts import initial_view_for as initial_view_for
from app.visual_bible.reference_status import (
    _existing_visual_reference_views,
)
from app.visual_bible.reference_status import (
    _visual_generation_reference_uris as _visual_generation_reference_uris,
)
from app.visual_bible.reference_status import (
    visual_reference_completion_message as visual_reference_completion_message,  # noqa: F401
)
from app.visual_bible.reference_status import (
    visual_reference_completion_report as visual_reference_completion_report,  # noqa: F401
)
from app.visual_bible.schemas import ConsistencyIssue
from app.visual_bible.upsert import (
    _match_visual_target as _match_visual_target,
)
from app.visual_bible.upsert import (
    _upsert_character_profile,
    _upsert_location_profile,
    _upsert_prop_profile,
)


class VisualReferenceCompletionReport(TypedDict):
    complete: bool
    counts: dict[str, int]
    missing_categories: list[str]
    expected_references: int
    existing_references: int
    missing_views: int














async def _generate_visual_bible_payload_with_llm(
    session: AsyncSession,
    project_id: UUID,
    latest_script: Script,
    source_payload: dict,
) -> dict:
    try:
        provider, model = await llm_provider_for_task(session, project_id, "generate_visual_bible")
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "generate_visual_bible",
            {
                "script": latest_script.content,
                "idea": source_payload,
            },
            artifact_id=latest_script.artifact_id,
            model=model,
            fallback_on_runtime_error=True,
        )
    except Exception:
        return {}
    return result.content if isinstance(result.content, dict) else {}


async def generate_visual_bible(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> tuple[list[Character], list[Location], list[Prop]] | None:
    project = await ProjectRepository(session).get_project(project_id)
    latest_script = await session.get(Script, script_id)
    if project is None or latest_script is None or latest_script.project_id != project_id:
        return None

    script_content = latest_script.content
    story_idea = await session.get(StoryIdea, latest_script.story_idea_id)
    source_payload = story_idea.payload if story_idea is not None else {}
    llm_payload = await _generate_visual_bible_payload_with_llm(
        session,
        project_id,
        latest_script,
        source_payload,
    )
    protagonist_hint = _story_idea_protagonist_name(
        story_idea.protagonist if story_idea is not None else ""
    )

    characters: list[Character] = []
    llm_character_items = _profile_items(
        _payload_section(
            llm_payload,
            ("characters", "personagens", "cast", "personas"),
        )
    )
    character_items = _profile_items(
        _payload_section(
            source_payload,
            ("characters", "personagens", "cast", "personas"),
        )
    )
    character_items = _merge_profile_items("character", llm_character_items, character_items)
    if not character_items:
        fallback_name = protagonist_hint or (
            _script_character_names(script_content)[0]
            if _script_character_names(script_content)
            else "Protagonista"
        )
        character_items = [
            {
                "name": fallback_name,
                "role": "protagonista",
                "desire": source_payload.get("protagonist_desire")
                or source_payload.get("stakes")
                or "cumprir a promessa emocional da historia",
                "arc": source_payload.get("emotional_need")
                or source_payload.get("resolution")
                or "transformacao emocional visivel",
            }
        ]
    character_items = _repair_missing_character_names(
        character_items, script_content, protagonist_hint
    )
    if script_content:
        character_items = _merge_profile_items(
            "character",
            character_items,
            _script_character_profiles(script_content),
        )
    character_profiles = [_character_profile(raw) for raw in character_items]
    _raise_visual_profile_errors("character", character_profiles)
    existing_character_result = await session.execute(
        select(Character).where(Character.project_id == project_id)
    )
    existing_characters = list(existing_character_result.scalars())
    for profile in character_profiles:
        characters.append(
            await _upsert_character_profile(
                session,
                project_id,
                latest_script.artifact_id,
                profile,
                existing_characters,
            )
        )

    locations: list[Location] = []
    llm_location_items = _profile_items(
        _payload_section(
            llm_payload,
            ("locations", "locais", "lugares", "settings", "places", "cenarios", "cenários"),
        )
    )
    location_items = _profile_items(
        _payload_section(
            source_payload,
            ("locations", "locais", "lugares", "settings", "places", "cenarios", "cenários"),
        )
    )
    location_items = _merge_profile_items("location", llm_location_items, location_items)
    if script_content:
        location_items = _merge_profile_items(
            "location", location_items, _script_location_profiles(script_content)
        )
    location_profiles = [_location_profile(raw) for raw in location_items]
    _raise_visual_profile_errors("location", location_profiles)
    existing_location_result = await session.execute(
        select(Location).where(Location.project_id == project_id)
    )
    existing_locations = list(existing_location_result.scalars())
    for profile in location_profiles:
        locations.append(
            await _upsert_location_profile(
                session,
                project_id,
                latest_script.artifact_id,
                profile,
                existing_locations,
            )
        )

    props: list[Prop] = []
    llm_prop_items = _profile_items(
        _payload_section(
            llm_payload,
            (
                "props",
                "objetos",
                "objects",
                "items",
                "itens",
                "objetos_narrativos",
                "narrative_props",
            ),
        )
    )
    prop_items = _profile_items(
        _payload_section(
            source_payload,
            (
                "props",
                "objetos",
                "objects",
                "items",
                "itens",
                "objetos_narrativos",
                "narrative_props",
            ),
        )
    )
    prop_items = _merge_profile_items("prop", llm_prop_items, prop_items)
    if script_content:
        prop_items = _merge_profile_items("prop", prop_items, _script_prop_profiles(script_content))
    prop_profiles = [_prop_profile(raw) for raw in prop_items]
    _raise_visual_profile_errors("prop", prop_profiles)
    existing_prop_result = await session.execute(select(Prop).where(Prop.project_id == project_id))
    existing_props = list(existing_prop_result.scalars())
    for profile in prop_profiles:
        props.append(
            await _upsert_prop_profile(
                session,
                project_id,
                latest_script.artifact_id,
                profile,
                existing_props,
            )
        )

    await session.commit()
    for item in [*characters, *locations, *props]:
        await session.refresh(item)
    return characters, locations, props


async def _get_visual_target(
    session: AsyncSession, project_id: UUID, target_kind: str, target_id: UUID
) -> tuple[dict, UUID] | None:
    target: Character | Location | Prop | None
    if target_kind == "character":
        target = await session.get(Character, target_id)
    elif target_kind == "location":
        target = await session.get(Location, target_id)
    elif target_kind == "prop":
        target = await session.get(Prop, target_id)
    else:
        return None
    if target is None or target.project_id != project_id:
        return None
    return target.canonical_profile, target.artifact_id


async def update_visual_target_prompt(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    canonical_prompt: str,
    change_note: str | None = None,
) -> Character | Location | Prop | None:
    prompt = canonical_prompt.strip()
    if not prompt:
        raise ValueError("O prompt não pode ficar vazio")

    target: Character | Location | Prop | None
    if target_kind == "character":
        target = await session.get(Character, target_id)
    elif target_kind == "location":
        target = await session.get(Location, target_id)
    elif target_kind == "prop":
        target = await session.get(Prop, target_id)
    else:
        return None
    if target is None or target.project_id != project_id:
        return None

    profile = dict(target.canonical_profile or {})
    if profile.get("canonical_prompt") == prompt:
        return target
    profile["canonical_prompt"] = prompt
    target.canonical_profile = profile
    target.current_version += 1

    if isinstance(target, Character):
        target.character_fingerprint = _fingerprint(profile)
        session.add(
            CharacterVersion(
                character_id=target.id,
                version_number=target.current_version,
                canonical_profile=profile,
                change_note=change_note or "Canonical prompt edited",
            )
        )
    elif isinstance(target, Location):
        session.add(
            LocationVersion(
                location_id=target.id,
                version_number=target.current_version,
                canonical_profile=profile,
                change_note=change_note or "Canonical prompt edited",
            )
        )
    else:
        session.add(
            PropVersion(
                prop_id=target.id,
                version_number=target.current_version,
                canonical_profile=profile,
                change_note=change_note or "Canonical prompt edited",
            )
        )

    artifact = await session.get(Artifact, target.artifact_id)
    if artifact is not None:
        artifact.status = ArtifactStatus.READY_FOR_REVIEW
        await create_artifact_version(
            session,
            artifact,
            profile,
            change_note=change_note or "Canonical visual prompt edited",
        )

    await session.commit()
    await session.refresh(target)
    return target










async def approve_visual_target_and_generate_views(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_types: list[str] | None = None,
) -> list[VisualReference] | None:
    project = await ProjectRepository(session).get_project(project_id)
    target = await _get_visual_target(session, project_id, target_kind, target_id)
    if project is None or target is None:
        return None

    _profile, target_artifact_id = target
    artifact = await session.get(Artifact, target_artifact_id)
    if artifact is None:
        return None
    version_result = await session.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.version_number == artifact.current_version,
        )
        .limit(1)
    )
    artifact_version = version_result.scalars().first()
    if artifact_version is None:
        return None

    await record_approval(
        session,
        artifact,
        artifact_version,
        ApprovalDecision.APPROVED,
        notes="Perfil visual aprovado para criacao de vistas multiplas.",
    )
    existing_views = await _existing_visual_reference_views(
        session, project_id, target_kind, target_id
    )
    requested_views = validated_visual_reference_views(target_kind, view_types)
    missing_views = [view for view in requested_views if view not in existing_views]
    if not missing_views:
        await session.commit()
        return []
    return await generate_visual_references(
        session,
        project_id,
        target_kind,
        target_id,
        missing_views,
    )


async def generate_visual_references(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_types: list[str] | None = None,
    force: bool = False,
) -> list[VisualReference] | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    target = await _get_visual_target(session, project_id, target_kind, target_id)
    if target is None:
        return None
    profile, target_artifact_id = target
    production_settings = await get_or_create_production_settings(session, project_id)
    provider, image_model, image_dir_name = await _image_provider_for_project(session, project_id)
    image_resolution = production_settings.image_resolution
    requested_views = validated_visual_reference_views(target_kind, view_types)
    if force:
        views = requested_views
    else:
        existing_views = await _existing_visual_reference_views(
            session, project_id, target_kind, target_id
        )
        views = [view for view in requested_views if view not in existing_views]
    if not views:
        return []
    references: list[VisualReference] = []
    output_dir = get_settings().local_storage_path / image_dir_name / str(project_id)

    for view_type in views:
        prompt = visual_reference_prompt(profile, view_type)
        aspect_ratio = visual_reference_aspect_ratio(profile, view_type)
        reference_uris = await _visual_generation_reference_uris(
            session,
            project_id,
            target_kind,
            target_id,
            profile,
            view_type,
        )
        generation_started_at = perf_counter()
        image_result, fallback_metadata = await _generate_image_with_provider_fallback(
            provider,
            ImageGenerationRequest(
                prompt=prompt,
                target_id=str(target_id),
                view_type=view_type,
                output_dir=output_dir,
                aspect_ratio=aspect_ratio,
                resolution=image_resolution,
                references=reference_uris,
                model=image_model,
            ),
        )
        duration_ms = max(1, int((perf_counter() - generation_started_at) * 1000))
        generation_metadata = {
            "reference_uris": reference_uris,
            "resolution": image_resolution,
            "duration_ms": duration_ms,
            **fallback_metadata,
        }
        asset = Asset(
            project_id=project_id,
            artifact_id=target_artifact_id,
            kind=AssetKind.IMAGE,
            name=f"{profile.get('name', target_kind)} - {view_type}",
            storage_uri=image_result.storage_uri,
            content_type=image_result.content_type,
            sha256=image_result.sha256,
            metadata_json={
                "provider": image_result.provider,
                "model": image_result.model,
                "aspect_ratio": aspect_ratio,
                **generation_metadata,
            },
        )
        session.add(asset)
        await session.flush()
        session.add(
            AssetVersion(
                asset_id=asset.id,
                version_number=1,
                storage_uri=asset.storage_uri,
                sha256=asset.sha256,
                metadata_json=asset.metadata_json,
            )
        )
        reference_payload = {
            "target_kind": target_kind,
            "target_id": str(target_id),
            "view_type": view_type,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "asset_id": str(asset.id),
        }
        artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.VISUAL_REFERENCE,
            f"{profile.get('name', target_kind)} - {view_type}",
            reference_payload,
        )
        await _add_dependency(session, target_artifact_id, artifact.id)
        execution = PromptExecution(
            project_id=project_id,
            artifact_id=artifact.id,
            prompt_template_id=None,
            template_version=None,
            provider=image_result.provider,
            model=image_result.model,
            prompt=prompt,
            variables={"target_kind": target_kind, "target_id": str(target_id), "view": view_type},
            response={"asset_id": str(asset.id), "storage_uri": asset.storage_uri},
            parameters=generation_metadata,
            estimated_cost=Decimal(image_result.estimated_cost),
            duration_ms=duration_ms,
        )
        session.add(execution)
        reference = VisualReference(
            project_id=project_id,
            artifact_id=artifact.id,
            asset_id=asset.id,
            target_kind=target_kind,
            target_id=target_id,
            view_type=view_type,
            prompt=prompt,
            provider=image_result.provider,
            model=image_result.model,
            metadata_json={
                "sha256": image_result.sha256,
                "aspect_ratio": aspect_ratio,
                **generation_metadata,
            },
        )
        session.add(reference)
        references.append(reference)

    await session.flush()
    reference_ids = [reference.id for reference in references]
    await session.commit()
    result = await session.execute(
        select(VisualReference).where(VisualReference.id.in_(reference_ids))
    )
    references_by_id = {reference.id: reference for reference in result.scalars()}
    reloaded_references = [
        references_by_id[reference_id]
        for reference_id in reference_ids
        if reference_id in references_by_id
    ]
    return reloaded_references if len(reloaded_references) == len(references) else references


async def regenerate_visual_reference(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    view_type: str,
) -> VisualReference | None:
    references = await generate_visual_references(
        session,
        project_id,
        target_kind,
        target_id,
        [view_type],
        force=True,
    )
    if references is None:
        return None
    return references[0] if references else None


async def check_visual_consistency(
    session: AsyncSession, project_id: UUID, target_kind: str, target_id: UUID
) -> list[ConsistencyIssue] | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    target = await _get_visual_target(session, project_id, target_kind, target_id)
    if target is None:
        return None

    expected = set(default_views_for(target_kind))
    result = await session.execute(
        select(VisualReference.view_type).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target_kind,
            VisualReference.target_id == target_id,
        )
    )
    existing = set(result.scalars())
    missing = sorted(expected - existing)
    issues = [
        ConsistencyIssue(
            code="missing_visual_reference",
            message=f"Referência visual ausente: {view_type}",
            severity="warning",
        )
        for view_type in missing
    ]
    return issues
