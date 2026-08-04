from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import ArtifactType, AssetKind, CostEntryType, ProjectStatus
from app.costs.models import CostEntry
from app.costs.service import cost_audit_metadata, estimate_operation_cost, final_budget_cost
from app.generation.models import PromptExecution
from app.production.service import (
    get_or_create_production_settings,
    normalize_image_aspect_ratio,
    normalize_image_resolution,
)
from app.projects.models import Artifact, ArtifactVersion
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.storage.service import apply_asset_storage_metadata
from app.storyboards.animatic import (
    _animatic_fingerprint as _animatic_fingerprint,
)
from app.storyboards.animatic import (
    generate_animatic_bundle as generate_animatic_bundle,  # noqa: F401
)
from app.storyboards.assets import (
    _delete_local_storage_file,
    _storyboard_frame_asset_available,
)
from app.storyboards.assets import (
    _local_storage_file_exists as _local_storage_file_exists,
)
from app.storyboards.assets import (
    _local_storage_file_path as _local_storage_file_path,
)
from app.storyboards.frame_generation import (
    StoryboardFrameGenerationPlan,
    generate_storyboard_plan_images,
    storyboard_image_concurrency,
)
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline, TimelineItem
from app.storyboards.prompt_approvals import (
    _ensure_storyboard_prompts_approved,
)
from app.storyboards.prompt_approvals import (
    approve_storyboard_prompt as approve_storyboard_prompt,  # noqa: F401
)
from app.storyboards.prompt_approvals import (
    approve_storyboard_prompts as approve_storyboard_prompts,  # noqa: F401
)
from app.storyboards.prompt_approvals import (
    list_storyboard_prompt_previews as list_storyboard_prompt_previews,  # noqa: F401
)
from app.storyboards.prompt_approvals import (
    storyboard_prompts_need_approval as storyboard_prompts_need_approval,  # noqa: F401
)
from app.storyboards.prompt_approvals import (
    update_storyboard_prompt as update_storyboard_prompt,  # noqa: F401
)
from app.storyboards.prompts import (
    _prompt_hash,
    _storyboard_effective_prompt,
    _storyboard_frame_payload,
    _storyboard_prompt,
    _storyboard_prompt_is_approved,
    _storyboard_visual_context,
)
from app.storyboards.queries import (
    list_storyboard_frames,
    storyboard_coverage_errors,
)
from app.storyboards.workflow import (
    _add_dependency,
    _create_artifact,
    _image_provider_for_project,
    _selected_storyboard_shots,
)
from app.storyboards.workflow import (
    _ordered_shots_for_script as _ordered_shots_for_script,
)
from app.storytelling.models import Scene, Script, Shot
from app.video_generation.models import ClipReview, GenerationJob, VideoClip
from app.visual_bible.service import (
    visual_reference_completion_message,
    visual_reference_completion_report,
)
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import advance_project_status


