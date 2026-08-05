import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.storyboards.prompts import (
    _prompt_hash,
    _store_storyboard_generated_prompt,
    _store_storyboard_prompt_approval,
    _store_storyboard_prompt_override,
    _storyboard_effective_prompt,
    _storyboard_generated_prompt_map,
    _storyboard_generated_prompt_source_hash_map,
    _storyboard_prompt,
    _storyboard_prompt_is_approved,
    _storyboard_reference_uris_for_shot,
    _storyboard_visual_context,
    storyboard_continuity_checklist,
)
from app.storyboards.queries import list_storyboard_frames
from app.storyboards.workflow import _selected_storyboard_shots
from app.storytelling.models import Scene, Script, Shot


def _storyboard_generation_payload(shot_rows: list[tuple[Shot, Scene]]) -> list[dict]:
    return [
        {
            "shot_id": str(shot.id),
            "scene_number": scene.scene_number,
            "shot_number": shot.shot_number,
            "duration_seconds": shot.duration_seconds,
            "action": shot.action,
            "emotion": shot.emotion,
            "visual_composition": shot.visual_composition,
            "camera_movement": shot.camera_movement,
            "narration_text": shot.narration_text,
            "dialogue_text": shot.dialogue_text,
        }
        for shot, scene in shot_rows
    ]


def _storyboard_generated_prompt_payload(content: dict) -> dict[str, str]:
    raw_prompts = content.get("prompts")
    prompts = raw_prompts if isinstance(raw_prompts, list) else []
    prompt_by_shot: dict[str, str] = {}
    for item in prompts:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if shot_id and prompt:
            prompt_by_shot[shot_id] = prompt
    return prompt_by_shot


async def _ensure_storyboard_prompts_generated_with_llm(
    session: AsyncSession,
    project_id: UUID,
    script: Script,
    shot_rows: list[tuple[Shot, Scene]],
    visual_context: dict,
    metadata: dict,
) -> dict:
    generated_prompts = _storyboard_generated_prompt_map(metadata, script.id)
    generated_hashes = _storyboard_generated_prompt_source_hash_map(metadata, script.id)
    default_prompt_by_shot = {
        shot.id: _storyboard_prompt(shot, scene, visual_context) for shot, scene in shot_rows
    }
    pending_rows = [
        (shot, scene)
        for shot, scene in shot_rows
        if generated_prompts.get(str(shot.id)) is None
        or generated_hashes.get(str(shot.id)) != _prompt_hash(default_prompt_by_shot[shot.id])
    ]
    if not pending_rows:
        return metadata

    fallback_prompts = [
        {
            "shot_id": str(shot.id),
            "prompt": default_prompt_by_shot[shot.id],
        }
        for shot, _scene in pending_rows
    ]
    provider, model = await llm_provider_for_task(
        session,
        project_id,
        "generate_storyboard_prompts",
    )
    result, _execution = await run_structured_generation(
        session,
        provider,
        project_id,
        "generate_storyboard_prompts",
        {
            "script": script.content,
            "shots": json.dumps(
                _storyboard_generation_payload(pending_rows),
                ensure_ascii=False,
            ),
            "visual_context": json.dumps(visual_context, ensure_ascii=False),
            "fallback_prompts": json.dumps(fallback_prompts, ensure_ascii=False),
        },
        artifact_id=script.artifact_id,
        model=model,
        fallback_on_runtime_error=True,
    )
    fallback_prompt_by_shot = {
        str(item["shot_id"]): str(item["prompt"]) for item in fallback_prompts
    }
    llm_prompt_by_shot = _storyboard_generated_prompt_payload(result.content)
    if not llm_prompt_by_shot:
        llm_prompt_by_shot = fallback_prompt_by_shot
    else:
        for shot, _scene in pending_rows:
            shot_key = str(shot.id)
            llm_prompt_by_shot.setdefault(shot_key, fallback_prompt_by_shot[shot_key])

    updated = metadata
    changed = False
    for shot, _scene in pending_rows:
        default_prompt = default_prompt_by_shot[shot.id]
        prompt = llm_prompt_by_shot[str(shot.id)]
        updated = _store_storyboard_generated_prompt(
            updated,
            script.id,
            shot.id,
            prompt,
            _prompt_hash(default_prompt),
        )
        changed = True
    if changed:
        production_settings = await get_or_create_production_settings(session, project_id)
        production_settings.metadata_json = updated
        await session.commit()
    return updated


