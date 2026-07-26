from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.generation.director_agent import ask_director_agent
from app.generation.model_settings import llm_provider_for_task
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
from app.generation.project_agent_types import (
    ACTION_PROGRESS_MESSAGES,
    ProgressCallback,
    ProjectChatAction,
    ProjectChatIntent,
    ProjectChatResult,
    _emit_progress,
)
from app.generation.service import run_structured_generation
from app.projects.versioning import mark_dependents_stale
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline
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


def classify_project_chat_action(message: str, active: str) -> ProjectChatAction:
    normalized = _normalize_match_text(message)
    generation_terms = (
        "avancar",
        "avance",
        "continuar",
        "continue",
        "criacao",
        "crie",
        "criar",
        "desenvolvimento",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "faca",
        "fazer",
        "faça",
        "monte",
        "montar",
        "parta",
        "partir",
        "produza",
        "produzir",
        "prosseguir",
        "prossiga",
        "seguir",
        "siga",
        "exporte",
        "exportar",
        "finalize",
        "finalizar",
        "valide",
        "validar",
        "rode",
        "rodar",
        "execute",
        "executar",
    )
    script_terms = ("roteiro", "historia", "história", "cena", "cenas", "dialogo", "diálogo")
    idea_terms = (
        "ideia",
        "ideias",
        "premissa",
        "premissas",
        "opcao",
        "opcoes",
        "opção",
        "opções",
    )
    bible_terms = (
        "story bible",
        "bible",
        "biblia",
        "bíblia",
        "universo",
        "mundo",
    )
    asset_terms = (
        "personagem",
        "personagens",
        "visual",
        "cenario",
        "cenarios",
        "locais",
        "local",
        "objeto",
        "objetos",
        "props",
        "referencia",
        "referência",
    )
    storyboard_terms = (
        "storyboard",
        "quadro",
        "quadros",
        "frame",
        "frames",
        "enquadramento",
        "animatic",
    )
    video_terms = ("video", "vídeo", "clipe", "clipes", "montagem")

    finalization_terms = (
        "finalizacao",
        "finalização",
        "finalizar",
        "export",
        "exportar",
        "timeline",
        "legenda",
        "legendas",
        "narracao",
        "narração",
    )
    quality_terms = (
        "qualidade",
        "qa",
        "controle",
        "continuidade",
        "validar",
        "validacao",
        "validação",
    )

    wants_generation = any(term in normalized for term in generation_terms)
    wants_revision = _requests_regeneration(message)
    actionable = wants_generation or wants_revision

    if _requests_visual_prompt_approval(message):
        return "approve_visual_prompt"
    if _requests_full_script_regeneration(message):
        return "generate_script"
    if actionable and any(term in normalized for term in quality_terms):
        return "run_quality"
    if actionable and any(term in normalized for term in finalization_terms):
        return "generate_finalization"
    if actionable and any(term in normalized for term in video_terms):
        return "generate_video"
    if actionable and any(term in normalized for term in storyboard_terms):
        return "generate_storyboard"
    if actionable and any(term in normalized for term in asset_terms):
        return "generate_assets"
    if actionable and any(term in normalized for term in bible_terms):
        return "generate_script"
    if wants_generation and any(term in normalized for term in idea_terms):
        return "generate_ideas"
    if wants_revision and (active == "script" or any(term in normalized for term in script_terms)):
        return "revise_script"
    if wants_revision:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
    if wants_generation and (
        active == "script" or any(term in normalized for term in script_terms)
    ):
        return "generate_script"
    if wants_generation:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
        return "generate_script"
    return "chat"


