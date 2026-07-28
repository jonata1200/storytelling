from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.finalization.service import (
    create_final_timeline,
    export_timeline,
)
from app.generation.director_agent import ask_director_agent
from app.generation.project_agent_context import (
    _active_scene_count_for_script,
    _count,
    _latest,
    build_project_context,
)
from app.generation.project_agent_context import (
    _compact_payload as _compact_payload,
)
from app.generation.project_agent_context import (
    _latest_many as _latest_many,
)
from app.generation.project_agent_intent import (
    _is_ai_generation_failure_message,
    _is_visual_reference_gate_message,
    _requested_storyboard_scene_number,
    _requests_full_script_regeneration,
    _requests_specific_script_scenes,
)
from app.generation.project_agent_routing import (
    _contextual_project_chat_intent,
    _infer_project_chat_intent_with_ai,
    classify_project_chat_action,
)
from app.generation.project_agent_support import (
    _ensure_ideas_pipeline,
    _refresh_visual_bible_after_script_regeneration,
)
from app.generation.project_agent_types import (
    ACTION_PROGRESS_MESSAGES,
    ProgressCallback,
    ProjectChatResult,
    _emit_progress,
)
from app.generation.project_agent_visual import (  # noqa: E402,F401
    VisualChatTarget,
    _approve_visual_prompt_from_chat,
    _matching_visual_chat_targets,
    _normalize_match_text,
    _requests_all_visual_targets,
    _requests_all_visual_views,
    _requests_regeneration,
    _requests_visual_prompt_approval,
    _visual_chat_targets,
    _visual_reference_views_for_target,
    _visual_target_kind_from_message,
)
from app.projects.versioning import (
    mark_dependents_stale,
    resolve_stale_artifacts_after_regeneration,
)
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic, StoryboardFrame, Timeline
from app.storyboards.service import (
    generate_animatic_bundle,
    generate_storyboard_frames,
    storyboard_frames_need_generation,
    storyboard_prompts_need_approval,
)
from app.storytelling.models import Briefing, Script, StoryIdea
from app.storytelling.service import (
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
    regenerate_scenes_and_shots,
    revise_script,
)
from app.video_generation.models import VideoClip
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import (  # noqa: F401
    approve_visual_target_and_generate_views as approve_visual_target_and_generate_views,
)
from app.visual_bible.service import (
    generate_visual_bible,
    visual_reference_completion_message,
    visual_reference_completion_report,
)


