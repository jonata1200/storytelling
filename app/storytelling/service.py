from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.storytelling.artifacts import (
    _add_dependency,
    _advance_project_status_when_reachable,
    _create_artifact,
)
from app.storytelling.models import (
    Briefing,
    Scene,
    Script,
    ScriptVersion,
    Shot,
    StoryIdea,
)
from app.storytelling.normalization import (
    GenerationOutputError,
    _bounded_required_str,
    _idea_script_contract,
    _required_int,
    _required_list,
    _required_mapping,
    _required_str,
    _shot_narration_text,
    expected_script_scene_count,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    scene_plan_payload_from_script_content,
)
from app.storytelling.normalization import (
    _fallback_script_content_from_bible as _fallback_script_content_from_bible,
)
from app.storytelling.normalization import (
    _fallback_script_content_from_idea as _fallback_script_content_from_idea,  # noqa: F401
)
from app.storytelling.normalization import (
    _story_idea_db_text as _story_idea_db_text,  # noqa: F401
)
from app.storytelling.normalization import (
    _story_idea_retry_guidance as _story_idea_retry_guidance,  # noqa: F401
)
from app.storytelling.normalization import (
    coerce_duration_minutes as coerce_duration_minutes,
)
from app.storytelling.normalization import (
    normalize_scene_plan_payload as normalize_scene_plan_payload,
)
from app.storytelling.normalization import (
    normalize_story_bible_payload as normalize_story_bible_payload,
)
from app.storytelling.normalization import (
    normalize_story_idea_payload as normalize_story_idea_payload,  # noqa: F401
)
from app.storytelling.normalization import (
    screenplay_validation_errors as screenplay_validation_errors,
)
from app.storytelling.normalization import (
    story_bible_validation_errors as story_bible_validation_errors,
)
from app.storytelling.normalization import (
    story_idea_diversity_errors as story_idea_diversity_errors,
)
from app.storytelling.normalization import (
    story_idea_validation_errors as story_idea_validation_errors,
)
from app.storytelling.schemas import BriefingCreate
from app.storytelling.story_ideas import (
    create_story_idea_from_payload as create_story_idea_from_payload,  # noqa: F401
)
from app.storytelling.story_ideas import (
    generate_story_ideas as generate_story_ideas,  # noqa: F401
)
from app.storytelling.story_ideas import (
    get_latest_briefing,
)
from app.storytelling.story_ideas import (
    list_story_ideas as list_story_ideas,  # noqa: F401
)
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    VIDEO_CLIP_TARGET_SECONDS,
    format_clip_durations,
    video_clip_durations,
)
from app.workflows.state_machine import advance_project_status

SCRIPT_GENERATION_MAX_ATTEMPTS = 3








def _retry_script_generation_after_runtime_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "api_key" in message or "api key" in message or "chave" in message:
        return False
    retry_terms = (
        "json",
        "formato",
        "format",
        "content vazio",
        "fora do formato",
        "resposta fora",
        "timeout",
        "demorou mais",
        "connection",
        "network",
        "temporarily unavailable",
    )
    return any(term in message for term in retry_terms)


def _script_runtime_retry_guidance(exc: Exception) -> str:
    return (
        "A resposta anterior não pôde ser lida pela aplicação: "
        f"{str(exc)[:600]}. Responda com um único objeto JSON válido, sem markdown, "
        "sem comentários antes ou depois, mantendo o roteiro completo em content. "
        "Escape aspas internas de diálogo quando necessário."
    )


def _briefing_payload(data: BriefingCreate) -> dict:
    return data.model_dump(mode="json")


async def create_briefing(
    session: AsyncSession, project_id: UUID, data: BriefingCreate
) -> Briefing | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None

    payload = _briefing_payload(data)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.BRIEFING,
        "Briefing",
        payload,
        ArtifactStatus.APPROVED,
    )
    briefing = Briefing(
        project_id=project_id,
        artifact_id=artifact.id,
        theme=data.theme,
        audience=data.audience,
        genre=data.genre,
        primary_emotion=data.primary_emotion,
        emotional_intensity=data.emotional_intensity,
        ending_type=data.ending_type,
        language=data.language,
        country_context=data.country_context,
        desired_duration_minutes=data.desired_duration_minutes,
        has_narrator=data.has_narrator,
        visual_style=data.visual_style,
        content_objective=data.content_objective,
        call_to_action=data.call_to_action,
        constraints=data.constraints,
    )
    advance_project_status(project, ProjectStatus.IDEA_GENERATION)
    session.add(briefing)
    await session.commit()
    await session.refresh(briefing)
    return briefing