def _context_counts(project_context: dict[str, Any]) -> dict[str, int]:
    raw_counts = project_context.get("counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        try:
            normalized[key] = int(value or 0)
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def _workflow_progression_requested(message: str) -> bool:
    normalized = _normalize_match_text(message)
    terms = (
        "agora que",
        "avancar",
        "avance",
        "continuar",
        "continue",
        "etapa seguinte",
        "partir",
        "pode seguir",
        "proxima etapa",
        "proximo passo",
        "prosseguir",
        "prossiga",
        "seguir",
        "siga",
    )
    return any(term in normalized for term in terms)


def _next_project_action(active: str, project_context: dict[str, Any]) -> ProjectChatAction:
    counts = _context_counts(project_context)
    scripts = counts.get("scripts", 0)
    scenes = counts.get("scenes", 0)
    shots = counts.get("shots", 0)
    characters = counts.get("characters", 0)
    locations = counts.get("locations", 0)
    props = counts.get("props", 0)
    frames = counts.get("frames", 0)
    clips = counts.get("clips", 0)

    if scripts == 0:
        return "generate_script"
    if scenes == 0 or shots == 0:
        return "generate_script"
    if characters == 0 or locations == 0 or props == 0:
        return "generate_assets"
    if frames == 0:
        return "generate_storyboard"
    if clips == 0:
        return "generate_video"
    if active == "video":
        return "generate_finalization"
    return "run_quality"


def _contextual_project_chat_intent(
    message: str,
    active: str,
    project_context: dict[str, Any],
    classified_action: ProjectChatAction,
) -> ProjectChatIntent:
    normalized = _normalize_match_text(message)
    if _requests_visual_prompt_approval(message):
        return ProjectChatIntent("approve_visual_prompt", 1.0, "pedido explicito de aprovacao")

    asset_phrase = all(term in normalized for term in ("personagens", "locais", "objetos"))
    if asset_phrase and _workflow_progression_requested(message):
        return ProjectChatIntent(
            "generate_assets",
            0.96,
            "pedido para avancar criando personagens, locais e objetos",
        )

    if _workflow_progression_requested(message):
        next_action = _next_project_action(active, project_context)
        return ProjectChatIntent(next_action, 0.86, "pedido para avancar no fluxo do projeto")

    if classified_action != "chat":
        return ProjectChatIntent(classified_action, 0.8, "classificador por regras")

    return ProjectChatIntent("chat", 0.0, "sem intencao executavel clara")


def _coerce_project_chat_action(value: object) -> ProjectChatAction:
    action = str(value or "").strip()
    valid_actions = set(ACTION_PROGRESS_MESSAGES)
    return cast(ProjectChatAction, action) if action in valid_actions else "chat"


async def _infer_project_chat_intent_with_ai(
    session: AsyncSession,
    project_id: UUID,
    active: str,
    message: str,
    project_context: dict[str, Any],
) -> ProjectChatIntent:
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    prompt = (
        "Interprete a intencao operacional do usuario dentro de um software de criacao "
        "audiovisual. Retorne somente JSON valido, sem markdown. Acoes possiveis: "
        "chat, generate_ideas, generate_script, revise_script, generate_assets, "
        "approve_visual_prompt, generate_storyboard, generate_video, generate_finalization, "
        "run_quality. Use o estado real do projeto para decidir se o usuario quer executar "
        "uma etapa ou apenas conversar. Se a confianca for menor que 0.70, use chat. "
        'Formato: {"action":"generate_assets","confidence":0.92,"reason":"..."}. '
        f"Etapa ativa: {active}. Estado do projeto: {project_context}. "
        f"Mensagem do usuario: {message}"
    )
    try:
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "director_agent_chat",
            {
                "prompt": prompt,
                "section": active,
                "message": message,
                "project_context": project_context,
                "history": [],
            },
            model=model,
            fallback_on_runtime_error=True,
        )
    except Exception:
        return ProjectChatIntent("chat", 0.0, "falha ao interpretar por IA")

    action = _coerce_project_chat_action(
        result.content.get("action") or result.content.get("intent")
    )
    try:
        confidence = float(result.content.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(result.content.get("reason") or "").strip()
    if confidence < 0.7:
        action = "chat"
    return ProjectChatIntent(action, confidence, reason)


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


async def _ensure_ideas_pipeline(
    session: AsyncSession,
    project_id: UUID,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return ProjectChatResult(
            "Este projeto ainda nao tem briefing para orientar as ideias.",
            "generate_ideas",
        )

    existing_ideas = await _count(session, StoryIdea, project_id)
    if existing_ideas > 0:
        return ProjectChatResult(
            "O projeto ja tem ideias registradas. Posso ajudar a escolher ou ajustar uma delas.",
            "generate_ideas",
            False,
        )

    await _emit_progress(progress, "Vou criar ideias narrativas a partir do briefing.")
    ideas = await generate_story_ideas(session, project_id)
    if not ideas:
        return ProjectChatResult(
            "Não consegui gerar ideias para este projeto.",
            "generate_ideas",
            failed=True,
        )
    return ProjectChatResult(f"Criei {len(ideas)} ideia(s) para o projeto.", "generate_ideas", True)


async def _project_has_visual_bible(session: AsyncSession, project_id: UUID) -> bool:
    return any(
        [
            await _count(session, Character, project_id),
            await _count(session, Location, project_id),
            await _count(session, Prop, project_id),
        ]
    )


async def _refresh_visual_bible_after_script_regeneration(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    progress: ProgressCallback | None = None,
) -> bool:
    if not await _project_has_visual_bible(session, project_id):
        return False
    await _emit_progress(
        progress,
        "Vou atualizar automaticamente personagens, locais e objetos a partir do novo roteiro.",
    )
    visual = await generate_visual_bible(session, project_id, script_id)
    if visual is None:
        await _emit_progress(
            progress,
            "Nao consegui atualizar automaticamente a biblioteca visual.",
        )
        return False
    await _emit_progress(
        progress,
        "Biblioteca visual atualizada para o roteiro atual.",
    )
    return True


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
                return script, "O roteiro existe, mas não consegui criar cenas e planos.", True
            return script, "O roteiro ja existia; criei cenas e planos para ele.", True
        return script, "O projeto ja tem roteiro e cenas.", False

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        await _emit_progress(progress, "Vou criar uma ideia base para orientar o roteiro.")
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return None, "Não consegui gerar uma ideia base para este projeto.", False
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
        return None, "Não consegui gerar o roteiro para este projeto.", False
    await _emit_progress(progress, "Roteiro criado. Agora vou separar em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return script, "Roteiro criado, mas as cenas e planos não foram gerados.", True
    if force:
        visual_updated = await _refresh_visual_bible_after_script_regeneration(
            session,
            project_id,
            script.id,
            progress,
        )
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
                "Não consegui criar personagens, locais e objetos.",
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
                f"{scene_copy} precisam ser aprovados antes da geração das imagens. "
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
                "Não consegui gerar o storyboard.",
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
                "Storyboard criado, mas o animatic não foi gerado.",
                "generate_storyboard",
                True,
                True,
            )
        changed = True

    message = "Storyboard e animatic criados para o roteiro atual."
    if scene_number is not None:
        message = (
            f"Storyboard da cena {scene_number} criado/atualizado. "
            "O storyboard completo já está coberto e o animatic foi validado."
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

    source_audio = await _latest(session, AudioTrack, project_id)
    if source_audio is None:
        return ProjectChatResult(
            "Nao encontrei audio do animatic para criar a narracao final.",
            "generate_finalization",
            changed,
        )

    await _emit_progress(progress, "Vou sintetizar a narracao final.")
    try:
        final_audio = await synthesize_narration(
            session,
            project_id,
            source_audio.id,
            "pt-br-warm-narrator",
        )
    except ValueError as exc:
        return ProjectChatResult(str(exc), "generate_finalization", changed, True)
    if final_audio is None:
        return ProjectChatResult(
            "Não consegui gerar a narração final.",
            "generate_finalization",
            changed,
            True,
        )
    changed = True

    await _emit_progress(progress, "Vou gerar as legendas.")
    subtitle = await generate_subtitles(session, project_id, final_audio.id)
    if subtitle is not None:
        changed = True

    timeline = await _latest(session, Timeline, project_id)
    if timeline is None:
        await _emit_progress(progress, "Vou montar a timeline final.")
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
                "Finalização preparada, mas ainda faltam clipes selecionados para a timeline.",
                "generate_finalization",
                changed,
            )
        changed = True

    await _emit_progress(progress, "Vou exportar a timeline.")
    exported = await export_timeline(
        session,
        project_id,
        timeline.id,
        subtitle.id if subtitle else None,
    )
    if exported is None:
        return ProjectChatResult(
            "Timeline criada, mas não consegui exportar o projeto.",
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
            "Não consegui rodar o controle de qualidade.",
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
                "Não consegui aplicar a revisão no roteiro.",
                action,
                changed,
                True,
            )
        await _emit_progress(progress, "Vou recriar cenas e planos a partir do roteiro revisado.")
        scenes = await regenerate_scenes_and_shots(session, project_id, revised.id)
        if scenes is None:
            return ProjectChatResult(
                "Roteiro revisado, mas não consegui recriar cenas e planos.",
                action,
                True,
                True,
            )
        if _requests_specific_script_scenes(message):
            return ProjectChatResult(
                "Cena(s) revisada(s) e cenas/planos recriados para o roteiro atual.",
                action,
                True,
            )
        return ProjectChatResult(
            "Roteiro revisado e cenas/planos recriados para o projeto.",
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