async def _ensure_script_pipeline(
    session: AsyncSession,
    project_id: UUID,
    progress: ProgressCallback | None = None,
    force: bool = False,
) -> tuple[Script | None, str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return None, "Este projeto ainda nao tem briefing para orientar o roteiro.", False

    script = await _latest(session, Script, project_id)
    if script is not None and not force:
        scene_count = await _active_scene_count_for_script(session, project_id, script.id)
        if scene_count == 0:
            await _emit_progress(progress, "O roteiro ja existe. Vou dividir em cenas e planos.")
            scenes = await generate_scenes_and_shots(session, project_id, script.id)
            if scenes is None:
                return script, "O roteiro existe, mas nÃ£o consegui criar cenas e planos.", True
            return script, "O roteiro ja existia; criei cenas e planos para ele.", True
        return script, "O projeto ja tem roteiro e cenas.", False

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        await _emit_progress(progress, "Vou criar uma ideia base para orientar o roteiro.")
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return None, "NÃ£o consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    if script is not None and force:
        await _emit_progress(
            progress,
            "Vou gerar novamente o roteiro completo e atualizar as cenas derivadas.",
        )
        await mark_dependents_stale(session, {script.artifact_id})
    else:
        await _emit_progress(
            progress,
            "Vou escrever o roteiro cinematografico a partir da ideia aprovada.",
        )

    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return None, "NÃ£o consegui gerar o roteiro para este projeto.", False
    await _emit_progress(progress, "Roteiro criado. Agora vou separar em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return script, "Roteiro criado, mas as cenas e planos nÃ£o foram gerados.", True
    if force:
        visual_updated = await _refresh_visual_bible_after_script_regeneration(
            session,
            project_id,
            script.id,
            progress,
        )
        await resolve_stale_artifacts_after_regeneration(session, project_id)
        if visual_updated:
            return (
                script,
                "Roteiro completo gerado novamente, cenas/planos recriados "
                "e biblioteca visual atualizada.",
                True,
            )
        return script, "Roteiro completo gerado novamente e dividido em cenas e planos.", True
    return script, "Roteiro criado e dividido em cenas e planos.", True


async def _ensure_visual_pipeline(
    session: AsyncSession,
    project_id: UUID,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id, progress)
    if script is None:
        return ProjectChatResult(
            message,
            "generate_assets",
            changed,
            failed=_is_ai_generation_failure_message(message),
        )

    existing_characters = await _count(session, Character, project_id)
    existing_locations = await _count(session, Location, project_id)
    existing_props = await _count(session, Prop, project_id)
    needs_visual = (
        force or existing_characters == 0 or existing_locations == 0 or existing_props == 0
    )
    changed = changed or needs_visual
    if needs_visual:
        await _emit_progress(
            progress,
            "Vou extrair personagens, locais e objetos do roteiro para a biblioteca visual.",
        )
        visual = await generate_visual_bible(session, project_id, script.id)
        if visual is None:
            return ProjectChatResult(
                "NÃ£o consegui criar personagens, locais e objetos.",
                "generate_assets",
                failed=True,
            )
        await _emit_progress(
            progress,
            "Prompts visuais criados. Revise e aprove antes de gerar imagens.",
        )

    visual_refs = await _count(session, VisualReference, project_id)
    if visual_refs == 0:
        return ProjectChatResult(
            "Personagens, locais e objetos foram preparados. "
            "Revise e aprove os prompts na aba Biblioteca visual para criar as imagens.",
            "generate_assets",
            changed,
        )
    return ProjectChatResult(
        "Personagens, locais e objetos ja existem. "
        "Revise os prompts ou aprove-os para gerar imagens.",
        "generate_assets",
        changed,
    )


async def _ensure_storyboard_pipeline(
    session: AsyncSession,
    project_id: UUID,
    force: bool = False,
    progress: ProgressCallback | None = None,
    scene_number: int | None = None,
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id, progress)
    if script is None:
        return ProjectChatResult(
            message,
            "generate_storyboard",
            changed,
            failed=_is_ai_generation_failure_message(message),
        )

    visual_report = await visual_reference_completion_report(session, project_id)
    if not visual_report["complete"]:
        return ProjectChatResult(
            visual_reference_completion_message(visual_report),
            "generate_storyboard",
            changed,
        )

    if (
        scene_number is not None
        or force
        or await storyboard_frames_need_generation(session, project_id, script.id)
    ):
        if await storyboard_prompts_need_approval(
            session,
            project_id,
            script.id,
            scene_number=scene_number,
        ):
            scene_copy = f" da cena {scene_number}" if scene_number is not None else ""
            return ProjectChatResult(
                "Os prompts de storyboard"
                f"{scene_copy} precisam ser aprovados antes da geraÃ§Ã£o das imagens. "
                "Abra a aba Storyboard, revise os cards de prompt e clique em aprovar.",
                "generate_storyboard",
                changed,
            )
        if scene_number is None:
            await _emit_progress(progress, "Vou transformar as cenas em frames de storyboard.")
        else:
            await _emit_progress(
                progress,
                f"Vou transformar a cena {scene_number} em frames de storyboard.",
            )
        generated_frames = await generate_storyboard_frames(
            session,
            project_id,
            script.id,
            scene_number=scene_number,
            force=force,
        )
        if generated_frames is None:
            return ProjectChatResult(
                "NÃ£o consegui gerar o storyboard.",
                "generate_storyboard",
                changed,
                True,
            )
        changed = True

    if scene_number is not None and await storyboard_frames_need_generation(
        session, project_id, script.id
    ):
        return ProjectChatResult(
            f"Storyboard da cena {scene_number} criado/atualizado. "
            "As demais cenas ainda precisam de storyboard antes de montar o animatic completo.",
            "generate_storyboard",
            changed,
        )

    animatics = await _count(session, Animatic, project_id)
    if force or animatics == 0:
        await _emit_progress(progress, "Vou montar o animatic para validar ritmo e continuidade.")
        bundle = await generate_animatic_bundle(session, project_id, script.id)
        if bundle is None:
            return ProjectChatResult(
                "Storyboard criado, mas o animatic nÃ£o foi gerado.",
                "generate_storyboard",
                True,
                True,
            )
        changed = True

    message = "Storyboard e animatic criados para o roteiro atual."
    if scene_number is not None:
        message = (
            f"Storyboard da cena {scene_number} criado/atualizado. "
            "O storyboard completo jÃ¡ estÃ¡ coberto e o animatic foi validado."
        )
    return ProjectChatResult(
        message,
        "generate_storyboard",
        changed,
    )


async def _ensure_video_pipeline(
    session: AsyncSession,
    project_id: UUID,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    storyboard_result = await _ensure_storyboard_pipeline(
        session, project_id, force=force, progress=progress
    )
    changed = storyboard_result.changed
    if _is_visual_reference_gate_message(storyboard_result.message):
        return ProjectChatResult(
            storyboard_result.message,
            "generate_video",
            changed,
            storyboard_result.failed,
        )
    frames = await _latest_many(session, StoryboardFrame, project_id, 100)
    if not frames:
        return ProjectChatResult(
            "Nao ha frames de storyboard para gerar video.",
            "generate_video",
            changed,
        )

    clips = await _count(session, VideoClip, project_id)
    if not force and clips > 0:
        return ProjectChatResult(
            "Os clipes de video ja existem para este storyboard.",
            "generate_video",
            changed,
        )
    return ProjectChatResult(
        "Storyboard pronto. Revise e aprove os prompts na aba Video para gerar os clipes.",
        "generate_video",
        changed,
    )


async def _ensure_finalization_pipeline(
    session: AsyncSession,
    project_id: UUID,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    storyboard_result = await _ensure_storyboard_pipeline(session, project_id, progress=progress)
    changed = storyboard_result.changed
    if _is_visual_reference_gate_message(storyboard_result.message):
        return ProjectChatResult(
            storyboard_result.message,
            "generate_finalization",
            changed,
            storyboard_result.failed,
        )

    timeline = await _latest(session, Timeline, project_id)
    if timeline is None:
        await _emit_progress(progress, "Vou montar a timeline final sem narracao.")
        animatic = await _latest(session, Animatic, project_id)
        try:
            timeline = await create_final_timeline(
                session,
                project_id,
                animatic.id if animatic else None,
            )
        except ValueError as exc:
            return ProjectChatResult(str(exc), "generate_finalization", changed)
        if timeline is None:
            return ProjectChatResult(
                "Finalizacao preparada, mas ainda faltam clipes selecionados para a timeline.",
                "generate_finalization",
                changed,
            )
        changed = True

    await _emit_progress(progress, "Vou exportar a timeline sem narracao.")
    exported = await export_timeline(
        session,
        project_id,
        timeline.id,
    )
    if exported is None:
        return ProjectChatResult(
            "Timeline criada, mas nao consegui exportar o projeto.",
            "generate_finalization",
            changed,
            True,
        )
    return ProjectChatResult(
        "Finalizacao criada e exportacao salva no projeto.",
        "generate_finalization",
        True,
    )


async def _ensure_quality_pipeline(session: AsyncSession, project_id: UUID) -> ProjectChatResult:
    check = await run_quality_check(session, project_id)
    if check is None:
        return ProjectChatResult(
            "NÃ£o consegui rodar o controle de qualidade.",
            "run_quality",
            failed=True,
        )
    return ProjectChatResult(
        f"Controle de qualidade concluido com score {check.score} ({check.status}).",
        "run_quality",
        True,
    )


async def handle_project_chat(
    session: AsyncSession,
    project_id: UUID,
    active: str,
    message: str,
    history: list[dict[str, str]],
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    project_context = await build_project_context(session, project_id)
    classified_action = classify_project_chat_action(message, active)
    intent = _contextual_project_chat_intent(message, active, project_context, classified_action)
    if intent.action == "chat":
        ai_intent = await _infer_project_chat_intent_with_ai(
            session,
            project_id,
            active,
            message,
            project_context,
        )
        if ai_intent.action != "chat":
            intent = ai_intent
    action = intent.action
    force = _requests_regeneration(message) or _requests_full_script_regeneration(message)
    await _emit_progress(progress, ACTION_PROGRESS_MESSAGES[action])

    if action == "generate_ideas":
        return await _ensure_ideas_pipeline(session, project_id, progress=progress)
    if action == "generate_script":
        _script, result_message, changed = await _ensure_script_pipeline(
            session, project_id, progress, force=force
        )
        return ProjectChatResult(
            result_message,
            action,
            changed,
            failed=_is_ai_generation_failure_message(result_message),
        )
    if action == "revise_script":
        script, result_message, changed = await _ensure_script_pipeline(
            session, project_id, progress
        )
        if script is None:
            return ProjectChatResult(
                result_message,
                action,
                changed,
                failed=_is_ai_generation_failure_message(result_message),
            )
        revised = await revise_script(session, project_id, script.id, message, project_context)
        if revised is None:
            return ProjectChatResult(
                "NÃ£o consegui aplicar a revisÃ£o no roteiro.",
                action,
                changed,
                True,
            )
        await _emit_progress(progress, "Vou recriar cenas e planos a partir do roteiro revisado.")
        scenes = await regenerate_scenes_and_shots(session, project_id, revised.id)
        if scenes is None:
            return ProjectChatResult(
                "Roteiro revisado, mas nÃ£o consegui recriar cenas e planos.",
                action,
                True,
                True,
            )
        visual_updated = await _refresh_visual_bible_after_script_regeneration(
            session,
            project_id,
            revised.id,
            progress,
        )
        await resolve_stale_artifacts_after_regeneration(session, project_id)
        if _requests_specific_script_scenes(message):
            return ProjectChatResult(
                "Cena(s) revisada(s), cenas/planos recriados e artefatos antigos substituidos.",
                action,
                True,
            )
        if visual_updated:
            return ProjectChatResult(
                (
                    "Roteiro revisado, cenas/planos recriados e Biblioteca Visual "
                    "atualizada para o projeto."
                ),
                action,
                True,
            )
        return ProjectChatResult(
            "Roteiro revisado, cenas/planos recriados e artefatos antigos substituidos.",
            action,
            True,
        )
    if action == "generate_assets":
        return await _ensure_visual_pipeline(session, project_id, force=force, progress=progress)
    if action == "approve_visual_prompt":
        return await _approve_visual_prompt_from_chat(
            session,
            project_id,
            message,
            progress=progress,
        )
    if action == "generate_storyboard":
        scene_number = _requested_storyboard_scene_number(message)
        if scene_number is not None:
            return await _ensure_storyboard_pipeline(
                session,
                project_id,
                force=force,
                progress=progress,
                scene_number=scene_number,
            )
        return await _ensure_storyboard_pipeline(
            session, project_id, force=force, progress=progress
        )
    if action == "generate_video":
        return await _ensure_video_pipeline(session, project_id, force=force, progress=progress)
    if action == "generate_finalization":
        return await _ensure_finalization_pipeline(session, project_id, progress=progress)
    if action == "run_quality":
        return await _ensure_quality_pipeline(session, project_id)

    response = await ask_director_agent(
        session,
        project_id,
        active,
        message,
        project_context,
        history,
    )
    return ProjectChatResult(response, "chat", False)