async def list_storyboard_prompt_previews(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    scene_number: int | None = None,
    shot_id: UUID | None = None,
    generate_missing: bool = True,
) -> list[dict]:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return []
    try:
        _all_shot_rows, shot_rows, frame_number_by_shot = await _selected_storyboard_shots(
            session,
            project_id,
            script_id,
            scene_number=scene_number,
            shot_id=shot_id,
        )
    except ValueError:
        return []
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    visual_context = await _storyboard_visual_context(session, project_id)
    if generate_missing:
        metadata = await _ensure_storyboard_prompts_generated_with_llm(
            session,
            project_id,
            script,
            shot_rows,
            visual_context,
            metadata,
        )
    existing_frames = await list_storyboard_frames(session, project_id, script_id)
    existing_by_shot = {frame.shot_id: frame for frame in existing_frames}
    previews: list[dict] = []
    for shot, scene in shot_rows:
        default_prompt = _storyboard_prompt(shot, scene, visual_context)
        prompt = _storyboard_effective_prompt(
            metadata,
            script_id,
            shot.id,
            default_prompt,
        )
        prompt_hash = _prompt_hash(prompt)
        reference_uris = await _storyboard_reference_uris_for_shot(
            session,
            project_id,
            shot,
            scene,
        )
        previews.append(
            {
                "shot_id": shot.id,
                "scene_id": scene.id,
                "scene_number": scene.scene_number,
                "shot_number": shot.shot_number,
                "frame_number": frame_number_by_shot[shot.id],
                "duration_seconds": shot.duration_seconds,
                "prompt": prompt,
                "default_prompt": default_prompt,
                "prompt_hash": prompt_hash,
                "reference_count": len(reference_uris),
                "continuity_checks": storyboard_continuity_checklist(prompt, reference_uris),
                "custom_prompt": prompt != default_prompt,
                "approved": _storyboard_prompt_is_approved(
                    metadata,
                    script_id,
                    shot.id,
                    prompt_hash,
                ),
                "generated": shot.id in existing_by_shot,
            }
        )
    return previews


async def approve_storyboard_prompts(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    scene_number: int | None = None,
) -> int:
    previews = await list_storyboard_prompt_previews(
        session,
        project_id,
        script_id,
        scene_number=scene_number,
    )
    if not previews:
        return 0
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    approved_count = 0
    for preview in previews:
        if preview["approved"]:
            continue
        metadata = _store_storyboard_prompt_approval(
            metadata,
            script_id,
            preview["shot_id"],
            preview["prompt_hash"],
        )
        approved_count += 1
    production_settings.metadata_json = metadata
    await session.commit()
    return approved_count


async def approve_storyboard_prompt(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
) -> bool:
    previews = await list_storyboard_prompt_previews(
        session,
        project_id,
        script_id,
        shot_id=shot_id,
    )
    if not previews:
        return False
    preview = previews[0]
    if preview["approved"]:
        return False
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    production_settings.metadata_json = _store_storyboard_prompt_approval(
        metadata,
        script_id,
        preview["shot_id"],
        preview["prompt_hash"],
    )
    await session.commit()
    return True


async def update_storyboard_prompt(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    shot_id: UUID,
    prompt: str,
) -> bool:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise ValueError("Informe um prompt de storyboard antes de salvar.")
    previews = await list_storyboard_prompt_previews(
        session,
        project_id,
        script_id,
        shot_id=shot_id,
    )
    if not previews:
        return False
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    production_settings.metadata_json = _store_storyboard_prompt_override(
        metadata,
        script_id,
        shot_id,
        cleaned_prompt,
    )
    await session.commit()
    return True


async def storyboard_prompts_need_approval(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    scene_number: int | None = None,
) -> bool:
    previews = await list_storyboard_prompt_previews(
        session,
        project_id,
        script_id,
        scene_number=scene_number,
    )
    if not previews:
        return True
    return any(not preview["approved"] for preview in previews)


async def _ensure_storyboard_prompts_approved(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    shot_rows: list[tuple[Shot, Scene]],
    visual_context: dict,
) -> dict[UUID, str]:
    production_settings = await get_or_create_production_settings(session, project_id)
    metadata = production_settings.metadata_json or {}
    script = await session.get(Script, script_id)
    if script is not None:
        metadata = await _ensure_storyboard_prompts_generated_with_llm(
            session,
            project_id,
            script,
            shot_rows,
            visual_context,
            metadata,
        )
    prompt_by_shot: dict[UUID, str] = {}
    pending: list[str] = []
    for shot, scene in shot_rows:
        default_prompt = _storyboard_prompt(shot, scene, visual_context)
        prompt = _storyboard_effective_prompt(
            metadata,
            script_id,
            shot.id,
            default_prompt,
        )
        prompt_by_shot[shot.id] = prompt
        if not _storyboard_prompt_is_approved(
            metadata,
            script_id,
            shot.id,
            _prompt_hash(prompt),
        ):
            pending.append(f"cena {scene.scene_number}, plano {shot.shot_number}")
    if pending:
        sample = "; ".join(pending[:5])
        if len(pending) > 5:
            sample += f"; e mais {len(pending) - 5}"
        raise ValueError(
            f"Aprove os prompts de storyboard antes de gerar imagens. Pendentes: {sample}."
        )
    return prompt_by_shot