async def generate_script(
    session: AsyncSession, project_id: UUID, story_idea_id: UUID
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    idea = await session.get(StoryIdea, story_idea_id)
    briefing = await get_latest_briefing(session, project_id)
    if (
        project is None
        or idea is None
        or idea.project_id != project_id
        or briefing is None
    ):
        return None

    target_duration_seconds = int(briefing.desired_duration_minutes * Decimal("60"))
    clip_durations = video_clip_durations(target_duration_seconds)
    scene_count = expected_script_scene_count(target_duration_seconds)
    narrative_contract = _idea_script_contract(idea, briefing)
    variables = {
        "narrative_contract": narrative_contract,
        "idea": idea.payload,
        "idea_title": idea.title,
        "language": briefing.language,
        "target_duration_seconds": target_duration_seconds,
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "expected_clip_count": len(clip_durations),
        "expected_scene_count": scene_count,
        "clip_durations": format_clip_durations(clip_durations),
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    payload: dict | None = None
    last_error: GenerationOutputError | None = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        try:
            result, _execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "generate_script",
                variables,
                model=model,
                fallback_on_runtime_error=True,
            )
        except RuntimeError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1 or not (
                _retry_script_generation_after_runtime_error(exc)
            ):
                raise
            variables["retry_guidance"] = _script_runtime_retry_guidance(exc)
            continue
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "generate_script"),
                default_title=idea.title,
                language=briefing.language,
                target_duration_seconds=target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            last_error = exc
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque não seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo content como roteiro de filme limpo e "
                "sem plano tecnico, lista de shots, cenas compactadas em parágrafos ou "
                "sluglines numeradas como '1. INT.'."
            )
    if payload is None:
        if last_error is not None:
            raise last_error
        raise GenerationOutputError("generate_script: resposta vazia do modelo")
    title = _required_str(payload, "title", "generate_script")
    if not str(payload.get("content") or "").strip():
        raise GenerationOutputError("generate_script: resposta sem roteiro")
    artifact = await _create_artifact(
        session, project_id, ArtifactType.SCRIPT, title, payload
    )
    await _add_dependency(session, idea.artifact_id, artifact.id)
    script = Script(
        project_id=project_id,
        artifact_id=artifact.id,
        story_idea_id=idea.id,
        title=title,
        language=_required_str(payload, "language", "generate_script"),
        target_duration_seconds=_required_int(
            payload, "target_duration_seconds", "generate_script"
        ),
        word_count=_required_int(payload, "word_count", "generate_script"),
        content=_required_str(payload, "content", "generate_script"),
    )
    session.add(script)
    await session.flush()
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=1,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    _advance_project_status_when_reachable(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def revise_script(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    instruction: str,
    project_context: dict | None = None,
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or script is None or script.project_id != project_id or briefing is None:
        return None
    artifact = await session.get(Artifact, script.artifact_id)
    if artifact is None:
        return None

    variables = {
        "title": script.title,
        "language": script.language,
        "target_duration_seconds": script.target_duration_seconds,
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "current_script": script.content,
        "instruction": instruction,
        "project_context": project_context or {},
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "revise_script")
    payload: dict | None = None
    execution = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        try:
            result, execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "revise_script",
                variables,
                artifact_id=script.artifact_id,
                model=model,
                fallback_on_runtime_error=True,
            )
        except RuntimeError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1 or not (
                _retry_script_generation_after_runtime_error(exc)
            ):
                raise
            variables["retry_guidance"] = _script_runtime_retry_guidance(exc)
            continue
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "revise_script"),
                default_title=script.title,
                language=script.language,
                target_duration_seconds=script.target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque não seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo apenas roteiro de filme em content, com "
                "FADE IN, CENA, slugline, acao e dialogo em linhas separadas."
            )
    if payload is None or execution is None:
        return None
    title = _required_str(payload, "title", "revise_script")
    content = _required_str(payload, "content", "revise_script")
    script.title = title
    script.language = _required_str(payload, "language", "revise_script")
    script.target_duration_seconds = _required_int(
        payload, "target_duration_seconds", "revise_script"
    )
    script.word_count = _required_int(payload, "word_count", "revise_script")
    script.content = content
    await create_artifact_version(
        session,
        artifact,
        payload,
        change_note=f"Revisão por chat: {instruction[:160]}",
    )
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=artifact.current_version,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    execution.response = result.content
    _advance_project_status_when_reachable(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def _script_embedded_production_plan(
    session: AsyncSession, script: Script
) -> dict | None:
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

    clip_durations = video_clip_durations(script.target_duration_seconds)
    embedded_plan = await _script_embedded_production_plan(session, script)

    scenes: list[Scene] = []
    if embedded_plan is not None:
        try:
            content = normalize_scene_plan_payload_from_script(
                embedded_plan,
                script.target_duration_seconds,
                script.content,
            )
        except GenerationOutputError:
            embedded_plan = None
    if embedded_plan is None:
        local_plan = scene_plan_payload_from_script_content(
            script.content,
            script.target_duration_seconds,
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
                    "target_duration_seconds": script.target_duration_seconds,
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
                script.target_duration_seconds,
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
            shot_context = (
                f"generate_scenes_and_shots.scenes[{scene_index}].shots[{shot_index}]"
            )
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
                    camera_movement=_bounded_required_str(
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

    artifact_result = await session.execute(
        select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.id.in_(stale_artifact_ids),
        )
    )
    for artifact in artifact_result.scalars():
        artifact.status = ArtifactStatus.STALE
    await session.flush()


async def regenerate_scenes_and_shots(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> list[Scene] | None:
    await _mark_existing_scene_plan_stale(session, project_id, script_id)
    return await generate_scenes_and_shots(session, project_id, script_id)