async def generate_storyboard_frames(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    scene_number: int | None = None,
    shot_id: UUID | None = None,
    force: bool = False,
    approved_only: bool = False,
) -> list[StoryboardFrame] | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None

    visual_report = await visual_reference_completion_report(session, project_id)
    if not visual_report["complete"]:
        raise ValueError(visual_reference_completion_message(visual_report))

    all_shot_rows, shot_rows, frame_number_by_shot = await _selected_storyboard_shots(
        session,
        project_id,
        script_id,
        scene_number=scene_number,
        shot_id=shot_id,
    )

    production_settings = await get_or_create_production_settings(session, project_id)
    image_aspect_ratio = normalize_image_aspect_ratio(production_settings.aspect_ratio)
    image_resolution = normalize_image_resolution(
        production_settings.image_resolution,
        image_aspect_ratio,
    )
    visual_context = await _storyboard_visual_context(session, project_id)
    if approved_only:
        metadata = production_settings.metadata_json or {}
        approved_shot_rows: list[tuple[Shot, Scene]] = []
        prompt_by_shot: dict[UUID, str] = {}
        for shot, scene in shot_rows:
            default_prompt = _storyboard_prompt(shot, scene, visual_context)
            prompt = _storyboard_effective_prompt(
                metadata,
                script_id,
                shot.id,
                default_prompt,
            )
            if not _storyboard_prompt_is_approved(
                metadata,
                script_id,
                shot.id,
                _prompt_hash(prompt),
            ):
                continue
            approved_shot_rows.append((shot, scene))
            prompt_by_shot[shot.id] = prompt
        shot_rows = approved_shot_rows
        if not shot_rows:
            return []
    else:
        prompt_by_shot = await _ensure_storyboard_prompts_approved(
            session,
            project_id,
            script_id,
            shot_rows,
            visual_context,
        )
    provider, image_model, image_dir_name = await _image_provider_for_project(session, project_id)
    app_settings = get_settings()
    output_dir = app_settings.local_storage_path / image_dir_name / str(project_id)
    existing_frames = await list_storyboard_frames(session, project_id, script_id)
    existing_by_shot = {frame.shot_id: frame for frame in existing_frames}
    frame_plans: list[StoryboardFrameGenerationPlan] = []
    for shot, scene in shot_rows:
        frame_number = frame_number_by_shot[shot.id]
        prompt = prompt_by_shot[shot.id]
        existing_frame = existing_by_shot.get(shot.id)
        existing_prompt_hash = (
            (existing_frame.metadata_json or {}).get("prompt_hash")
            if existing_frame is not None
            else None
        )
        existing_asset_available = await _storyboard_frame_asset_available(session, existing_frame)
        needs_image = (
            force
            or existing_frame is None
            or existing_prompt_hash != _prompt_hash(prompt)
            or not existing_asset_available
        )
        asset_artifact_id = (
            existing_frame.artifact_id if existing_frame is not None else shot.artifact_id
        )
        frame_plans.append(
            StoryboardFrameGenerationPlan(
                shot=shot,
                scene=scene,
                frame_number=frame_number,
                prompt=prompt,
                existing_frame=existing_frame,
                needs_image=needs_image,
                asset_artifact_id=asset_artifact_id,
            )
        )

    await generate_storyboard_plan_images(
        provider,
        frame_plans,
        output_dir=output_dir,
        image_resolution=image_resolution,
        image_aspect_ratio=image_aspect_ratio,
        image_model=image_model,
        concurrency=storyboard_image_concurrency(
            getattr(app_settings, "storyboard_image_concurrency", None)
        ),
    )

    frames: list[StoryboardFrame] = []
    for plan in frame_plans:
        shot = plan.shot
        scene = plan.scene
        frame_number = plan.frame_number
        prompt = plan.prompt
        existing_frame = plan.existing_frame
        needs_image = plan.needs_image
        if needs_image:
            image = plan.image
            if image is None:
                raise RuntimeError("A geração do storyboard não retornou imagem.")
            duration_ms = plan.duration_ms or 1
            generation_metadata = {
                "resolution": image_resolution,
                "aspect_ratio": image_aspect_ratio,
                "duration_ms": duration_ms,
                **(plan.fallback_metadata or {}),
            }
            asset = Asset(
                project_id=project_id,
                artifact_id=plan.asset_artifact_id,
                kind=AssetKind.IMAGE,
                name=f"Storyboard frame {frame_number:03d}",
                storage_uri=image.storage_uri,
                content_type=image.content_type,
                sha256=image.sha256,
                metadata_json={
                    "provider": image.provider,
                    "model": image.model,
                    **generation_metadata,
                },
            )
            apply_asset_storage_metadata(asset)
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
            asset_id = asset.id
        else:
            assert existing_frame is not None
            image = None
            asset = None
            asset_id = existing_frame.asset_id
            duration_ms = None
            generation_metadata = {"reused": True}

        payload = _storyboard_frame_payload(scene, shot, asset_id, prompt)
        if existing_frame is not None:
            previous_fingerprint = (existing_frame.metadata_json or {}).get("frame_fingerprint")
            existing_frame.frame_number = frame_number
            existing_frame.duration_seconds = shot.duration_seconds
            existing_frame.prompt = prompt
            existing_frame.narration_text = shot.narration_text
            existing_frame.dialogue_text = shot.dialogue_text
            existing_frame.metadata_json = payload
            metadata_changed = previous_fingerprint != payload["frame_fingerprint"]
            if needs_image:
                existing_frame.asset_id = asset_id
                artifact = await session.get(Artifact, existing_frame.artifact_id)
                if artifact is not None:
                    artifact.name = f"Storyboard {scene.scene_number}.{shot.shot_number}"
                    await create_artifact_version(
                        session,
                        artifact,
                        payload,
                        change_note="Storyboard frame regenerated after prompt change",
                    )
                session.add(
                    PromptExecution(
                        project_id=project_id,
                        artifact_id=existing_frame.artifact_id,
                        prompt_template_id=None,
                        template_version=None,
                        provider=image.provider if image is not None else "reused",
                        model=image.model if image is not None else image_model,
                        prompt=prompt,
                        variables={"shot_id": str(shot.id), "scene_id": str(scene.id)},
                        response={
                            "asset_id": str(asset_id),
                            "storage_uri": asset.storage_uri if asset is not None else "",
                        },
                        parameters={"reused": False, **generation_metadata},
                        estimated_cost=(
                            Decimal(image.estimated_cost)
                            if image is not None
                            else Decimal("0.000000")
                        ),
                        duration_ms=duration_ms,
                    )
                )
                if image is not None:
                    cost_estimate = estimate_operation_cost(
                        "image_generation",
                        Decimal("1"),
                        provider=image.provider,
                        model=image.model,
                    )
                    provider_cost = Decimal(str(image.estimated_cost or "0.000000"))
                    budget_cost = final_budget_cost(cost_estimate.estimated, provider_cost)
                    session.add(
                        CostEntry(
                            project_id=project_id,
                            artifact_id=existing_frame.artifact_id,
                            entry_type=CostEntryType.ESTIMATE,
                            provider=image.provider,
                            model=image.model,
                            operation="image_generation",
                            quantity=cost_estimate.quantity,
                            unit=cost_estimate.unit,
                            unit_cost=cost_estimate.unit_cost,
                            total_cost=budget_cost,
                            currency=cost_estimate.currency,
                            metadata_json=cost_audit_metadata(
                                estimated_cost=cost_estimate.estimated,
                                provider_reported_cost=provider_cost,
                                final_budget_cost=budget_cost,
                                stage="storyboard",
                                extra={"asset_id": str(asset_id), "shot_id": str(shot.id)},
                            ),
                        )
                    )
            elif metadata_changed:
                artifact = await session.get(Artifact, existing_frame.artifact_id)
                if artifact is not None:
                    artifact.name = f"Storyboard {scene.scene_number}.{shot.shot_number}"
                    await create_artifact_version(
                        session,
                        artifact,
                        payload,
                        change_note="Storyboard frame metadata updated",
                    )
            else:
                artifact = await session.get(Artifact, existing_frame.artifact_id)
                if artifact is not None and artifact.name != (
                    f"Storyboard {scene.scene_number}.{shot.shot_number}"
                ):
                    artifact.name = f"Storyboard {scene.scene_number}.{shot.shot_number}"
            await _add_dependency(session, shot.artifact_id, existing_frame.artifact_id)
            frame = existing_frame
        else:
            artifact = await _create_artifact(
                session,
                project_id,
                ArtifactType.STORYBOARD,
                f"Storyboard {scene.scene_number}.{shot.shot_number}",
                payload,
            )
            await _add_dependency(session, shot.artifact_id, artifact.id)
            session.add(
                PromptExecution(
                    project_id=project_id,
                    artifact_id=artifact.id,
                    prompt_template_id=None,
                    template_version=None,
                    provider=image.provider if image is not None else "reused",
                    model=image.model if image is not None else image_model,
                    prompt=prompt,
                    variables={"shot_id": str(shot.id), "scene_id": str(scene.id)},
                    response={
                        "asset_id": str(asset_id),
                        "storage_uri": asset.storage_uri if asset is not None else "",
                    },
                    parameters={"reused": False, **generation_metadata},
                    estimated_cost=(
                        Decimal(image.estimated_cost) if image is not None else Decimal("0.000000")
                    ),
                    duration_ms=duration_ms,
                )
            )
            if image is not None:
                cost_estimate = estimate_operation_cost(
                    "image_generation",
                    Decimal("1"),
                    provider=image.provider,
                    model=image.model,
                )
                provider_cost = Decimal(str(image.estimated_cost or "0.000000"))
                budget_cost = final_budget_cost(cost_estimate.estimated, provider_cost)
                session.add(
                    CostEntry(
                        project_id=project_id,
                        artifact_id=artifact.id,
                        entry_type=CostEntryType.ESTIMATE,
                        provider=image.provider,
                        model=image.model,
                        operation="image_generation",
                        quantity=cost_estimate.quantity,
                        unit=cost_estimate.unit,
                        unit_cost=cost_estimate.unit_cost,
                        total_cost=budget_cost,
                        currency=cost_estimate.currency,
                        metadata_json=cost_audit_metadata(
                            estimated_cost=cost_estimate.estimated,
                            provider_reported_cost=provider_cost,
                            final_budget_cost=budget_cost,
                            stage="storyboard",
                            extra={"asset_id": str(asset_id), "shot_id": str(shot.id)},
                        ),
                    )
                )
            frame = StoryboardFrame(
                project_id=project_id,
                artifact_id=artifact.id,
                shot_id=shot.id,
                asset_id=asset_id,
                frame_number=frame_number,
                duration_seconds=shot.duration_seconds,
                prompt=prompt,
                narration_text=shot.narration_text,
                dialogue_text=shot.dialogue_text,
                metadata_json=payload,
            )
            session.add(frame)
        frames.append(frame)

    errors = storyboard_coverage_errors(shot_rows, frames)
    if errors:
        raise ValueError("Storyboard incompleto: " + "; ".join(errors))
    full_scope_generation = scene_number is None and shot_id is None and not approved_only
    if full_scope_generation:
        advance_project_status(project, ProjectStatus.STORYBOARD_APPROVAL)
    else:
        full_frames = await list_storyboard_frames(session, project_id, script_id)
        full_frame_by_shot = {frame.shot_id: frame for frame in full_frames}
        for frame in frames:
            full_frame_by_shot[frame.shot_id] = frame
        if not storyboard_coverage_errors(all_shot_rows, list(full_frame_by_shot.values())):
            advance_project_status(project, ProjectStatus.STORYBOARD_APPROVAL)
    await session.commit()
    for frame in frames:
        await session.refresh(frame)
    return frames


