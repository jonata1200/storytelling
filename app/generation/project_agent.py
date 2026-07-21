import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus
from app.finalization.models import Export, SubtitleTrack
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.generation.director_agent import ask_director_agent
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.quality.models import ContinuityIssue, QualityCheck
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline
from app.storyboards.service import generate_animatic_bundle, generate_storyboard_frames
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryIdea
from app.storytelling.service import (
    generate_scenes_and_shots,
    generate_script,
    generate_story_ideas,
    revise_script,
)
from app.video_generation.models import VideoClip
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import (
    approve_visual_target_and_generate_views,
    default_views_for,
    generate_visual_bible,
    initial_view_for,
)

ProjectChatAction = Literal[
    "chat",
    "generate_ideas",
    "generate_script",
    "revise_script",
    "generate_assets",
    "approve_visual_prompt",
    "generate_storyboard",
    "generate_video",
    "generate_finalization",
    "run_quality",
]

REVISION_TERMS = (
    "ajuste",
    "ajustar",
    "altere",
    "alterar",
    "melhore",
    "melhorar",
    "mude",
    "mudar",
    "modifique",
    "modificar",
    "refaça",
    "refazer",
    "reescreva",
    "reescrever",
    "revise",
    "revisar",
)


@dataclass(frozen=True)
class ProjectChatResult:
    message: str
    action: ProjectChatAction
    changed: bool = False


ProgressCallback = Callable[[str], Awaitable[None]]


ACTION_PROGRESS_MESSAGES: dict[ProjectChatAction, str] = {
    "generate_ideas": "Criando ideias.",
    "generate_script": "Criando roteiro.",
    "revise_script": "Revisando roteiro.",
    "generate_assets": "Criando ativos visuais.",
    "approve_visual_prompt": "Aprovando prompt visual.",
    "generate_storyboard": "Criando storyboard.",
    "generate_video": "Preparando video.",
    "generate_finalization": "Finalizando projeto.",
    "run_quality": "Rodando controle de qualidade.",
    "chat": "Analisando projeto.",
}


async def _emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        await progress(message)


async def _latest(
    session: AsyncSession, model: type[Any], project_id: UUID
) -> Any | None:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _latest_many(
    session: AsyncSession,
    model: type[Any],
    project_id: UUID,
    limit: int = 5,
) -> list[Any]:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _count(session: AsyncSession, model: type[Any], project_id: UUID) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(model.project_id == project_id)
    )
    return int(value or 0)


def _compact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact_payload(item) for key, item in list(value.items())[:24]}
    if isinstance(value, list):
        return [_compact_payload(item) for item in value[:8]]
    return value


async def build_project_context(session: AsyncSession, project_id: UUID) -> dict[str, Any]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return {"project_id": str(project_id), "found": False}

    briefing = await _latest(session, Briefing, project_id)
    idea = await _latest(session, StoryIdea, project_id)
    script = await _latest(session, Script, project_id)
    stale_count = await session.scalar(
        select(func.count())
        .select_from(Artifact)
        .where(Artifact.project_id == project_id, Artifact.status == ArtifactStatus.STALE)
    )
    return {
        "found": True,
        "project": {
            "id": str(project.id),
            "title": project.title,
            "description": project.description,
            "status": project.status,
        },
        "briefing": (
            {
                "theme": briefing.theme,
                "audience": briefing.audience,
                "genre": briefing.genre,
                "primary_emotion": briefing.primary_emotion,
                "duration_minutes": float(briefing.desired_duration_minutes),
                "objective": briefing.content_objective,
                "constraints": briefing.constraints,
            }
            if briefing is not None
            else None
        ),
        "idea": _compact_payload(idea.payload) if idea is not None else None,
        "script": (
            {
                "title": script.title,
                "target_duration_seconds": script.target_duration_seconds,
                "word_count": script.word_count,
                "content_preview": script.content[:1200],
            }
            if script is not None
            else None
        ),
        "counts": {
            "ideas": await _count(session, StoryIdea, project_id),
            "scripts": await _count(session, Script, project_id),
            "scenes": await _count(session, Scene, project_id),
            "shots": await _count(session, Shot, project_id),
            "characters": await _count(session, Character, project_id),
            "locations": await _count(session, Location, project_id),
            "props": await _count(session, Prop, project_id),
            "visual_refs": await _count(session, VisualReference, project_id),
            "frames": await _count(session, StoryboardFrame, project_id),
            "animatics": await _count(session, Animatic, project_id),
            "clips": await _count(session, VideoClip, project_id),
            "timelines": await _count(session, Timeline, project_id),
            "audio_tracks": await _count(session, AudioTrack, project_id),
            "subtitles": await _count(session, SubtitleTrack, project_id),
            "exports": await _count(session, Export, project_id),
            "quality_checks": await _count(session, QualityCheck, project_id),
            "qa_issues": await _count(session, ContinuityIssue, project_id),
            "stale_artifacts": int(stale_count or 0),
        },
        "recent": {
            "scenes": [
                {"number": scene.scene_number, "title": scene.title, "summary": scene.summary}
                for scene in await _latest_many(session, Scene, project_id, 6)
            ],
            "characters": [
                {"name": character.name, "role": character.role}
                for character in await _latest_many(session, Character, project_id, 6)
            ],
            "frames": [
                {
                    "number": frame.frame_number,
                    "duration_seconds": frame.duration_seconds,
                    "prompt": frame.prompt,
                }
                for frame in await _latest_many(session, StoryboardFrame, project_id, 6)
            ],
        },
    }


