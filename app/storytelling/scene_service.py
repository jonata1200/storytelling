"""Scene and shot plan persistence derived from a generated script."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.projects.versioning import mark_dependents_stale
from app.storytelling.artifacts import (
    _add_dependency,
    _advance_project_status_when_reachable,
    _create_artifact,
)
from app.storytelling.models import Scene, Script, ScriptVersion, Shot
from app.storytelling.normalization import (
    GenerationOutputError,
    _bounded_required_str,
    _bounded_str_or_empty,
    _required_int,
    _required_list,
    _required_mapping,
    _required_str,
    _shot_narration_text,
    normalize_scene_plan_payload_from_script,
    scene_plan_payload_from_script_content,
)
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    VIDEO_CLIP_TARGET_SECONDS,
    format_clip_durations,
    video_clip_durations,
)


async def _ensure_script_video_package_duration(session: AsyncSession, script: Script) -> int:
    target_duration_seconds = max(VIDEO_CLIP_MIN_SECONDS, int(script.target_duration_seconds))
    remainder = target_duration_seconds % VIDEO_CLIP_TARGET_SECONDS
    if remainder:
        target_duration_seconds += VIDEO_CLIP_TARGET_SECONDS - remainder
    if target_duration_seconds != script.target_duration_seconds:
        script.target_duration_seconds = target_duration_seconds
        await session.flush()
    return target_duration_seconds


async def _script_embedded_production_plan(session: AsyncSession, script: Script) -> dict | None:
    result = await session.execute(
        select(ScriptVersion)
        .where(ScriptVersion.script_id == script.id)
        .order_by(ScriptVersion.version_number.desc())
    )
    version = result.scalars().first()
    if version is None:
        return None
    payload = version.payload if isinstance(version.payload, dict) else {}
    production_plan = payload.get("production_plan")
    return production_plan if isinstance(production_plan, dict) else None


async def generate_scenes_and_shots(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> list[Scene] | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None

    target_duration_seconds = await _ensure_script_video_package_duration(session, script)
    clip_durations = video_clip_durations(target_duration_seconds)
    embedded_plan = await _script_embedded_production_plan(session, script)

    scenes: list[Scene] = []
    if embedded_plan is not None:
        try:
            content = normalize_scene_plan_payload_from_script(
                embedded_plan,
                target_duration_seconds,
                script.content,
            )
        except GenerationOutputError:
            embedded_plan = None
    if embedded_plan is None:
        local_plan = scene_plan_payload_from_script_content(
            script.content,
            target_duration_seconds,
        )
        if local_plan is not None:
            content = local_plan
        else:
            provider, model = await llm_provider_for_task(
                session, project_id, "generate_scenes_and_shots"
            )
            result, _execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "generate_scenes_and_shots",
                {
                    "script": script.content,
                    "target_duration_seconds": target_duration_seconds,
                    "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
                    "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
                    "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
                    "expected_clip_count": len(clip_durations),
                    "clip_durations": format_clip_durations(clip_durations),
                },
                model=model,
                fallback_on_runtime_error=True,
            )
            content = normalize_scene_plan_payload_from_script(
                _required_mapping(result.content, "generate_scenes_and_shots"),
                target_duration_seconds,
                script.content,
            )
    for scene_index, raw_scene_payload in enumerate(
        _required_list(content, "scenes", "generate_scenes_and_shots"), 1
    ):
        scene_payload = _required_mapping(
            raw_scene_payload, f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_title = _required_str(
            scene_payload, "title", f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.SCENE,
            scene_title,
            scene_payload,
        )
        await _add_dependency(session, script.artifact_id, scene_artifact.id)
        scene = Scene(
            project_id=project_id,
            artifact_id=scene_artifact.id,
            script_id=script.id,
            scene_number=_required_int(
                scene_payload, "scene_number", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            title=scene_title,
            summary=_required_str(
                scene_payload, "summary", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            duration_seconds=_required_int(
                scene_payload,
                "duration_seconds",
                f"generate_scenes_and_shots.scenes[{scene_index}]",
            ),
            payload=scene_payload,
        )
        session.add(scene)
        await session.flush()
        for shot_index, raw_shot_payload in enumerate(
            _required_list(
                scene_payload, "shots", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            1,
        ):
            shot_context = f"generate_scenes_and_shots.scenes[{scene_index}].shots[{shot_index}]"
            shot_payload = _required_mapping(raw_shot_payload, shot_context)
            shot_artifact = await _create_artifact(
                session,
                project_id,
                ArtifactType.SHOT,
                f"{scene.title} - Plano {_required_int(shot_payload, 'shot_number', shot_context)}",
                shot_payload,
            )
            await _add_dependency(session, scene_artifact.id, shot_artifact.id)
            session.add(
                Shot(
                    project_id=project_id,
                    artifact_id=shot_artifact.id,
                    scene_id=scene.id,
                    shot_number=_required_int(shot_payload, "shot_number", shot_context),
                    duration_seconds=_required_int(shot_payload, "duration_seconds", shot_context),
                    narration_text=_shot_narration_text(shot_payload, shot_context),
                    dialogue_text=str(shot_payload.get("dialogue_text") or ""),
                    action=_required_str(shot_payload, "action", shot_context),
                    emotion=_bounded_required_str(shot_payload, "emotion", shot_context, 120),
                    visual_composition=_required_str(
                        shot_payload, "visual_composition", shot_context
                    ),
                    camera_movement=_bounded_str_or_empty(
                        shot_payload, "camera_movement", shot_context, 120
                    ),
                    generation_type=_bounded_required_str(
                        shot_payload, "generation_type", shot_context, 80
                    ),
                    payload=shot_payload,
                )
            )
        scenes.append(scene)
    _advance_project_status_when_reachable(project, ProjectStatus.VISUAL_BIBLE_GENERATION)
    await session.commit()
    for scene in scenes:
        await session.refresh(scene)
    return scenes


async def _mark_existing_scene_plan_stale(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> None:
    scene_result = await session.execute(
        select(Scene).where(Scene.project_id == project_id, Scene.script_id == script_id)
    )
    existing_scenes = list(scene_result.scalars())
    if not existing_scenes:
        return

    shot_result = await session.execute(
        select(Shot)
        .join(Scene, Shot.scene_id == Scene.id)
        .where(Shot.project_id == project_id, Scene.script_id == script_id)
    )
    existing_shots = list(shot_result.scalars())
    stale_artifact_ids = {scene.artifact_id for scene in existing_scenes}
    stale_artifact_ids.update(shot.artifact_id for shot in existing_shots)
    if not stale_artifact_ids:
        return

    await mark_dependents_stale(session, stale_artifact_ids)
    artifact_result = await session.execute(
        select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.id.in_(stale_artifact_ids),
        )
    )
    for artifact in artifact_result.scalars():
        artifact.status = ArtifactStatus.STALE
    await session.flush()


async def mark_scene_plan_stale(session: AsyncSession, project_id: UUID, script_id: UUID) -> None:
    await _mark_existing_scene_plan_stale(session, project_id, script_id)


async def regenerate_scenes_and_shots(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> list[Scene] | None:
    await _mark_existing_scene_plan_stale(session, project_id, script_id)
    return await generate_scenes_and_shots(session, project_id, script_id)