async def storyboard_frames_need_generation(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
) -> bool:
    shot_rows = await _ordered_shots_for_script(session, project_id, script_id)
    if not shot_rows:
        return True
    existing_frames = await list_storyboard_frames(session, project_id, script_id)
    if len(existing_frames) != len(shot_rows):
        return True
    existing_by_shot = {frame.shot_id: frame for frame in existing_frames}
    visual_context = await _storyboard_visual_context(session, project_id)
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    for shot, scene in shot_rows:
        frame = existing_by_shot.get(shot.id)
        if frame is None:
            return True
        default_prompt = _storyboard_prompt(shot, scene, visual_context)
        prompt = _storyboard_effective_prompt(
            metadata,
            script_id,
            shot.id,
            default_prompt,
        )
        existing_prompt_hash = (frame.metadata_json or {}).get("prompt_hash")
        if existing_prompt_hash != _prompt_hash(prompt):
            return True
        if not await _storyboard_frame_asset_available(session, frame):
            return True
    return False


async def delete_storyboard_outputs(session: AsyncSession, project_id: UUID) -> dict[str, int]:
    frame_rows = await session.execute(
        select(StoryboardFrame.id, StoryboardFrame.artifact_id, StoryboardFrame.asset_id).where(
            StoryboardFrame.project_id == project_id
        )
    )
    frame_data = list(frame_rows.all())
    frame_ids = [row[0] for row in frame_data]
    storyboard_artifact_ids = [row[1] for row in frame_data]
    asset_ids = {row[2] for row in frame_data if row[2] is not None}

    if frame_ids:
        clip_rows = await session.execute(
            select(
                VideoClip.id,
                VideoClip.artifact_id,
                VideoClip.asset_id,
                VideoClip.generation_job_id,
            )
            .where(VideoClip.project_id == project_id)
            .where(VideoClip.storyboard_frame_id.in_(frame_ids))
        )
        clip_data = list(clip_rows.all())
    else:
        clip_data = []
    clip_ids = [row[0] for row in clip_data]
    video_artifact_ids = [row[1] for row in clip_data]
    asset_ids.update(row[2] for row in clip_data if row[2] is not None)
    generation_job_ids = [row[3] for row in clip_data if row[3] is not None]

    animatic_rows = await session.execute(
        select(Animatic.id, Animatic.artifact_id, Animatic.audio_track_id).where(
            Animatic.project_id == project_id
        )
    )
    animatic_data = list(animatic_rows.all())
    animatic_ids = [row[0] for row in animatic_data]
    animatic_artifact_ids = [row[1] for row in animatic_data]
    audio_track_ids = [row[2] for row in animatic_data if row[2] is not None]

    if animatic_ids:
        timeline_rows = await session.execute(
            select(Timeline.id, Timeline.artifact_id)
            .where(Timeline.project_id == project_id)
            .where(Timeline.animatic_id.in_(animatic_ids))
        )
        timeline_data = list(timeline_rows.all())
    else:
        timeline_data = []
    timeline_ids = [row[0] for row in timeline_data]
    timeline_artifact_ids = [row[1] for row in timeline_data]

    if audio_track_ids:
        audio_rows = await session.execute(
            select(AudioTrack.artifact_id).where(AudioTrack.id.in_(audio_track_ids))
        )
        audio_artifact_ids = [row[0] for row in audio_rows.all()]
    else:
        audio_artifact_ids = []

    artifact_ids = set(
        storyboard_artifact_ids
        + video_artifact_ids
        + animatic_artifact_ids
        + timeline_artifact_ids
        + audio_artifact_ids
    )

    if artifact_ids:
        asset_rows = await session.execute(
            select(Asset.id).where(
                Asset.project_id == project_id,
                Asset.artifact_id.in_(artifact_ids),
            )
        )
        asset_ids.update(row[0] for row in asset_rows.all())
    asset_storage_uris: list[str] = []
    if asset_ids:
        storage_rows = await session.execute(
            select(Asset.storage_uri).where(
                Asset.project_id == project_id,
                Asset.id.in_(asset_ids),
            )
        )
        asset_storage_uris = [str(row[0] or "") for row in storage_rows.all()]

    if clip_ids:
        await session.execute(delete(ClipReview).where(ClipReview.video_clip_id.in_(clip_ids)))
        await session.execute(delete(VideoClip).where(VideoClip.id.in_(clip_ids)))
    if timeline_ids:
        await session.execute(
            delete(TimelineItem).where(TimelineItem.timeline_id.in_(timeline_ids))
        )
        await session.execute(delete(Timeline).where(Timeline.id.in_(timeline_ids)))
    if animatic_ids:
        await session.execute(delete(Animatic).where(Animatic.id.in_(animatic_ids)))
    if audio_track_ids:
        await session.execute(delete(AudioTrack).where(AudioTrack.id.in_(audio_track_ids)))
    if frame_ids:
        await session.execute(delete(StoryboardFrame).where(StoryboardFrame.id.in_(frame_ids)))
    if generation_job_ids:
        await session.execute(delete(GenerationJob).where(GenerationJob.id.in_(generation_job_ids)))
    if asset_ids:
        await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(asset_ids)))
        await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    if artifact_ids:
        await session.execute(
            delete(PromptExecution).where(PromptExecution.artifact_id.in_(artifact_ids))
        )
        await session.execute(
            delete(ArtifactDependency).where(
                (ArtifactDependency.upstream_artifact_id.in_(artifact_ids))
                | (ArtifactDependency.downstream_artifact_id.in_(artifact_ids))
            )
        )
        await session.execute(
            delete(ArtifactVersion).where(ArtifactVersion.artifact_id.in_(artifact_ids))
        )
        await session.execute(delete(Artifact).where(Artifact.id.in_(artifact_ids)))
    deleted_files = sum(
        1 for storage_uri in asset_storage_uris if _delete_local_storage_file(storage_uri)
    )
    await session.commit()
    return {
        "frames": len(frame_ids),
        "clips": len(clip_ids),
        "animatics": len(animatic_ids),
        "timelines": len(timeline_ids),
        "assets": len(asset_ids),
        "artifacts": len(artifact_ids),
        "files": deleted_files,
    }
