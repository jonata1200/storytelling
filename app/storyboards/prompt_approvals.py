from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.production.service import get_or_create_production_settings
from app.projects.repository import ProjectRepository
from app.storyboards.prompts import (
    _prompt_hash,
    _store_storyboard_prompt_approval,
    _store_storyboard_prompt_override,
    _storyboard_effective_prompt,
    _storyboard_prompt,
    _storyboard_prompt_is_approved,
    _storyboard_visual_context,
)
from app.storyboards.queries import list_storyboard_frames
from app.storyboards.workflow import _selected_storyboard_shots
from app.storytelling.models import Scene, Script, Shot


async def list_storyboard_prompt_previews(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    scene_number: int | None = None,
    shot_id: UUID | None = None,
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