def classify_project_chat_action(message: str, active: str) -> ProjectChatAction:
    normalized = message.lower()
    generation_terms = (
        "crie",
        "criar",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "faca",
        "fazer",
        "faça",
        "monte",
        "montar",
        "produza",
        "produzir",
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


def _requests_regeneration(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in REVISION_TERMS)


def _normalize_match_text(value: str) -> str:
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def _requests_visual_prompt_approval(message: str) -> bool:
    normalized = _normalize_match_text(message)
    approval_terms = ("aprovar", "aprove", "aprova", "aprovado", "autorizar", "autorize")
    visual_terms = (
        "prompt",
        "imagem",
        "imagens",
        "vista",
        "vistas",
        "referencia",
        "visual",
        "ativo",
        "personagem",
        "local",
        "cenario",
        "objeto",
        "prop",
    )
    return any(term in normalized for term in approval_terms) and any(
        term in normalized for term in visual_terms
    )


@dataclass(frozen=True)
class VisualChatTarget:
    kind: str
    id: UUID
    name: str


def _visual_target_kind_from_message(message: str) -> str | None:
    normalized = _normalize_match_text(message)
    if any(term in normalized for term in ("personagem", "personagens", "character")):
        return "character"
    if any(term in normalized for term in ("local", "locais", "cenario", "cenarios", "location")):
        return "location"
    if any(term in normalized for term in ("objeto", "objetos", "prop", "props")):
        return "prop"
    return None


def _requests_all_visual_targets(message: str) -> bool:
    normalized = _normalize_match_text(message)
    return any(term in normalized for term in ("todos", "todas", "tudo"))


def _requests_all_visual_views(message: str) -> bool:
    normalized = _normalize_match_text(message)
    return any(
        term in normalized
        for term in ("todas as vistas", "todos os prompts", "todas as imagens", "views")
    )


async def _visual_chat_targets(
    session: AsyncSession,
    project_id: UUID,
    target_kind: str | None = None,
) -> list[VisualChatTarget]:
    targets: list[VisualChatTarget] = []
    for kind, model, name_attr in (
        ("character", Character, Character.name),
        ("location", Location, Location.name),
        ("prop", Prop, Prop.name),
    ):
        if target_kind is not None and kind != target_kind:
            continue
        result = await session.execute(
            select(model).where(model.project_id == project_id).order_by(name_attr)
        )
        for item in result.scalars():
            targets.append(VisualChatTarget(kind, item.id, str(item.name)))
    return targets


def _matching_visual_chat_targets(
    message: str, targets: list[VisualChatTarget]
) -> list[VisualChatTarget]:
    normalized = _normalize_match_text(message)
    matches = [
        target
        for target in targets
        if _normalize_match_text(target.name) and _normalize_match_text(target.name) in normalized
    ]
    if matches:
        return matches
    return targets if len(targets) == 1 else []


async def _visual_reference_views_for_target(
    session: AsyncSession,
    project_id: UUID,
    target: VisualChatTarget,
) -> set[str]:
    result = await session.execute(
        select(VisualReference.view_type).where(
            VisualReference.project_id == project_id,
            VisualReference.target_kind == target.kind,
            VisualReference.target_id == target.id,
        )
    )
    return set(result.scalars())


async def _approve_visual_prompt_from_chat(
    session: AsyncSession,
    project_id: UUID,
    message: str,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    target_kind = _visual_target_kind_from_message(message)
    targets = await _visual_chat_targets(session, project_id, target_kind)
    if not targets:
        return ProjectChatResult(
            "Nao encontrei personagens, locais ou objetos para aprovar. "
            "Crie os ativos visuais primeiro.",
            "approve_visual_prompt",
            False,
        )

    if _requests_all_visual_targets(message):
        selected_targets = targets
    else:
        selected_targets = _matching_visual_chat_targets(message, targets)
    if not selected_targets:
        options = ", ".join(target.name for target in targets[:8])
        return ProjectChatResult(
            "Preciso saber qual ativo visual voce quer aprovar. "
            f"Disponiveis agora: {options}.",
            "approve_visual_prompt",
            False,
        )

    created_count = 0
    approved_count = 0
    for target in selected_targets:
        existing_views = await _visual_reference_views_for_target(session, project_id, target)
        if _requests_all_visual_views(message):
            view_types = [
                view for view in default_views_for(target.kind) if view not in existing_views
            ]
        elif not existing_views:
            view_types = [initial_view_for(target.kind)]
        else:
            view_types = [
                view for view in default_views_for(target.kind) if view not in existing_views
            ]
        if not view_types:
            approved_count += 1
            continue
        await _emit_progress(progress, f"Aprovando {target.name} e gerando imagem.")
        references = await approve_visual_target_and_generate_views(
            session,
            project_id,
            target.kind,
            target.id,
            view_types,
        )
        if references is None:
            continue
        approved_count += 1
        created_count += len(references)

    if approved_count == 0:
        return ProjectChatResult(
            "Nao consegui aprovar nenhum ativo visual com esse pedido.",
            "approve_visual_prompt",
            False,
        )
    if created_count == 0:
        return ProjectChatResult(
            f"{approved_count} ativo(s) visual(is) ja estavam com as imagens solicitadas criadas.",
            "approve_visual_prompt",
            True,
        )
    return ProjectChatResult(
        f"Aprovei {approved_count} ativo(s) visual(is) e criei {created_count} imagem(ns).",
        "approve_visual_prompt",
        True,
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
        return ProjectChatResult("Nao consegui gerar ideias para este projeto.", "generate_ideas")
    return ProjectChatResult(f"Criei {len(ideas)} ideia(s) para o projeto.", "generate_ideas", True)


async def _ensure_script_pipeline(
    session: AsyncSession,
    project_id: UUID,
    progress: ProgressCallback | None = None,
) -> tuple[Script | None, str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return None, "Este projeto ainda nao tem briefing para orientar o roteiro.", False

    script = await _latest(session, Script, project_id)
    if script is not None:
        scene_count = await _count(session, Scene, project_id)
        if scene_count == 0:
            await _emit_progress(progress, "O roteiro ja existe. Vou dividir em cenas e planos.")
            scenes = await generate_scenes_and_shots(session, project_id, script.id)
            if scenes is None:
                return script, "O roteiro existe, mas nao consegui criar cenas e planos.", True
            return script, "O roteiro ja existia; criei cenas e planos para ele.", True
        return script, "O projeto ja tem roteiro e cenas.", False

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        await _emit_progress(progress, "Vou criar uma ideia base para orientar o roteiro.")
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return None, "Nao consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    await _emit_progress(
        progress,
        "Vou escrever o roteiro cinematografico a partir da ideia aprovada.",
    )
    script = await generate_script(session, project_id, idea.id)
    if script is None:
        return None, "Nao consegui gerar o roteiro para este projeto.", False
    await _emit_progress(progress, "Roteiro criado. Agora vou separar em cenas e planos.")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return script, "Roteiro criado, mas as cenas e planos nao foram gerados.", True
    return script, "Roteiro criado e dividido em cenas e planos.", True


async def _ensure_visual_pipeline(
    session: AsyncSession,
    project_id: UUID,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id, progress)
    if script is None:
        return ProjectChatResult(message, "generate_assets", changed)

    existing_characters = await _count(session, Character, project_id)
    existing_locations = await _count(session, Location, project_id)
    existing_props = await _count(session, Prop, project_id)
    needs_visual = (
        force
        or existing_characters == 0
        or existing_locations == 0
        or existing_props == 0
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
                "Nao consegui criar personagens e referencias visuais.",
                "generate_assets",
            )
        characters, locations, props = visual
        await _emit_progress(progress, "Vou criar as imagens iniciais de referencia.")
        for target_kind, items in (
            ("character", characters),
            ("location", locations),
            ("prop", props),
        ):
            for item in items:
                await approve_visual_target_and_generate_views(
                    session,
                    project_id,
                    target_kind,
                    item.id,
                    [initial_view_for(target_kind)],
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
        "Personagens, locais, objetos e referencias visuais estao prontos.",
        "generate_assets",
        changed,
    )


async def _ensure_storyboard_pipeline(
    session: AsyncSession,
    project_id: UUID,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> ProjectChatResult:
    script, message, changed = await _ensure_script_pipeline(session, project_id, progress)
    if script is None:
        return ProjectChatResult(message, "generate_storyboard", changed)

    frames = await _count(session, StoryboardFrame, project_id)
    if force or frames == 0:
        await _emit_progress(progress, "Vou transformar as cenas em frames de storyboard.")
        generated_frames = await generate_storyboard_frames(session, project_id, script.id)
        if generated_frames is None:
            return ProjectChatResult(
                "Nao consegui gerar o storyboard.",
                "generate_storyboard",
                changed,
            )
        changed = True

    animatics = await _count(session, Animatic, project_id)
    if force or animatics == 0:
        await _emit_progress(progress, "Vou montar o animatic para validar ritmo e continuidade.")
        bundle = await generate_animatic_bundle(session, project_id, script.id)
        if bundle is None:
            return ProjectChatResult(
                "Storyboard criado, mas o animatic nao foi gerado.",
                "generate_storyboard",
                True,
            )
        changed = True

    return ProjectChatResult(
        "Storyboard e animatic criados para o roteiro atual.",
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

    source_audio = await _latest(session, AudioTrack, project_id)
    if source_audio is None:
        return ProjectChatResult(
            "Nao encontrei audio do animatic para criar a narracao final.",
            "generate_finalization",
            changed,
        )

    await _emit_progress(progress, "Vou sintetizar a narracao final.")
    final_audio = await synthesize_narration(
        session,
        project_id,
        source_audio.id,
        "pt-br-warm-narrator",
    )
    if final_audio is None:
        return ProjectChatResult(
            "Nao consegui gerar a narracao final.",
            "generate_finalization",
            changed,
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
                "Finalizacao preparada, mas ainda faltam clipes selecionados para a timeline.",
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
            "Timeline criada, mas nao consegui exportar o projeto.",
            "generate_finalization",
            changed,
        )
    return ProjectChatResult(
        "Finalizacao criada e exportacao salva no projeto.",
        "generate_finalization",
        True,
    )


async def _ensure_quality_pipeline(session: AsyncSession, project_id: UUID) -> ProjectChatResult:
    check = await run_quality_check(session, project_id)
    if check is None:
        return ProjectChatResult("Nao consegui rodar o controle de qualidade.", "run_quality")
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
    action = classify_project_chat_action(message, active)
    force = _requests_regeneration(message)
    project_context = await build_project_context(session, project_id)
    await _emit_progress(progress, ACTION_PROGRESS_MESSAGES[action])

    if action == "generate_ideas":
        return await _ensure_ideas_pipeline(session, project_id, progress=progress)
    if action == "generate_script":
        _script, result_message, changed = await _ensure_script_pipeline(
            session, project_id, progress
        )
        return ProjectChatResult(result_message, action, changed)
    if action == "revise_script":
        script, result_message, changed = await _ensure_script_pipeline(
            session, project_id, progress
        )
        if script is None:
            return ProjectChatResult(result_message, action, changed)
        revised = await revise_script(session, project_id, script.id, message, project_context)
        if revised is None:
            return ProjectChatResult("Nao consegui aplicar a revisao no roteiro.", action, changed)
        return ProjectChatResult("Roteiro revisado e nova versao salva no projeto.", action, True)
    if action == "generate_assets":
        return await _ensure_visual_pipeline(
            session, project_id, force=force, progress=progress
        )
    if action == "approve_visual_prompt":
        return await _approve_visual_prompt_from_chat(
            session,
            project_id,
            message,
            progress=progress,
        )
    if action == "generate_storyboard":
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
