# ruff: noqa: E501

import asyncio
import base64
import logging
import mimetypes
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from nicegui import app as nicegui_app
from nicegui import background_tasks, ui
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.preferences import save_preferences
from app.config.settings import get_settings
from app.core.enums import ArtifactStatus
from app.costs.models import CostEntry
from app.database.session import AsyncSessionLocal
from app.finalization.models import Export, SubtitleTrack
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.generation.model_settings import (
    NARRATIVE_TASKS,
    TASK_LABELS,
    ensure_default_model_settings,
    set_model_setting,
)
from app.generation.models import ProjectModelSetting
from app.generation.project_agent import handle_project_chat
from app.production.models import ProjectProductionSettings
from app.production.service import (
    ASPECT_RATIOS,
    CONTENT_TYPES,
    RESOLUTIONS,
    WORKFLOW_MODES,
    get_or_create_production_settings,
    update_production_settings,
)
from app.projects.models import Artifact, Project
from app.projects.repository import ProjectRepository
from app.projects.schemas import ProjectCreate
from app.projects.service import (
    create_project,
    delete_all_projects,
    delete_project,
    list_projects,
    rename_project,
)
from app.quality.models import ContinuityIssue, QualityCheck
from app.quality.service import run_quality_check
from app.storyboards.models import (
    Animatic,
    AudioTrack,
    StoryboardFrame,
    Timeline,
    TimelineItem,
)
from app.storyboards.service import generate_animatic_bundle, generate_storyboard_frames
from app.storytelling.idea_lab import (
    delete_all_ideas,
    delete_generated_idea,
    delete_saved_idea,
    generate_freeform_ideas,
    load_generated_ideas,
    load_saved_ideas,
    replace_generated_ideas,
    save_idea,
)
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryBible, StoryIdea
from app.storytelling.schemas import BriefingCreate
from app.storytelling.service import (
    coerce_duration_minutes,
    create_briefing,
    create_story_idea_from_payload,
    generate_scenes_and_shots,
    generate_script,
    generate_story_bible,
    generate_story_ideas,
)
from app.video_generation.models import GenerationJob, VideoClip
from app.video_generation.service import generate_video_clips
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import generate_visual_bible, generate_visual_references

BRAND_MARK_URL = "/ui-assets/favicon.png"
DEFAULT_STORY_DURATION_MINUTES = 5.0
STORY_DURATION_OPTIONS = [3, 4, 5, 6, 7, 8]
BLOCKING_DIALOG_PROPS = "persistent no-esc-dismiss no-backdrop-dismiss"
logger = logging.getLogger(__name__)

IDEA_GENRES = [
    "Ação",
    "Animação",
    "Aventura",
    "Comédia",
    "Documentário",
    "Drama",
    "Fantasia",
    "Ficção Científica",
    "Histórias familiares emocionantes",
    "Romance",
    "Suspense (Thriller)",
    "Terror (ou Horror)",
]


@dataclass(frozen=True)
class ProductionStep:
    key: str
    title: str
    description: str
    action_label: str
    icon: str


PRODUCTION_STEPS = [
    ProductionStep(
        "briefing",
        "Briefing",
        "Defina tema, publico, emocao, duracao e objetivo do video.",
        "Criar novo projeto",
        "edit_note",
    ),
    ProductionStep(
        "ideas",
        "Ideias",
        "Gere tres caminhos narrativos e escolha a melhor promessa emocional.",
        "Gerar ideias",
        "tips_and_updates",
    ),
    ProductionStep(
        "bible",
        "Story Bible",
        "Congele regras narrativas, personagens, locais, objetos e estilo.",
        "Gerar Story Bible",
        "menu_book",
    ),
    ProductionStep(
        "script",
        "Roteiro",
        "Crie o texto base, duracao alvo, cenas e planos estruturados.",
        "Gerar roteiro",
        "description",
    ),
    ProductionStep(
        "visual",
        "Visual",
        "Crie fichas canonicas e referencias visuais aprovaveis.",
        "Gerar visual",
        "palette",
    ),
    ProductionStep(
        "storyboard",
        "Storyboard",
        "Transforme planos em quadros, animatic e timeline preliminar.",
        "Gerar storyboard",
        "view_comfy",
    ),
    ProductionStep(
        "video",
        "Video",
        "Gere clipes mock por plano, com jobs, assets e custos rastreados.",
        "Gerar clipes",
        "movie",
    ),
    ProductionStep(
        "finalization",
        "Finalizacao",
        "Crie narracao final, legendas, timeline final e exportacao.",
        "Finalizar",
        "auto_awesome_motion",
    ),
    ProductionStep(
        "quality",
        "Qualidade",
        "Rode continuity ledger, alertas, score e observabilidade do projeto.",
        "Rodar QA",
        "verified",
    ),
]


def _body_style() -> None:
    ui.colors(primary="#5898d4")
    ui.dark_mode(value=get_settings().user_theme != "light")
    ui.page_title(get_settings().app_name)
    ui.query("body").classes("studio-body")
    ui.add_head_html(f'<link rel="icon" type="image/png" href="{BRAND_MARK_URL}">')
    ui.add_head_html(
        r"""
        <meta name="theme-color" content="#090b0a">
        <style>
          @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
          :root { --ink:#080a09; --panel:#111412; --line:#272c28; --acid:#5898d4; --muted:#969c97; }
          body.studio-body { background:var(--ink); color:#f4f5f2; font-family:'DM Sans',sans-serif; }
          body:not(.body--dark).studio-body { background:#f4f5ef; color:#171a17; }
          body:not(.body--dark) .glass,
          body:not(.body--dark) .entity-card { background:#ffffff; border-color:#d9ded7; }
          body:not(.body--dark) .chat-shell { box-shadow:0 20px 60px rgba(25,35,25,.12); }
          body:not(.body--dark) .desktop-nav,
          body:not(.body--dark) .right-assistant,
          body:not(.body--dark) .bg-slate-900,
          body:not(.body--dark) .bg-slate-800,
          body:not(.body--dark) .bg-\[\#0b0d0c\],
          body:not(.body--dark) .bg-\[\#090b0a\],
          body:not(.body--dark) .bg-\[\#0d0f0e\],
          body:not(.body--dark) .bg-\[\#0d100e\] { background:#f8faf6!important; }
          body:not(.body--dark) .border-slate-800,
          body:not(.body--dark) .border-\[\#222622\],
          body:not(.body--dark) .border-\[\#242824\],
          body:not(.body--dark) .border-\[\#252925\],
          body:not(.body--dark) .border-\[\#343934\],
          body:not(.body--dark) .border-\[\#363b36\] { border-color:#d9ded7!important; }
          body:not(.body--dark) .text-slate-100,
          body:not(.body--dark) .text-slate-300,
          body:not(.body--dark) .text-\[\#b8bdb8\],
          body:not(.body--dark) .text-\[\#c8ccc8\],
          body:not(.body--dark) .text-\[\#d1d4d1\],
          body:not(.body--dark) .text-\[\#d4d8d4\],
          body:not(.body--dark) .text-\[\#d7dbd7\],
          body:not(.body--dark) .text-\[\#d8dbd8\],
          body:not(.body--dark) .text-\[\#d9dcd9\] { color:#20261f!important; }
          body:not(.body--dark) .text-slate-400,
          body:not(.body--dark) .text-\[\#747a75\],
          body:not(.body--dark) .text-\[\#777d78\],
          body:not(.body--dark) .text-\[\#7f8580\],
          body:not(.body--dark) .text-\[\#858b86\],
          body:not(.body--dark) .text-\[\#878d88\],
          body:not(.body--dark) .text-\[\#8d938e\],
          body:not(.body--dark) .text-\[\#8e948f\],
          body:not(.body--dark) .text-\[\#8f9590\],
          body:not(.body--dark) .text-\[\#939994\],
          body:not(.body--dark) .text-\[\#969c97\],
          body:not(.body--dark) .text-\[\#999f9a\],
          body:not(.body--dark) .text-\[\#9aa29b\] { color:#626b62!important; }
          body:not(.body--dark) .bg-\[\#243342\] { background:#e8f3ff!important; }
          body:not(.body--dark) .bg-\[\#2f3321\],
          body:not(.body--dark) .bg-\[\#30362b\],
          body:not(.body--dark) .bg-\[\#26301f\] { background:#eff5dc!important; }
          body:not(.body--dark) .text-\[\#bfe2ff\] { color:#24577c!important; }
          body:not(.body--dark) .text-\[\#dff57b\],
          body:not(.body--dark) .text-\[\#e6f59b\],
          body:not(.body--dark) .text-\[\#eaf878\] { color:#4f6417!important; }
          body:not(.body--dark) .visual-placeholder { background:radial-gradient(circle at 70% 15%,#e6e9c9 0,#d9ddcf 42%,#eef0e9 80%); }
          body:not(.body--dark) .q-field__control { background:#ffffff!important; }
          body:not(.body--dark) .q-field__native,
          body:not(.body--dark) .q-field__input,
          body:not(.body--dark) .q-textarea textarea { color:#171a17!important; }
          body:not(.body--dark) .q-menu { background:#ffffff!important; color:#171a17!important; }
          .studio-body .nicegui-content { padding:0; }
          .brand-type { font-family:'Manrope',sans-serif; letter-spacing:-.04em; }
          .glass { background:rgba(17,20,18,.88); border:1px solid var(--line); }
          .acid { color:var(--acid); }
          .acid-bg { background:var(--acid)!important; color:#10120d!important; }
          .nav-pill { border:1px solid transparent; color:#8c918d; transition:.2s ease; }
          .nav-pill:hover { color:#eaf3ff; background:#171a18; }
          .nav-active { color:#ffffff!important; background:var(--acid)!important; border-color:rgba(255,255,255,.45)!important; min-width:92px; }
          .nav-active .q-btn__content,
          .nav-active .q-btn__content span,
          .nav-active .q-icon { color:#ffffff!important; opacity:1!important; }
          .nav-locked { color:#78a8d5!important; background:transparent!important; border-color:transparent!important; }
          .nav-locked:hover { color:#78a8d5!important; background:transparent!important; }
          body:not(.body--dark) .nav-pill { color:#6d756f; }
          body:not(.body--dark) .nav-pill:hover { color:#2c6da7; background:#edf6ff; }
          body:not(.body--dark) .nav-active { color:#ffffff!important; background:var(--acid)!important; border-color:transparent!important; }
          body:not(.body--dark) .nav-active .q-btn__content,
          body:not(.body--dark) .nav-active .q-btn__content span,
          body:not(.body--dark) .nav-active .q-icon { color:#ffffff!important; opacity:1!important; }
          body:not(.body--dark) .nav-locked,
          body:not(.body--dark) .nav-locked:hover { color:#6aa4d8!important; background:transparent!important; border-color:transparent!important; }
          .idea-badge-genre { background:#243342!important; color:#d9efff!important; }
          .idea-badge-emotion { background:#2f3321!important; color:#f1ff9f!important; }
          .idea-badge-duration { background:#2d2636!important; color:#eadfff!important; }
          body:not(.body--dark) .idea-badge-genre { background:#d7ebff!important; color:#164b77!important; }
          body:not(.body--dark) .idea-badge-emotion { background:#eaf5c6!important; color:#40540e!important; }
          body:not(.body--dark) .idea-badge-duration { background:#eee4ff!important; color:#54358a!important; }
          .entity-card { background:#151816; border:1px solid #252a26; transition:.2s ease; }
          .entity-card:hover { transform:translateY(-2px); border-color:#555d4c; }
          .visual-placeholder { background:radial-gradient(circle at 70% 15%,#4e5531 0,#24281e 32%,#141614 70%); }
          .chat-shell { box-shadow:0 30px 90px rgba(0,0,0,.45); }
          .q-field__label { color: #b9beb9 !important; }
          .q-field__native, .q-field__input, .q-textarea textarea {
            color: #f8fafc !important;
          }
          .q-field__control {
            background: #181b19 !important;
            border-radius: 14px !important;
          }
          .assistant-chat-messages { overscroll-behavior:contain; }
          .assistant-chat-bubble { white-space:pre-wrap; overflow-wrap:anywhere; }
          .assistant-chat-input .q-field__control { min-height:48px!important; height:auto!important; max-height:132px!important; }
          .assistant-chat-input .q-field__native,
          .assistant-chat-input.q-textarea textarea {
            min-height:24px!important;
            max-height:96px!important;
            line-height:20px!important;
            padding-top:12px!important;
            padding-bottom:12px!important;
            resize:none!important;
            overflow-y:auto!important;
          }
          .q-field__control::before { border-color: #303530 !important; }
          .q-field__control::after { color: var(--acid) !important; }
          .q-field--focused .q-field__label { color: var(--acid) !important; }
          .q-placeholder::placeholder { color: #777d78 !important; }
          .q-menu { background: #151816 !important; color: #f8fafc !important; }
          ::-webkit-scrollbar { width:7px; height:7px } ::-webkit-scrollbar-thumb { background:#363b36; border-radius:10px }
          @media(max-width:900px){.desktop-nav{display:none!important}.workspace-main{padding:18px!important}.right-assistant{display:none!important}}
        </style>
        """
    )


def _card_classes(extra: str = "") -> str:
    return f"bg-slate-900 border border-slate-800 rounded-md shadow-none {extra}".strip()


def _button_classes() -> str:
    return "bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold rounded-md"


def _muted(text: str) -> None:
    ui.label(text).classes("text-sm text-slate-400")


async def _scalar_count(
    session: AsyncSession, model: type[Any], project_id: UUID | None = None
) -> int:
    statement = select(func.count()).select_from(model)
    if project_id is not None and hasattr(model, "project_id"):
        statement = statement.where(model.project_id == project_id)
    value = await session.scalar(statement)
    return int(value or 0)


async def _latest(session: AsyncSession, model: type[Any], project_id: UUID) -> Any | None:
    result = await session.execute(
        select(model).where(model.project_id == project_id).order_by(model.created_at.desc())
    )
    return result.scalars().first()


async def _latest_many(
    session: AsyncSession,
    model: type[Any],
    project_id: UUID,
    limit: int = 6,
) -> list[Any]:
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _project_cards() -> list[Project]:
    try:
        async with AsyncSessionLocal() as session:
            return await list_projects(session)
    except Exception:
        return []


async def _dashboard_metrics() -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            project_count = await _scalar_count(session, Project)
            artifact_count = await _scalar_count(session, Artifact)
            job_count = await _scalar_count(session, GenerationJob)
            open_issues = await session.scalar(
                select(func.count())
                .select_from(ContinuityIssue)
                .where(ContinuityIssue.accepted.is_(False))
            )
            exports = await _scalar_count(session, Export)
    except Exception as exc:
        return {"Banco": "indisponivel", "Detalhe": type(exc).__name__}
    return {
        "Projetos": str(project_count),
        "Artefatos": str(artifact_count),
        "Jobs": str(job_count),
        "Alertas QA": str(open_issues or 0),
        "Exports": str(exports),
    }


async def _project_summary(project_id: UUID) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        project = await ProjectRepository(session).get_project(project_id)
        if project is None:
            return None
        await ensure_default_model_settings(session, project_id)
        production_settings = await get_or_create_production_settings(session, project_id)
        model_result = await session.execute(
            select(ProjectModelSetting)
            .where(ProjectModelSetting.project_id == project_id)
            .order_by(ProjectModelSetting.task)
        )
        cost_total = await session.scalar(
            select(func.coalesce(func.sum(CostEntry.total_cost), Decimal("0.000000"))).where(
                CostEntry.project_id == project_id
            )
        )
        latest_quality = await _latest(session, QualityCheck, project_id)
        latest_export = await _latest(session, Export, project_id)
        latest_timeline = await _latest(session, Timeline, project_id)
        timeline_items: list[TimelineItem] = []
        if latest_timeline is not None:
            item_result = await session.execute(
                select(TimelineItem)
                .where(TimelineItem.timeline_id == latest_timeline.id)
                .order_by(TimelineItem.order_index)
                .limit(12)
            )
            timeline_items = list(item_result.scalars())
        return {
            "project": project,
            "production_settings": production_settings,
            "counts": {
                "briefings": await _scalar_count(session, Briefing, project_id),
                "ideas": await _scalar_count(session, StoryIdea, project_id),
                "bibles": await _scalar_count(session, StoryBible, project_id),
                "scripts": await _scalar_count(session, Script, project_id),
                "scenes": await _scalar_count(session, Scene, project_id),
                "shots": await _scalar_count(session, Shot, project_id),
                "characters": await _scalar_count(session, Character, project_id),
                "visual_refs": await _scalar_count(session, VisualReference, project_id),
                "frames": await _scalar_count(session, StoryboardFrame, project_id),
                "animatics": await _scalar_count(session, Animatic, project_id),
                "clips": await _scalar_count(session, VideoClip, project_id),
                "audio": await _scalar_count(session, AudioTrack, project_id),
                "subtitles": await _scalar_count(session, SubtitleTrack, project_id),
                "exports": await _scalar_count(session, Export, project_id),
                "qa_issues": await _scalar_count(session, ContinuityIssue, project_id),
                "stale_artifacts": int(
                    await session.scalar(
                        select(func.count())
                        .select_from(Artifact)
                        .where(
                            Artifact.project_id == project_id,
                            Artifact.status == ArtifactStatus.STALE,
                        )
                    )
                    or 0
                ),
            },
            "cost_total": str(cost_total or Decimal("0.000000")),
            "quality": latest_quality,
            "export": latest_export,
            "model_settings": list(model_result.scalars()),
            "script": await _latest(session, Script, project_id),
            "scenes": await _latest_many(session, Scene, project_id, 12),
            "shots": await _latest_many(session, Shot, project_id, 20),
            "characters": await _latest_many(session, Character, project_id, 4),
            "locations": await _latest_many(session, Location, project_id, 4),
            "props": await _latest_many(session, Prop, project_id, 4),
            "visual_refs": await _latest_many(session, VisualReference, project_id, 6),
            "frames": await _latest_many(session, StoryboardFrame, project_id, 9),
            "clips": await _latest_many(session, VideoClip, project_id, 6),
            "timeline": latest_timeline,
            "timeline_items": timeline_items,
        }


def _step_ready(step_key: str, counts: dict[str, int]) -> bool:
    readiness = {
        "briefing": counts["briefings"] > 0,
        "ideas": counts["ideas"] > 0,
        "bible": counts["bibles"] > 0,
        "script": counts["scripts"] > 0,
        "visual": counts["characters"] > 0,
        "storyboard": counts["frames"] > 0 and counts["animatics"] > 0,
        "video": counts["clips"] > 0,
        "finalization": counts["exports"] > 0,
        "quality": counts["qa_issues"] >= 0,
    }
    return readiness[step_key]


def _render_project_card(project: Project, redirect_to: str) -> None:
    with ui.dialog() as rename_dialog, ui.card().classes("entity-card rounded-2xl p-6 min-w-96"):
        ui.label("Renomear projeto").classes("brand-type text-2xl font-bold")
        name_input = ui.input("Nome do projeto", value=project.title).props("outlined").classes(
            "w-full"
        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=rename_dialog.close).props("flat no-caps")
            ui.button(
                "Salvar",
                icon="save",
                on_click=lambda p=project.id: _rename_project_from_ui(
                    p, str(name_input.value or ""), redirect_to
                ),
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")

    with ui.dialog() as delete_dialog, ui.card().classes("entity-card rounded-2xl p-6 min-w-96"):
        ui.label("Excluir projeto?").classes("brand-type text-2xl font-bold")
        ui.label(
            f'O projeto "{project.title}" será removido da lista de projetos.'
        ).classes("text-sm text-[#8d938e]")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancelar", on_click=delete_dialog.close).props("flat no-caps")
            ui.button(
                "Excluir",
                icon="delete",
                on_click=lambda p=project.id: _delete_project_from_ui(p, redirect_to),
            ).props("unelevated no-caps").classes("bg-red-600 text-white rounded-xl")

    with (
        ui.element("article")
        .classes("entity-card rounded-2xl overflow-hidden cursor-pointer")
        .on("click", lambda p=project.id: ui.navigate.to(f"/projects/{p}/script"))
    ):
        with ui.element("div").classes("visual-placeholder aspect-video p-5 flex items-end"):
            ui.icon("play_circle").classes("text-4xl acid")
        with ui.column().classes("p-4 gap-2"):
            ui.label(project.title).classes("brand-type text-xl font-bold")
            ui.label(project.description or "Projeto em desenvolvimento").classes(
                "text-sm text-[#8d938e] line-clamp-2"
            )
            with ui.row().classes("gap-2 mt-2 flex-wrap"):
                ui.button("Renomear", icon="edit", on_click=rename_dialog.open).props(
                    "flat no-caps"
                ).classes("text-[#aeb3ae]").on(
                    "click.stop", lambda: None
                )
                ui.button("Excluir", icon="delete", on_click=delete_dialog.open).props(
                    "flat no-caps"
                ).classes("text-red-300").on(
                    "click.stop", lambda: None
                )


def _workspace_section_access(section: str, counts: dict[str, int]) -> tuple[bool, str]:
    script_ready = _step_ready("script", counts)
    assets_ready = _step_ready("visual", counts)
    storyboard_ready = _step_ready("storyboard", counts)
    if section == "script":
        return True, ""
    if section == "assets":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar personagens."
        return True, ""
    if section == "storyboard":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar o storyboard."
        if not assets_ready:
            return False, "Crie os personagens antes de acessar o storyboard."
        return True, ""
    if section == "video":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar video."
        if not assets_ready:
            return False, "Crie os personagens antes de acessar video."
        if not storyboard_ready:
            return False, "Crie o storyboard antes de acessar video."
        return True, ""
    return False, "Etapa desconhecida."


def _first_available_workspace_section(counts: dict[str, int]) -> str:
    for section in ["video", "storyboard", "assets", "script"]:
        allowed, _ = _workspace_section_access(section, counts)
        if allowed:
            return section
    return "script"


def _render_header(title: str, subtitle: str) -> None:
    with ui.row().classes(
        "w-full items-center justify-between px-6 py-4 bg-slate-900 border-b border-slate-800"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("movie_filter").classes("text-3xl text-cyan-300")
            with ui.column().classes("gap-0"):
                ui.label(title).classes("text-2xl font-bold")
                ui.label(subtitle).classes("text-sm text-slate-400")
        with ui.row().classes("gap-2"):
            _theme_toggle()
            ui.button(
                "Projetos", icon="dashboard", on_click=lambda: ui.navigate.to("/projects")
            ).classes("bg-slate-800 hover:bg-slate-700 rounded-md")
            ui.link("API docs", "/docs").classes(
                "text-slate-100 bg-slate-800 hover:bg-slate-700 px-3 py-2 rounded-md"
            )


def _compact_project_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    cleaned = " ".join((first_line or text).strip().split())
    if not cleaned:
        return "Novo projeto de storytelling"
    common_prefixes = [
        "quero criar uma historia sobre ",
        "quero criar uma história sobre ",
        "quero desenvolver uma historia sobre ",
        "quero desenvolver uma história sobre ",
        "crie uma historia sobre ",
        "crie uma história sobre ",
        "uma historia sobre ",
        "uma história sobre ",
    ]
    lower_cleaned = cleaned.lower()
    for prefix in common_prefixes:
        if lower_cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip(" ,;:-")
            if cleaned:
                cleaned = cleaned[:1].upper() + cleaned[1:]
            break
    first_sentence = cleaned
    for separator in [".", "!", "?"]:
        if separator in first_sentence:
            first_sentence = first_sentence.split(separator, 1)[0].strip()
            break
    words = first_sentence.split()
    if len(words) > 9:
        first_sentence = " ".join(words[:9])
    return first_sentence[:80].strip(" ,;:-") or "Novo projeto de storytelling"


def _format_idea_payload_for_project(idea: dict[str, Any]) -> str:
    labels = {
        "title": "Titulo",
        "theme": "Tema",
        "genre": "Genero",
        "primary_emotion": "Emocao principal",
        "final_emotion": "Emocao final",
        "hook": "Gancho",
        "premise": "Premissa",
        "protagonist": "Protagonista",
        "protagonist_desire": "Desejo do protagonista",
        "emotional_need": "Necessidade emocional",
        "conflict": "Conflito",
        "obstacles": "Obstaculos",
        "stakes": "Riscos narrativos",
        "twist": "Virada",
        "climax": "Climax",
        "resolution": "Resolucao",
        "duration_minutes": "Duracao",
        "retention_potential": "Potencial de retencao",
        "cliche_risk": "Risco de cliche",
        "production_complexity": "Complexidade de producao",
    }
    ordered_keys = [key for key in labels if key in idea]
    ordered_keys.extend(key for key in idea if key not in labels and not key.startswith("_"))
    lines: list[str] = []
    for key in ordered_keys:
        value = idea.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value_text = ", ".join(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            value_text = "; ".join(f"{item_key}: {item_value}" for item_key, item_value in value.items())
        else:
            value_text = str(value)
        if key == "duration_minutes":
            value_text = f"{coerce_duration_minutes(value):g} minutos"
        lines.append(f"{labels.get(key, key)}: {value_text}")
    return "\n".join(lines)


async def _generate_initial_script(
    session: AsyncSession,
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
) -> Script:
    if source_idea is not None:
        idea = await create_story_idea_from_payload(session, project_id, source_idea)
        if idea is None:
            raise ValueError("nao foi possivel registrar a ideia selecionada")
    else:
        generated_ideas = await generate_story_ideas(session, project_id)
        if not generated_ideas:
            raise ValueError("nao foi possivel gerar ideias iniciais")
        idea = generated_ideas[0]

    story_bible = await generate_story_bible(session, project_id, idea.id)
    if story_bible is None:
        raise ValueError("nao foi possivel gerar a Story Bible")
    script = await generate_script(session, project_id, story_bible.id)
    if script is None:
        raise ValueError("nao foi possivel gerar roteiro")
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        raise ValueError("nao foi possivel gerar cenas e planos")
    return script


async def _set_project_ai_action_status(
    session: AsyncSession,
    project_id: UUID,
    *,
    status: str,
    message: str,
    action: str = "create_initial_script",
    error: str | None = None,
) -> None:
    settings = await get_or_create_production_settings(session, project_id)
    metadata = dict(settings.metadata_json or {})
    metadata["ai_action"] = {
        "action": action,
        "status": status,
        "message": message,
        "error": error,
    }
    settings.metadata_json = metadata
    await session.commit()


async def _generate_initial_script_in_background(
    project_id: UUID,
    source_idea: dict[str, Any] | None = None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="A IA esta criando o roteiro inicial com base na ideia.",
            )
            await _generate_initial_script(session, project_id, source_idea)
            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Roteiro inicial criado.",
            )
    except Exception:
        logger.exception("Nao foi possivel gerar roteiro inicial do projeto %s", project_id)
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA nao conseguiu criar o roteiro inicial.",
                error="Consulte o terminal para ver o erro completo.",
            )


async def _generate_missing_scenes_in_background(project_id: UUID, script_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            settings = await get_or_create_production_settings(session, project_id)
            metadata = settings.metadata_json or {}
            action = metadata.get("ai_action") if isinstance(metadata, dict) else None
            status = str(action.get("status") or "") if isinstance(action, dict) else ""
            if status in {"queued", "running"}:
                return

            scene_count = await _scalar_count(session, Scene, project_id)
            if scene_count > 0:
                await _set_project_ai_action_status(
                    session,
                    project_id,
                    status="completed",
                    message="Cenas e planos ja estavam criados.",
                    action="create_script_scenes",
                )
                return

            await _set_project_ai_action_status(
                session,
                project_id,
                status="running",
                message="A IA esta criando cenas e planos para o roteiro.",
                action="create_script_scenes",
            )
            scenes = await generate_scenes_and_shots(session, project_id, script_id)
            if scenes is None:
                raise ValueError("nao foi possivel gerar cenas e planos")
            await _set_project_ai_action_status(
                session,
                project_id,
                status="completed",
                message="Cenas e planos criados para o roteiro.",
                action="create_script_scenes",
            )
    except Exception:
        logger.exception("Nao foi possivel gerar cenas do roteiro %s", script_id)
        async with AsyncSessionLocal() as session:
            await _set_project_ai_action_status(
                session,
                project_id,
                status="failed",
                message="A IA nao conseguiu criar cenas e planos.",
                action="create_script_scenes",
                error="Consulte o terminal para ver o erro completo.",
            )


async def _reload_project_when_script_ready(project_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        script = await _latest(session, Script, project_id)
        scene_count = await _scalar_count(session, Scene, project_id)
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        action = metadata.get("ai_action") if isinstance(metadata, dict) else None
        status = str(action.get("status") or "") if isinstance(action, dict) else ""
    if status in {"completed", "failed"} or (script is not None and scene_count > 0):
        ui.navigate.reload()


def _requests_script_generation(message: str, active: str) -> bool:
    normalized = message.lower()
    generation_terms = (
        "crie",
        "criar",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "monte",
        "montar",
        "produza",
        "produzir",
    )
    script_terms = ("roteiro", "cena", "cenas", "historia", "história")
    if not any(term in normalized for term in generation_terms):
        return False
    return active == "script" or any(term in normalized for term in script_terms)


async def _develop_script_for_existing_project(
    session: AsyncSession, project_id: UUID
) -> tuple[str, bool]:
    briefing = await _latest(session, Briefing, project_id)
    if briefing is None:
        return (
            "Este projeto ainda nao tem briefing. Crie o projeto pelo chat inicial ou preencha o briefing primeiro.",
            False,
        )

    script = await _latest(session, Script, project_id)
    if script is not None:
        scenes_count = await _scalar_count(session, Scene, project_id)
        if scenes_count == 0:
            await generate_scenes_and_shots(session, project_id, script.id)
            return "O roteiro ja existia; criei as cenas e planos para ele.", True
        return "Este projeto ja tem roteiro e cenas. Posso ajudar a revisar ou ajustar a estrutura.", False

    idea = await _latest(session, StoryIdea, project_id)
    if idea is None:
        ideas = await generate_story_ideas(session, project_id)
        if not ideas:
            return "Nao consegui gerar uma ideia base para este projeto.", False
        idea = ideas[0]

    bible = await _latest(session, StoryBible, project_id)
    if bible is None:
        bible = await generate_story_bible(session, project_id, idea.id)
        if bible is None:
            return "Nao consegui gerar a Story Bible antes do roteiro.", False

    script = await generate_script(session, project_id, bible.id)
    if script is None:
        return "Nao consegui gerar o roteiro para este projeto.", False
    scenes = await generate_scenes_and_shots(session, project_id, script.id)
    if scenes is None:
        return "O roteiro foi criado, mas nao consegui gerar as cenas e planos.", True
    return "Roteiro criado e dividido em cenas e planos.", True


async def _create_project_from_form(
    form: dict[str, Any],
    *,
    generate_initial_script: bool = False,
    source_idea: dict[str, Any] | None = None,
) -> None:
    try:
        duration = coerce_duration_minutes(form["duration"])
        project_id: UUID
        async with AsyncSessionLocal() as session:
            project = await create_project(
                session,
                ProjectCreate(title=form["title"], description=form["description"]),
            )
            project_id = project.id
            await ensure_default_model_settings(session, project.id)
            await update_production_settings(
                session,
                project.id,
                {
                    "content_type": form["content_type"],
                    "aspect_ratio": form["aspect_ratio"],
                    "image_resolution": form["image_resolution"],
                    "video_resolution": form["video_resolution"],
                    "workflow_mode": form["workflow_mode"],
                    "image_model": form["image_model"],
                    "video_model": form["video_model"],
                    "motion_intensity": int(form["motion_intensity"]),
                    "metadata_json": {
                        "one_line_idea": form["one_line_idea"],
                        "source_idea": form.get("source_idea_payload"),
                    },
                },
            )
            briefing = BriefingCreate(
                theme=form["theme"],
                audience=form["audience"],
                genre=form["genre"],
                primary_emotion=form["emotion"],
                emotional_intensity=int(form["intensity"]),
                ending_type=form["ending"],
                desired_duration_minutes=Decimal(str(duration)),
                visual_style=form["visual_style"],
                content_objective=form["objective"],
                call_to_action=form["cta"] or None,
                constraints=[
                    item.strip() for item in form["constraints"].splitlines() if item.strip()
                ],
            )
            await create_briefing(session, project.id, briefing)
            if generate_initial_script:
                await _set_project_ai_action_status(
                    session,
                    project.id,
                    status="queued",
                    message="A IA vai iniciar a criacao do roteiro inicial.",
                )
        if generate_initial_script:
            background_tasks.create(
                _generate_initial_script_in_background(
                    project_id,
                    dict(source_idea) if source_idea is not None else None,
                ),
                name=f"initial-script-{project_id}",
            )
        message = (
            f"Projeto criado. A IA ja iniciou o roteiro de {duration:g} minutos."
            if generate_initial_script
            else "Projeto criado com briefing inicial."
        )
        ui.notify(message, color="positive")
        destination = (
            f"/projects/{project_id}/script" if generate_initial_script else f"/projects/{project_id}"
        )
        ui.navigate.to(destination)
    except Exception as exc:
        ui.notify(f"Nao foi possivel criar o projeto: {exc}", color="negative")


async def _create_project_from_chat_prompt(prompt: str) -> None:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        ui.notify("Descreva a ideia ou cole um roteiro antes de criar o projeto.", color="warning")
        return
    form = {
        "title": _compact_project_title(cleaned_prompt),
        "description": cleaned_prompt[:240],
        "theme": cleaned_prompt[:220],
        "audience": "publico geral",
        "genre": "drama emocional",
        "emotion": "curiosidade",
        "intensity": 8,
        "ending": "final com revelacao afetiva",
        "duration": DEFAULT_STORY_DURATION_MINUTES,
        "visual_style": "cinematico realista vertical",
        "objective": (
            f"reter audiencia com uma historia completa de "
            f"{DEFAULT_STORY_DURATION_MINUTES:g} minutos"
        ),
        "cta": "",
        "constraints": "evitar violencia grafica\nmanter tom familiar",
        "one_line_idea": cleaned_prompt,
        "content_type": "short_drama",
        "aspect_ratio": "9:16",
        "workflow_mode": "keyframes_i2v",
        "image_resolution": "1080x1920",
        "video_resolution": "1080x1920",
        "motion_intensity": 5,
        "image_model": get_settings().openrouter_image_model,
        "video_model": get_settings().openrouter_video_model,
    }
    await _create_project_from_form(form, generate_initial_script=True)


async def _create_project_from_idea(idea: dict[str, Any]) -> None:
    title = str(idea.get("title") or "Ideia de storytelling").strip()
    theme = str(idea.get("theme") or idea.get("premise") or title).strip()
    premise = str(idea.get("premise") or idea.get("hook") or theme).strip()
    genre = str(idea.get("genre") or "drama emocional").strip()
    emotion = str(idea.get("primary_emotion") or idea.get("final_emotion") or "curiosidade").strip()
    duration = coerce_duration_minutes(idea.get("duration_minutes"), DEFAULT_STORY_DURATION_MINUTES)
    form = {
        "title": title[:80] or "Novo projeto de storytelling",
        "description": premise[:240],
        "theme": theme[:220],
        "audience": "publico geral",
        "genre": genre,
        "emotion": emotion,
        "intensity": 8,
        "ending": "final com payoff emocional",
        "duration": duration,
        "visual_style": "cinematico realista vertical",
        "objective": f"desenvolver uma historia completa de {duration:g} minutos",
        "cta": "",
        "constraints": (
            "manter ritmo forte\n"
            "criar ganchos claros\n"
            f"adequar para {duration:g} minutos"
        ),
        "one_line_idea": _format_idea_payload_for_project(idea),
        "source_idea_payload": dict(idea),
        "content_type": "short_drama",
        "aspect_ratio": "9:16",
        "workflow_mode": "keyframes_i2v",
        "image_resolution": "1080x1920",
        "video_resolution": "1080x1920",
        "motion_intensity": 5,
        "image_model": get_settings().openrouter_image_model,
        "video_model": get_settings().openrouter_video_model,
    }
    await _create_project_from_form(form, generate_initial_script=True, source_idea=idea)


async def _rename_project_from_ui(project_id: UUID, title: str, redirect_to: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await rename_project(session, project_id, title)
        if project is None:
            ui.notify("Projeto não encontrado.", color="negative")
            return
        ui.notify("Projeto renomeado.", color="positive")
        ui.navigate.to(redirect_to)
    except Exception as exc:
        ui.notify(f"Não foi possível renomear o projeto: {exc}", color="negative")


async def _delete_project_from_ui(project_id: UUID, redirect_to: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            deleted = await delete_project(session, project_id)
        if not deleted:
            ui.notify("Projeto não encontrado.", color="negative")
            return
        ui.notify("Projeto excluído.", color="positive")
        ui.navigate.to(redirect_to)
    except Exception as exc:
        ui.notify(f"Não foi possível excluir o projeto: {exc}", color="negative")


async def _delete_all_projects_from_ui() -> None:
    try:
        async with AsyncSessionLocal() as session:
            deleted_count = await delete_all_projects(session)
        ui.notify(f"{deleted_count} projeto(s) apagado(s).", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao foi possivel apagar os projetos: {exc}", color="negative")


def _delete_all_ideas_from_ui() -> None:
    try:
        deleted_count = delete_all_ideas()
        ui.notify(f"{deleted_count} ideia(s) apagada(s).", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao foi possivel apagar as ideias: {exc}", color="negative")


async def _save_model_setting(
    project_id: UUID, task: str, provider: str | None, model: str | None
) -> None:
    try:
        if not provider or not model:
            raise ValueError("informe provider e modelo")
        async with AsyncSessionLocal() as session:
            await set_model_setting(session, project_id, task, provider, model)
        ui.notify("Modelo salvo para esta etapa.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao foi possivel salvar modelo: {exc}", color="negative")


async def _save_production_setup(project_id: UUID, payload: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await update_production_settings(session, project_id, payload)
        ui.notify("Core Setup salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao foi possivel salvar Core Setup: {exc}", color="negative")


async def _create_next_episode(project_id: UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await ProjectRepository(session).get_project(project_id)
            briefing = await _latest(session, Briefing, project_id)
            settings = await get_or_create_production_settings(session, project_id)
            if project is None or briefing is None:
                raise ValueError("projeto sem briefing base")
            next_project = await create_project(
                session,
                ProjectCreate(
                    title=f"{project.title} - Episodio {settings.episode_number + 1}",
                    description="Continuidade episodica herdada do projeto anterior.",
                ),
            )
            await update_production_settings(
                session,
                next_project.id,
                {
                    "parent_project_id": project.id,
                    "episode_number": settings.episode_number + 1,
                    "content_type": settings.content_type,
                    "aspect_ratio": settings.aspect_ratio,
                    "image_resolution": settings.image_resolution,
                    "video_resolution": settings.video_resolution,
                    "workflow_mode": settings.workflow_mode,
                    "image_model": settings.image_model,
                    "video_model": settings.video_model,
                    "audio_mode": settings.audio_mode,
                    "motion_intensity": settings.motion_intensity,
                    "metadata_json": {
                        "inherits_from_project_id": str(project.id),
                        "one_line_idea": (
                            f"Continuar a historia de {project.title}, mantendo "
                            "personagens, tom emocional e conflitos em aberto."
                        ),
                    },
                },
            )
            await create_briefing(
                session,
                next_project.id,
                BriefingCreate(
                    theme=briefing.theme,
                    audience=briefing.audience,
                    genre=briefing.genre,
                    primary_emotion=briefing.primary_emotion,
                    emotional_intensity=briefing.emotional_intensity,
                    ending_type="continuidade episodica com novo gancho",
                    language=briefing.language,
                    country_context=briefing.country_context,
                    desired_duration_minutes=briefing.desired_duration_minutes,
                    has_narrator=briefing.has_narrator,
                    visual_style=briefing.visual_style,
                    content_objective=briefing.content_objective,
                    call_to_action=briefing.call_to_action,
                    constraints=briefing.constraints,
                ),
            )
            await ensure_default_model_settings(session, next_project.id)
        ui.notify("Proximo episodio criado.", color="positive")
        ui.navigate.to(f"/projects/{next_project.id}")
    except Exception as exc:
        ui.notify(f"Nao foi possivel criar proximo episodio: {exc}", color="negative")


async def _run_step(project_id: UUID, step_key: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            if step_key == "ideas":
                await generate_story_ideas(session, project_id)
            elif step_key == "bible":
                idea = await _latest(session, StoryIdea, project_id)
                if idea is None:
                    raise ValueError("gere ideias primeiro")
                await generate_story_bible(session, project_id, idea.id)
            elif step_key == "script":
                bible = await _latest(session, StoryBible, project_id)
                if bible is None:
                    raise ValueError("gere a Story Bible primeiro")
                script = await generate_script(session, project_id, bible.id)
                if script is None:
                    raise ValueError("nao foi possivel gerar roteiro")
                await generate_scenes_and_shots(session, project_id, script.id)
            elif step_key == "visual":
                bible = await _latest(session, StoryBible, project_id)
                if bible is None:
                    raise ValueError("gere a Story Bible primeiro")
                await generate_visual_bible(session, project_id, bible.id)
                character = await _latest(session, Character, project_id)
                location = await _latest(session, Location, project_id)
                prop = await _latest(session, Prop, project_id)
                if character is not None:
                    await generate_visual_references(
                        session, project_id, "character", character.id, ["front_portrait"]
                    )
                if location is not None:
                    await generate_visual_references(
                        session, project_id, "location", location.id, ["establishing"]
                    )
                if prop is not None:
                    await generate_visual_references(
                        session, project_id, "prop", prop.id, ["front"]
                    )
            elif step_key == "storyboard":
                script = await _latest(session, Script, project_id)
                if script is None:
                    raise ValueError("gere o roteiro primeiro")
                await generate_storyboard_frames(session, project_id, script.id)
                await generate_animatic_bundle(session, project_id, script.id)
            elif step_key == "video":
                result = await session.execute(
                    select(StoryboardFrame)
                    .where(StoryboardFrame.project_id == project_id)
                    .order_by(StoryboardFrame.frame_number)
                )
                frames = list(result.scalars())
                if not frames:
                    raise ValueError("gere o storyboard primeiro")
                await generate_video_clips(
                    session,
                    project_id,
                    frame_ids=[frame.id for frame in frames[:3]],
                    variants_per_frame=1,
                )
            elif step_key == "finalization":
                source_audio = await _latest(session, AudioTrack, project_id)
                if source_audio is None:
                    raise ValueError("gere o animatic primeiro")
                final_audio = await synthesize_narration(
                    session, project_id, source_audio.id, "pt-br-warm-narrator"
                )
                if final_audio is None:
                    raise ValueError("nao foi possivel gerar narracao")
                subtitle = await generate_subtitles(session, project_id, final_audio.id)
                animatic = await _latest(session, Animatic, project_id)
                timeline = await create_final_timeline(
                    session, project_id, animatic.id if animatic else None
                )
                if timeline is None:
                    raise ValueError("gere clipes de video primeiro")
                await export_timeline(
                    session,
                    project_id,
                    timeline.id,
                    subtitle.id if subtitle else None,
                )
            elif step_key == "quality":
                await run_quality_check(session, project_id)
            else:
                raise ValueError("etapa sem acao automatica")
        ui.notify("Etapa executada com sucesso.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Acao interrompida: {exc}", color="warning")


def _render_step_card(project_id: UUID, step: ProductionStep, counts: dict[str, int]) -> None:
    ready = _step_ready(step.key, counts)
    status_text = "pronto" if ready else "pendente"
    status_classes = (
        "bg-emerald-950 text-emerald-200 border border-emerald-800"
        if ready
        else "bg-slate-800 text-slate-300 border border-slate-700"
    )
    with ui.card().classes(_card_classes("min-h-48")):
        with ui.row().classes("items-start justify-between w-full"):
            ui.icon(step.icon).classes("text-2xl text-cyan-300")
            ui.label(status_text).classes(f"text-xs px-2 py-1 rounded-md {status_classes}")
        ui.label(step.title).classes("text-lg font-semibold")
        ui.label(step.description).classes("text-sm text-slate-400 min-h-10")
        if step.key == "briefing":
            ui.button(
                "Criar via chat",
                icon="chat_bubble_outline",
                on_click=lambda: ui.navigate.to("/dashboard"),
            ).classes(_button_classes())
        else:
            ui.button(
                step.action_label,
                icon="play_arrow",
                on_click=lambda key=step.key: _run_step(project_id, key),
            ).classes(_button_classes())


def _render_model_settings(project_id: UUID, settings_list: list[ProjectModelSetting]) -> None:
    settings_by_task = {item.task: item for item in settings_list}
    app_settings = get_settings()
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("hub").classes("text-cyan-300")
            ui.label("Modelos de IA por etapa").classes("text-lg font-semibold")
        if app_settings.openrouter_api_key:
            ui.label("OpenRouter configurado").classes(
                "text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-200 "
                "border border-emerald-800"
            )
        else:
            ui.label("OPENROUTER_API_KEY ausente: etapas OpenRouter caem para mock").classes(
                "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 border border-amber-800"
            )
        _muted(
            "Use mock para trabalhar sem custo ou OpenRouter para chamar modelos reais. "
            "Informe slugs como openai/gpt-4o-mini, anthropic/claude-3.5-sonnet "
            "ou google/gemini-flash-1.5."
        )
        for task in NARRATIVE_TASKS:
            setting = settings_by_task.get(task)
            provider_value = setting.provider if setting else "mock"
            model_value = setting.model if setting else "mock-llm"
            with ui.row().classes("w-full items-end gap-2"):
                ui.label(TASK_LABELS[task]).classes("w-28 text-sm text-slate-300")
                provider_select = ui.select(
                    ["mock", "openrouter"],
                    label="Provider",
                    value=provider_value,
                ).classes("w-36")
                model_input = ui.input("Modelo", value=model_value).classes("flex-1")
                ui.button(
                    "Salvar",
                    icon="save",
                    on_click=(
                        lambda task=task, provider_select=provider_select, model_input=model_input: (
                            _save_model_setting(
                                project_id,
                                task,
                                provider_select.value,
                                model_input.value,
                            )
                        )
                    ),
                ).classes("bg-slate-800 hover:bg-slate-700 rounded-md")


def _render_director_cockpit(settings: ProjectProductionSettings, counts: dict[str, int]) -> None:
    flow = [
        ("Script", counts["scripts"]),
        ("Assets", counts["characters"] + counts["visual_refs"]),
        ("Storyboard", counts["frames"]),
        ("Video", counts["clips"]),
        ("Timeline", counts["exports"]),
    ]
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("smart_toy").classes("text-cyan-300 text-2xl")
                ui.label("AI Director Cockpit").classes("text-xl font-semibold")
            ui.label(f"Episodio {settings.episode_number}").classes(
                "text-xs px-2 py-1 rounded-md bg-slate-800 text-slate-300"
            )
        _muted(
            "Fluxo integrado estilo estúdio: ideia, roteiro, ativos, storyboard, render, "
            "timeline e exportação sem trocar de ferramenta."
        )
        with ui.row().classes("w-full items-center gap-2"):
            for index, (label, value) in enumerate(flow):
                with ui.column().classes("items-center gap-1"):
                    ui.label(label).classes("text-sm font-semibold")
                    ui.label(str(value)).classes(
                        "w-10 h-10 rounded-full bg-cyan-950 text-cyan-100 "
                        "flex items-center justify-center font-mono border border-cyan-800"
                    )
                if index < len(flow) - 1:
                    ui.icon("arrow_forward").classes("text-slate-500")


def _render_core_setup(project_id: UUID, settings: ProjectProductionSettings) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("tune").classes("text-cyan-300")
            ui.label("Core Setup").classes("text-lg font-semibold")
        _muted("Configure formato, workflow e modelos antes de gerar clipes caros.")
        with ui.grid(columns=2).classes("w-full gap-3"):
            content_type = ui.select(
                CONTENT_TYPES,
                label="Tipo de conteudo",
                value=settings.content_type,
            )
            aspect_ratio = ui.select(
                ASPECT_RATIOS,
                label="Aspect ratio",
                value=settings.aspect_ratio,
            )
            image_resolution = ui.select(
                RESOLUTIONS,
                label="Imagem",
                value=settings.image_resolution,
            )
            video_resolution = ui.select(
                RESOLUTIONS,
                label="Video",
                value=settings.video_resolution,
            )
            workflow_mode = ui.select(
                WORKFLOW_MODES,
                label="Workflow",
                value=settings.workflow_mode,
            )
            motion_intensity = ui.number(
                "Movimento",
                value=settings.motion_intensity,
                min=1,
                max=10,
            )
            image_model = ui.input("Modelo de imagem", value=settings.image_model)
            video_model = ui.input("Modelo de video", value=settings.video_model)

        async def save() -> None:
            await _save_production_setup(
                project_id,
                {
                    "content_type": content_type.value,
                    "aspect_ratio": aspect_ratio.value,
                    "image_resolution": image_resolution.value,
                    "video_resolution": video_resolution.value,
                    "workflow_mode": workflow_mode.value,
                    "motion_intensity": int(motion_intensity.value or 5),
                    "image_model": image_model.value,
                    "video_model": video_model.value,
                },
            )

        ui.button("Salvar Core Setup", icon="save", on_click=save).classes(_button_classes())


def _render_asset_canvas(summary: dict[str, Any]) -> None:
    groups = [
        ("Personagens", summary["characters"], "person"),
        ("Cenarios", summary["locations"], "location_on"),
        ("Objetos", summary["props"], "category"),
        ("Referencias", summary["visual_refs"], "image"),
    ]
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("dashboard_customize").classes("text-cyan-300")
            ui.label("Asset Canvas").classes("text-lg font-semibold")
        _muted("Ativos reutilizaveis ficam centralizados para preservar consistencia visual.")
        with ui.grid(columns=4).classes("w-full gap-3"):
            for title, items, icon_name in groups:
                with ui.column().classes("gap-2"):
                    ui.label(title).classes("font-semibold")
                    if not items:
                        ui.label("vazio").classes("text-sm text-slate-500")
                    for item in items:
                        name = getattr(item, "name", getattr(item, "view_type", "item"))
                        with ui.card().classes(_card_classes("w-full p-3")):
                            ui.icon(icon_name).classes("text-cyan-300")
                            ui.label(str(name)).classes("text-sm font-semibold")


def _render_storyboard_grid(frames: list[StoryboardFrame]) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("grid_view").classes("text-cyan-300")
            ui.label("Storyboard Grid").classes("text-lg font-semibold")
        _muted("Revise a estrutura quadro a quadro antes de converter tudo em video.")
        if not frames:
            ui.label("Gere storyboards para preencher a grade.").classes("text-sm text-slate-500")
            return
        with ui.grid(columns=3).classes("w-full gap-3"):
            for frame in sorted(frames, key=lambda item: item.frame_number):
                with ui.card().classes(_card_classes("min-h-32")):
                    ui.label(f"Frame {frame.frame_number:03d}").classes("text-xs text-cyan-200")
                    ui.label(frame.narration_text[:120]).classes("text-sm text-slate-300")
                    ui.label(f"{frame.duration_seconds}s").classes("text-xs text-slate-500")


def _render_timeline_strip(timeline: Timeline | None, items: list[TimelineItem]) -> None:
    with ui.card().classes(_card_classes("w-full")):
        with ui.row().classes("items-center gap-2"):
            ui.icon("timeline").classes("text-cyan-300")
            ui.label("Timeline Assembly").classes("text-lg font-semibold")
        if timeline is None:
            ui.label("A timeline aparece depois do animatic ou da finalizacao.").classes(
                "text-sm text-slate-500"
            )
            return
        ui.label(f"{timeline.name} · {timeline.duration_seconds}s").classes(
            "text-sm text-slate-300"
        )
        with ui.row().classes("w-full gap-1 overflow-x-auto"):
            for item in items:
                width = max(44, min(160, (item.end_ms - item.start_ms) // 80))
                color = "bg-cyan-900" if item.layer == "video" else "bg-emerald-900"
                ui.label(item.layer).classes(
                    f"{color} text-xs text-slate-100 rounded px-2 py-3 text-center"
                ).style(f"width: {width}px")


def _studio_logo(compact: bool = False) -> None:
    with ui.row().classes("items-center gap-3"):
        ui.image(BRAND_MARK_URL).classes("w-9 h-9 rounded-xl object-cover")
        if not compact:
            ui.label("Storytelling").classes("brand-type text-xl font-extrabold")


def _theme_toggle() -> None:
    is_dark = get_settings().user_theme != "light"
    mode = ui.dark_mode(value=is_dark)
    button = ui.button(icon="light_mode" if is_dark else "dark_mode").props("flat round")

    def toggle_theme() -> None:
        next_dark = not bool(mode.value)
        mode.set_value(next_dark)
        save_preferences({"USER_THEME": "dark" if next_dark else "light"})
        button.props(f"icon={'light_mode' if next_dark else 'dark_mode'}")
        button.update()

    button.on("click", toggle_theme).tooltip("Alternar entre tema claro e escuro")


def _logout_button() -> None:
    ui.button(icon="logout").props("flat round").classes("text-[#aeb3ae]").on(
        "click",
        lambda: ui.run_javascript(
            "fetch('/auth/logout', {method: 'POST'}).then(() => window.location.href = '/login')"
        ),
    ).tooltip("Sair")


def _avatar_data_uri(path_value: str) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _save_avatar_file(filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix.lower()
    target_dir = Path("storage/profile")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"avatar{suffix}"
    target.write_bytes(content)
    return target


def _user_avatar(size: str = "44px", navigate: bool = True) -> Any:
    current = get_settings()
    image_source = _avatar_data_uri(current.user_avatar_path)
    initial = (current.user_display_name or "U").strip()[:1].upper()
    with ui.avatar(color="grey-9", size=size).classes(
        "cursor-pointer overflow-hidden ring-1 ring-[#3a3f3a]"
    ) as avatar:
        if image_source:
            ui.image(image_source).classes("w-full h-full object-cover").props("fit=cover")
        else:
            ui.label(initial)
    if navigate:
        avatar.on("click", lambda: ui.navigate.to("/settings"))
    return avatar


def _home_sidebar(active: str = "") -> None:
    with ui.column().classes(
        "desktop-nav fixed left-0 top-0 bottom-0 w-24 border-r border-[#222622] items-center py-6 gap-6 bg-[#0b0d0c] z-20"
    ):
        _studio_logo(compact=True)
        for key, icon, label, target in [
            ("ideas", "lightbulb_outline", "Ideias", "/"),
            ("create", "chat_bubble_outline", "Criar", "/dashboard"),
            ("projects", "folder_open", "Projetos", "/projects"),
            ("settings", "settings", "Ajustes", "/settings"),
        ]:
            active_classes = "acid" if key == active else "text-[#8d928e]"
            with (
                ui.column()
                .classes(
                    "items-center gap-1 cursor-pointer rounded-xl px-3 py-2 "
                    f"{active_classes} hover:text-white"
                )
                .on("click", lambda t=target: ui.navigate.to(t))
            ):
                ui.icon(icon).classes("text-2xl")
                ui.label(label).classes("text-[11px]")
        ui.space()
        with ui.element("div").classes("mb-2"):
            _user_avatar(size="48px")
        _logout_button()


def _workspace_header(project: Project, active: str, counts: dict[str, int]) -> None:
    tabs = [
        ("Roteiro", "script"),
        ("Personagens", "assets"),
        ("Storyboard", "storyboard"),
        ("Vídeo", "video"),
    ]
    with ui.row().classes(
        "sticky top-0 z-30 w-full h-16 px-5 items-center border-b border-[#242824] bg-[#090b0a] gap-5"
    ):
        _studio_logo(compact=True)
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
            "flat round"
        ).classes("text-[#9da29d]")
        with ui.column().classes("gap-0 min-w-40"):
            ui.label(project.title).classes("font-semibold truncate max-w-56")
        ui.label("Episódio 1").classes("text-[11px] text-[#818681]")
        if counts.get("stale_artifacts", 0):
            ui.badge(f"{counts['stale_artifacts']} desatualizado(s)").classes(
                "bg-amber-900 text-amber-100"
            ).tooltip("Alguns artefatos derivados precisam ser regenerados.")
        with ui.row().classes("desktop-nav flex-1 justify-center gap-2"):
            for label, key in tabs:
                allowed, reason = _workspace_section_access(key, counts)
                button = ui.button(
                    label,
                    icon=None if allowed else "lock",
                    on_click=lambda k=key: ui.navigate.to(f"/projects/{project.id}/{k}"),
                ).props("flat no-caps" if allowed else "flat no-caps disable").classes(
                    f"nav-pill rounded-full px-4 {'nav-active' if active == key else ''} "
                    f"{'nav-locked cursor-not-allowed' if not allowed else ''}"
                )
                if not allowed:
                    button.tooltip(reason)
        ui.label("PT-BR").classes("desktop-nav text-sm text-[#a9aea9]")
        _theme_toggle()
        ui.button("Exportar", icon="ios_share").props("unelevated no-caps").classes(
            "acid-bg rounded-xl font-semibold"
        )


def _assistant_initial_message(active: str, assistant_suggestions: dict[str, str]) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": (
            "Estou acompanhando esta etapa. Posso revisar, propor variações "
            "e orientar a próxima ação mantendo a continuidade do projeto.\n\n"
            f"{assistant_suggestions.get(active, '')}"
        ),
    }


def _assistant_chat_store() -> dict[str, list[dict[str, str]]]:
    raw_store = nicegui_app.storage.user.get("project_assistant_messages")
    if not isinstance(raw_store, dict):
        raw_store = {}
    return cast(dict[str, list[dict[str, str]]], raw_store)


def _is_legacy_assistant_greeting(role: str, content: str) -> bool:
    return role == "assistant" and content.startswith("Estou acompanhando esta etapa.")


def _load_assistant_messages(
    project_id: UUID, active: str, assistant_suggestions: dict[str, str]
) -> list[dict[str, str]]:
    store = _assistant_chat_store()
    raw_messages = store.get(str(project_id), [])
    messages: list[dict[str, str]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "assistant_pending":
            continue
        if _is_legacy_assistant_greeting(role, content):
            continue
        if role and content:
            messages.append({"role": role, "content": content})
    _ = active, assistant_suggestions
    store[str(project_id)] = messages
    nicegui_app.storage.user["project_assistant_messages"] = store
    return messages


def _save_assistant_messages(project_id: UUID, messages: list[dict[str, str]]) -> None:
    store = _assistant_chat_store()
    store[str(project_id)] = [
        item for item in messages[-80:] if item["role"] != "assistant_pending"
    ]
    nicegui_app.storage.user["project_assistant_messages"] = store


def _assistant_panel(project_id: UUID, active: str, summary: dict[str, Any]) -> None:
    prompts = {
        "script": "Peça ajustes de tom, diálogo ou estrutura.",
        "assets": "Descreva um personagem, local ou objeto.",
        "storyboard": "Diga ao diretor o que enquadrar.",
        "video": "Descreva movimento, câmera ou ritmo.",
    }
    assistant_suggestions = {
        "script": (
            "Sugestões que posso ajudar agora: revisar a estrutura do roteiro, "
            "fortalecer o gancho inicial ou ajustar diálogos."
        ),
        "assets": (
            "Sugestões que posso ajudar agora: criar personagens, locais e objetos "
            "a partir do roteiro, aprofundar perfis visuais ou gerar variações "
            "mantendo a continuidade do projeto."
        ),
        "storyboard": (
            "Sugestões que posso ajudar agora: criar o storyboard a partir do roteiro, "
            "melhorar enquadramentos, ajustar ritmo visual ou revisar continuidade entre cenas."
        ),
        "video": (
            "Sugestões que posso ajudar agora: criar clipes a partir do storyboard, "
            "orientar movimento de câmera, ajustar ritmo ou propor variações de montagem."
        ),
    }
    messages = _load_assistant_messages(project_id, active, assistant_suggestions)
    with ui.column().classes(
        "right-assistant w-[340px] min-w-[340px] border-l border-[#252925] "
        "bg-[#0d0f0e] h-[calc(100vh-64px)] min-h-0 p-4 gap-4 sticky top-16"
    ):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("auto_awesome").classes("acid")
                ui.label("Diretor IA").classes("font-semibold")
            ui.badge("online").classes("bg-[#26301f] text-white")

        @ui.refreshable
        def conversation() -> None:
            with ui.column().classes("w-full gap-3"):
                for item in messages:
                    sent = item["role"] == "user"
                    pending = item["role"] == "assistant_pending"
                    with ui.row().classes(f"w-full {'justify-end' if sent else 'justify-start'}"):
                        if pending:
                            with ui.row().classes(
                                "assistant-chat-bubble glass text-[#c8ccc8] rounded-2xl "
                                "rounded-bl-sm px-4 py-3 text-sm leading-5 max-w-full "
                                "items-center gap-2"
                            ):
                                ui.spinner("dots", size="sm", color="primary")
                                ui.label(item["content"])
                        else:
                            ui.label(item["content"]).classes(
                                "assistant-chat-bubble w-fit rounded-2xl px-4 py-3 text-sm leading-5 "
                                + ("max-w-[88%] " if sent else "max-w-full ")
                                + (
                                    "acid-bg rounded-br-sm"
                                    if sent
                                    else "glass text-[#c8ccc8] rounded-bl-sm"
                                )
                            )

        with ui.column().classes(
            "assistant-chat-messages w-full flex-1 min-h-0 overflow-y-auto pr-1"
        ):
            conversation()

        async def send_message(text: str | None = None) -> None:
            user_message = (text or prompt.value or "").strip()
            if not user_message:
                return
            messages.append({"role": "user", "content": user_message})
            pending_message = {
                "role": "assistant_pending",
                "content": "Diretor IA esta buscando a melhor resposta...",
            }
            messages.append(pending_message)
            _save_assistant_messages(project_id, messages)
            prompt.value = ""
            conversation.refresh()
            should_reload = False
            try:
                async with AsyncSessionLocal() as session:
                    result = await handle_project_chat(
                        session,
                        project_id,
                        active,
                        user_message,
                        [item for item in messages if item["role"] != "assistant_pending"],
                    )
                    response = result.message
                    should_reload = result.changed
            except Exception as exc:
                response = f"Não consegui responder agora ({type(exc).__name__}). Tente novamente."
            if pending_message in messages:
                messages.remove(pending_message)
            messages.append({"role": "assistant", "content": response})
            _save_assistant_messages(project_id, messages)
            conversation.refresh()
            if should_reload:
                ui.notify(response, color="positive")
                ui.navigate.reload()

        with ui.row().classes("w-full items-end gap-2 shrink-0"):
            prompt = (
                ui.textarea(placeholder=prompts[active])
                .props("outlined dense autogrow rows=1")
                .classes("flex-1 assistant-chat-input")
            )
            prompt.on(
                "keydown",
                lambda: send_message(),
                js_handler="""(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        emit();
                    }
                }""",
            )
            ui.button(
                icon="arrow_upward",
                on_click=send_message,
            ).props("round unelevated").classes("acid-bg shrink-0 mb-1")


def _section_title(title: str, subtitle: str, action: str | None, callback: Any | None) -> None:
    with ui.row().classes("w-full items-end justify-between mb-2"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("brand-type text-3xl font-bold")
            ui.label(subtitle).classes("text-sm text-[#8e948f]")
        if action and callback:
            ui.button(action, icon="auto_awesome", on_click=callback).props(
                "unelevated no-caps"
            ).classes("acid-bg rounded-xl font-semibold")


def _project_ai_action(summary: dict[str, Any]) -> dict[str, Any]:
    settings = summary.get("production_settings")
    metadata = getattr(settings, "metadata_json", {}) or {}
    action = metadata.get("ai_action")
    return action if isinstance(action, dict) else {}


def _ordered_scenes(scenes: list[Any]) -> list[Any]:
    return sorted(scenes, key=lambda scene: int(getattr(scene, "scene_number", 0) or 0))


def _render_script_area(project_id: UUID, summary: dict[str, Any]) -> None:
    script = summary["script"]
    ai_action = _project_ai_action(summary)
    ai_status = str(ai_action.get("status") or "")
    ai_action_name = str(ai_action.get("action") or "")
    missing_scenes = script is not None and not summary["scenes"]
    scene_generation_failed = ai_action_name == "create_script_scenes" and ai_status == "failed"
    should_recover_missing_scenes = (
        missing_scenes and ai_status not in {"queued", "running"} and not scene_generation_failed
    )
    if should_recover_missing_scenes:
        background_tasks.create(
            _generate_missing_scenes_in_background(project_id, script.id),
            name=f"generate missing scenes {project_id}",
        )
    generation_in_progress = (
        ai_status in {"queued", "running"} or should_recover_missing_scenes
    )
    if generation_in_progress:
        ui.timer(5.0, lambda: _reload_project_when_script_ready(project_id))
    _section_title(
        "Roteiro",
        "Estruture a narrativa e transforme o texto em cenas e planos.",
        None,
        None,
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            if generation_in_progress:
                with ui.element("div").classes(
                    "entity-card rounded-2xl p-4 w-full flex items-center gap-3"
                ):
                    ui.spinner("dots", size="md", color="primary")
                    with ui.column().classes("gap-0"):
                        ui.label(
                            "IA criando cenas" if missing_scenes else "IA criando o roteiro"
                        ).classes("font-semibold")
                        ui.label(
                            "A IA esta criando cenas e planos para o roteiro."
                            if missing_scenes
                            else str(
                                ai_action.get("message")
                                or "A IA esta desenvolvendo o roteiro com base na ideia."
                            )
                        ).classes("text-sm text-[#858b86]")
            elif script is None and ai_status == "failed":
                with ui.element("div").classes(
                    "border border-red-900 bg-red-950/40 rounded-2xl p-4 text-red-100"
                ):
                    ui.label("A IA nao conseguiu criar o roteiro inicial.").classes(
                        "font-semibold"
                    )
                    ui.label(str(ai_action.get("error") or ai_action.get("message") or "")).classes(
                        "text-sm opacity-80"
                    )
            with ui.element("div").classes("entity-card rounded-2xl p-7 min-h-[520px] w-full"):
                ui.label(script.title if script else "Seu roteiro começa aqui").classes(
                    "brand-type text-2xl font-bold mb-5"
                )
                content = (
                    script.content
                    if script
                    else "A IA esta desenvolvendo o roteiro com base na ideia do projeto."
                )
                ui.label(content).classes("whitespace-pre-wrap leading-8 text-[#d9dcd9]")
        with ui.column().classes("w-64 gap-3"):
            ui.label("Cenas").classes("font-semibold")
            for scene in _ordered_scenes(summary["scenes"]):
                with ui.element("div").classes("entity-card rounded-xl p-3 w-full"):
                    ui.label(f"Cena {scene.scene_number}").classes("text-xs acid uppercase")
                    ui.label(scene.title).classes("font-medium")
                    ui.label(f"{scene.duration_seconds}s").classes("text-xs text-[#7f857f]")
            if not summary["scenes"]:
                ui.label("Nenhuma cena criada.").classes("text-sm text-[#777d78]")


def _entity_card(icon: str, title: str, subtitle: str, detail: str) -> None:
    with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
        with ui.element("div").classes("visual-placeholder h-44 p-5 flex items-end"):
            ui.icon(icon).classes("text-6xl text-[#eefa83]")
        with ui.column().classes("p-4 gap-2"):
            ui.label(title).classes("brand-type text-xl font-bold")
            ui.label(subtitle).classes("text-xs acid uppercase tracking-wide")
            ui.label(detail).classes("text-sm text-[#999f9a] line-clamp-2")
            with ui.row().classes("w-full pt-2 border-t border-[#292d29]"):
                ui.button("Editar", icon="edit").props("flat dense no-caps").classes(
                    "text-[#d8dbd8]"
                )
                ui.button("Variações", icon="refresh").props("flat dense no-caps").classes(
                    "text-[#d8dbd8]"
                )


def _render_assets_area(project_id: UUID, summary: dict[str, Any]) -> None:
    _section_title(
        "Biblioteca visual",
        "Personagens, locais e objetos canônicos do seu universo.",
        None,
        None,
    )
    with (
        ui.tabs()
        .classes("text-[#8d938e]")
        .props("no-caps active-color=primary indicator-color=primary") as tabs
    ):
        people = ui.tab("Personagens")
        places = ui.tab("Locais")
        props = ui.tab("Objetos")
    with ui.tab_panels(tabs, value=people).classes("w-full bg-transparent p-0"):
        for tab, items, kind in [
            (people, summary["characters"], "person"),
            (places, summary["locations"], "location_on"),
            (props, summary["props"], "category"),
        ]:
            with ui.tab_panel(tab).classes("px-0"):
                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
                    for item in items:
                        subtitle = (
                            getattr(item, "role", "Local")
                            if kind == "person"
                            else ("Objeto narrativo" if kind == "category" else "Cenário")
                        )
                        detail = (
                            getattr(item, "description", None)
                            or getattr(item, "narrative_importance", None)
                            or str(getattr(item, "canonical_profile", {}))[:150]
                        )
                        _entity_card(kind, item.name, subtitle, detail)
                    if not items:
                        with ui.element("div").classes("entity-card rounded-2xl p-8"):
                            ui.icon(kind).classes("text-4xl acid")
                            ui.label("Nada criado ainda").classes("text-lg font-semibold")
                            ui.label(
                                "O Diretor IA pode criar esta coleção a partir do roteiro."
                            ).classes("text-sm text-[#888e89]")


def _render_storyboard_area(project_id: UUID, summary: dict[str, Any]) -> None:
    _section_title(
        "Storyboard",
        "Planeje enquadramentos e ritmo antes de gerar os clipes.",
        None,
        None,
    )
    with ui.row().classes("w-full gap-3 mb-3"):
        for label, value in [
            ("Quadros", summary["counts"]["frames"]),
            ("Planos", summary["counts"]["shots"]),
            ("Duração", f"{sum(f.duration_seconds for f in summary['frames'])}s"),
        ]:
            with ui.element("div").classes("glass rounded-xl px-4 py-2"):
                ui.label(label).classes("text-[10px] uppercase text-[#777d78]")
                ui.label(str(value)).classes("text-lg font-bold")
    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
        for frame in sorted(summary["frames"], key=lambda f: f.frame_number):
            with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                with ui.element("div").classes(
                    "visual-placeholder aspect-video p-4 flex items-center justify-center"
                ):
                    ui.icon("photo_camera").classes("text-5xl text-[#bdc77b]")
                with ui.column().classes("p-4 gap-1"):
                    ui.label(f"PLANO {frame.frame_number:02d} · {frame.duration_seconds}s").classes(
                        "text-xs acid font-semibold"
                    )
                    ui.label(frame.prompt).classes("text-sm text-[#d1d4d1] line-clamp-3")
        if not summary["frames"]:
            ui.label(
                "O Diretor IA pode criar os quadros quando roteiro e ativos estiverem prontos."
            ).classes("text-[#858b86]")


def _render_video_area(project_id: UUID, summary: dict[str, Any]) -> None:
    _section_title(
        "Produção de vídeo",
        "Gere clipes, escolha variações e finalize sua montagem.",
        None,
        None,
    )
    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
        for i, clip in enumerate(summary["clips"], 1):
            with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                with ui.element("div").classes(
                    "visual-placeholder aspect-video flex items-center justify-center relative"
                ):
                    ui.button(icon="play_arrow").props("round unelevated").classes("acid-bg")
                with ui.column().classes("p-4 gap-2"):
                    with ui.row().classes("w-full justify-between"):
                        ui.label(f"Clipe {i:02d}").classes("font-semibold")
                        ui.badge("Selecionado" if clip.selected else "Variação").classes(
                            "bg-[#30362b] text-[#eaf878]"
                        )
                    ui.label(f"{clip.duration_seconds}s · {clip.model}").classes(
                        "text-xs text-[#878d88]"
                    )
        if not summary["clips"]:
            ui.label(
                "O Diretor IA pode criar os clipes quando o storyboard estiver pronto."
            ).classes("text-[#858b86]")
    ui.label("Timeline").classes("brand-type text-2xl font-bold mt-6")
    _render_timeline_strip(summary["timeline"], summary["timeline_items"])


def register_ui_pages() -> None:
    @ui.page("/dashboard", response_timeout=15)
    async def dashboard() -> None:
        _body_style()
        projects = await _project_cards()
        _home_sidebar("create")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full px-5 md:px-10 lg:px-14 py-6 gap-9"):
                with ui.row().classes(
                    "w-full max-w-6xl mx-auto items-center justify-between min-h-14"
                ):
                    _studio_logo()
                    with ui.row().classes("items-center gap-3"):
                        _theme_toggle()
                        _user_avatar(size="48px")
                with ui.column().classes("w-full max-w-4xl mx-auto items-center text-center gap-4"):
                    with ui.element("div").classes(
                        "chat-shell glass rounded-3xl p-4 w-full min-h-[240px] flex flex-col"
                    ):
                        idea = (
                            ui.textarea(
                                placeholder="Descreva sua história, cole um roteiro ou peça uma ideia..."
                            )
                            .props("borderless autogrow input-style='min-height:140px'")
                            .classes("w-full text-lg flex-1 text-left")
                        )
                        with ui.row().classes("w-full items-center px-2 pb-1 gap-2"):
                            ui.space()
                            ui.button(
                                icon="arrow_upward",
                                on_click=lambda: _create_project_from_chat_prompt(
                                    str(idea.value or "")
                                ),
                            ).props("round unelevated").classes("acid-bg")
                with (
                    ui.column().props("id=projects").classes("w-full max-w-6xl mx-auto gap-4 pt-3")
                ):
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.column().classes("gap-0"):
                            ui.label("Projetos recentes").classes(
                                "brand-type text-2xl md:text-3xl font-bold"
                            )
                            ui.label("Continue de onde parou ou comece uma nova produção.").classes(
                                "text-sm text-[#7f8580]"
                            )
                    if not projects:
                        with (
                            ui.element("div")
                            .classes(
                                "w-full border border-dashed border-[#363b36] rounded-2xl min-h-48 flex flex-col items-center justify-center cursor-pointer text-[#969c97] bg-[#0d100e]"
                            )
                            .on("click", lambda: ui.navigate.to("/dashboard"))
                        ):
                            ui.icon("add_circle_outline").classes("text-4xl acid")
                            ui.label("Crie seu primeiro projeto").classes(
                                "mt-3 text-lg font-semibold text-[#d7dbd7]"
                            )
                            ui.label(
                                "Sua história, personagens e storyboards aparecerão aqui."
                            ).classes("mt-1 text-sm text-[#747a75]")
                    else:
                        with ui.grid().classes(
                            "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                        ):
                            for project in projects:
                                _render_project_card(project, "/dashboard")
                            with (
                                ui.element("div")
                                .classes(
                                    "border border-dashed border-[#363b36] rounded-2xl min-h-52 flex flex-col items-center justify-center cursor-pointer text-[#969c97]"
                                )
                                .on("click", lambda: ui.navigate.to("/dashboard"))
                            ):
                                ui.icon("add_circle_outline").classes("text-4xl acid")
                                ui.label("Criar novo projeto").classes("mt-2 font-semibold")

    @ui.page("/projects", response_timeout=15)
    async def projects_page() -> None:
        _body_style()
        projects = await _project_cards()
        _home_sidebar("projects")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        ui.label("Projetos").classes("brand-type text-4xl font-bold")
                        ui.label("Acompanhe e continue suas produções de vídeo.").classes(
                            "text-[#8f9590]"
                        )
                    with ui.row().classes("items-center gap-2"):
                        _theme_toggle()
                        ui.button(
                            "Novo projeto",
                            icon="add",
                            on_click=lambda: ui.navigate.to("/dashboard"),
                        ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                if not projects:
                    with ui.element("div").classes(
                        "w-full border border-dashed border-[#363b36] rounded-2xl min-h-64 flex flex-col items-center justify-center text-[#969c97]"
                    ):
                        ui.icon("folder_open").classes("text-5xl")
                        ui.label("Nenhum projeto criado ainda.").classes(
                            "mt-3 text-lg font-semibold"
                        )
                        ui.button(
                            "Começar uma criação",
                            icon="auto_awesome",
                            on_click=lambda: ui.navigate.to("/dashboard"),
                        ).props("flat no-caps").classes("acid mt-2")
                else:
                    with ui.grid().classes(
                        "w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
                    ):
                        for project in projects:
                            _render_project_card(project, "/projects")

    @ui.page("/", response_timeout=15)
    @ui.page("/ideas", response_timeout=15)
    async def ideas_page() -> None:
        _body_style()
        _home_sidebar("ideas")
        ideas: list[dict[str, Any]] = load_generated_ideas()
        saved_ideas = load_saved_ideas()
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon("lightbulb").classes("text-4xl acid")
                            ui.label("Laboratório de Ideias").classes(
                                "brand-type text-4xl font-bold"
                            )
                        ui.label(
                            "Explore histórias livremente, sem criar um projeto de vídeo."
                        ).classes("text-[#8f9590]")
                    _theme_toggle()

                with ui.element("div").classes("hidden"):
                    _ = (
                        ui.textarea(
                            "Sobre o que você quer contar?",
                            placeholder="Ex.: uma astronauta encontra uma mensagem enviada por ela mesma...",
                        )
                        .props("outlined autogrow stack-label")
                        .classes("hidden")
                    )
                    with ui.grid().classes("hidden"):
                        _ = ui.select(
                            [
                                "Drama",
                                "Ficção científica",
                                "Suspense",
                                "Comédia",
                                "Terror",
                                "Romance",
                                "Documentário",
                            ],
                            label="Gênero",
                            value="Drama",
                        ).props("outlined")
                        _ = ui.select(
                            [
                                "Esperança",
                                "Curiosidade",
                                "Tensão",
                                "Alegria",
                                "Melancolia",
                                "Surpresa",
                            ],
                            label="Emoção principal",
                            value="Esperança",
                        ).props("outlined")

                    with ui.dialog().props(BLOCKING_DIALOG_PROPS) as loading_dialog, ui.card().classes(
                        "entity-card rounded-2xl p-6 min-w-80 items-center text-center"
                    ):
                        ui.spinner("dots", size="lg", color="primary")
                        ui.label("Gerando ideias").classes("brand-type text-xl font-bold mt-3")
                        ui.label("A IA esta criando temas, generos e emocoes.").classes(
                            "text-sm text-[#8f9590]"
                        )

                    async def generate() -> None:
                        loading_dialog.open()
                        try:
                            generated = await generate_freeform_ideas(
                                "",
                                count=10,
                                genre=str(genre_select.value or ""),
                                target_duration_minutes=coerce_duration_minutes(
                                    duration_select.value
                                ),
                            )
                            ideas.clear()
                            ideas.extend(replace_generated_ideas(generated))
                            idea_results.refresh()
                        except Exception as exc:
                            ui.notify(f"Não foi possível gerar ideias: {exc}", color="negative")
                        finally:
                            loading_dialog.close()

                with ui.column().classes("w-full items-center gap-4 py-8"):
                    with ui.row().classes("w-full max-w-2xl gap-3 items-end justify-center"):
                        genre_select = (
                            ui.select(IDEA_GENRES, label="Gênero", value=IDEA_GENRES[0])
                            .props("outlined")
                            .classes("flex-1 min-w-64")
                        )
                        duration_select = (
                            ui.select(
                                STORY_DURATION_OPTIONS,
                                label="Duração",
                                value=int(DEFAULT_STORY_DURATION_MINUTES),
                            )
                            .props("outlined suffix='min'")
                            .classes("w-36")
                        )
                    ui.button(
                        "Gerar 10 ideias",
                        icon="auto_awesome",
                        on_click=generate,
                    ).props("unelevated no-caps size=lg").classes(
                        "acid-bg rounded-2xl px-10 py-5 text-lg font-bold"
                    )

                def discard_generated(idea: dict[str, Any]) -> None:
                    if idea in ideas:
                        ideas.remove(idea)
                    delete_generated_idea(str(idea.get("id") or ""))
                    idea_results.refresh()

                def save_generated(idea: dict[str, Any]) -> None:
                    saved = save_idea(idea)
                    saved_ideas[:] = [
                        existing for existing in saved_ideas if existing.get("id") != saved["id"]
                    ]
                    saved_ideas.insert(0, saved)
                    if idea in ideas:
                        ideas.remove(idea)
                    delete_generated_idea(str(idea.get("id") or saved["id"]))
                    idea_results.refresh()
                    saved_results.refresh()
                    ui.notify("Ideia salva.", color="positive")

                def delete_saved(idea_id: str) -> None:
                    delete_saved_idea(idea_id)
                    saved_ideas[:] = [
                        idea for idea in saved_ideas if str(idea.get("id")) != idea_id
                    ]
                    saved_results.refresh()
                    ui.notify("Ideia descartada.", color="warning")

                @ui.refreshable
                def idea_results() -> None:
                    if not ideas:
                        with ui.element("div").classes(
                            "w-full border border-dashed border-[#343934] rounded-2xl min-h-52 flex flex-col items-center justify-center text-[#777d78]"
                        ):
                            ui.icon("tips_and_updates").classes("text-5xl")
                            ui.label("Suas ideias aparecerão aqui.").classes("mt-3")
                        return
                    with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-3 gap-4"):
                        for index, idea in enumerate(ideas, 1):
                            with ui.element("article").classes(
                                "entity-card rounded-2xl p-5 flex flex-col min-h-80"
                            ):
                                ui.label(f"IDEIA {index:02d}").classes(
                                    "text-xs acid font-semibold tracking-widest"
                                )
                                ui.label(str(idea.get("title") or "História sem título")).classes(
                                    "brand-type text-2xl font-bold mt-2"
                                )
                                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                                    ui.label(str(idea.get("genre") or "Genero sugerido")).classes(
                                        "idea-badge-genre rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        str(idea.get("primary_emotion") or "Emocao sugerida")
                                    ).classes(
                                        "idea-badge-emotion rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        f"{coerce_duration_minutes(idea.get('duration_minutes')):g} min"
                                    ).classes(
                                        "idea-badge-duration rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                if idea.get("theme"):
                                    ui.label(f"Tema: {idea['theme']}").classes(
                                        "text-xs text-[#9aa29b] mt-3"
                                    )
                                ui.label(str(idea.get("hook") or "")).classes(
                                    "text-sm text-[#d4d8d4] mt-3 font-medium"
                                )
                                ui.label(str(idea.get("premise") or "")).classes(
                                    "text-sm text-[#8d938e] mt-3 leading-6"
                                )
                                ui.space()
                                with ui.row().classes("gap-2 mt-4"):
                                    ui.button(
                                        "Salvar",
                                        icon="bookmark_add",
                                        on_click=lambda item=idea: save_generated(item),
                                    ).props("flat no-caps").classes("acid")
                                    ui.button(
                                        "Descartar",
                                        icon="close",
                                        on_click=lambda item=idea: discard_generated(item),
                                    ).props("flat no-caps").classes("text-[#aeb3ae]")
                                    ui.button(
                                        "Desenvolver",
                                        icon="arrow_forward",
                                        on_click=lambda item=idea: _create_project_from_idea(item),
                                    ).props("flat no-caps").classes("acid")

                idea_results()

                @ui.refreshable
                def saved_results() -> None:
                    ui.label("Ideias salvas").classes("brand-type text-2xl font-bold")
                    if not saved_ideas:
                        ui.label("Nenhuma ideia salva ainda.").classes("text-sm text-[#777d78]")
                        return
                    with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-3 gap-4"):
                        for index, idea in enumerate(saved_ideas, 1):
                            with ui.element("article").classes(
                                "entity-card rounded-2xl p-5 flex flex-col min-h-80"
                            ):
                                ui.label(f"SALVA {index:02d}").classes(
                                    "text-xs acid font-semibold tracking-widest"
                                )
                                ui.label(str(idea.get("title") or "Historia sem titulo")).classes(
                                    "brand-type text-2xl font-bold mt-2"
                                )
                                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                                    ui.label(str(idea.get("genre") or "Genero sugerido")).classes(
                                        "idea-badge-genre rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        str(idea.get("primary_emotion") or "Emocao sugerida")
                                    ).classes(
                                        "idea-badge-emotion rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                    ui.label(
                                        f"{coerce_duration_minutes(idea.get('duration_minutes')):g} min"
                                    ).classes(
                                        "idea-badge-duration rounded-md px-2 py-0.5 text-xs font-medium"
                                    )
                                if idea.get("theme"):
                                    ui.label(f"Tema: {idea['theme']}").classes(
                                        "text-xs text-[#9aa29b] mt-3"
                                    )
                                ui.label(str(idea.get("hook") or "")).classes(
                                    "text-sm text-[#d4d8d4] mt-3 font-medium"
                                )
                                ui.label(str(idea.get("premise") or "")).classes(
                                    "text-sm text-[#8d938e] mt-3 leading-6"
                                )
                                ui.space()
                                with ui.row().classes("gap-2 mt-4"):
                                    saved_idea_id = str(idea.get("id"))
                                    ui.button(
                                        "Descartar",
                                        icon="delete",
                                        on_click=lambda idea_id=saved_idea_id: delete_saved(idea_id),
                                    ).props("flat no-caps").classes("text-red-300")
                                    ui.button(
                                        "Desenvolver",
                                        icon="arrow_forward",
                                        on_click=lambda item=idea: _create_project_from_idea(item),
                                    ).props("flat no-caps").classes("acid")

                saved_results()

    @ui.page("/settings", response_timeout=15)
    async def settings_page() -> None:
        _body_style()
        current = get_settings()
        saved_idea_count = len(load_saved_ideas())
        generated_idea_count = len(load_generated_ideas())
        project_count = len(await _project_cards())
        _home_sidebar("settings")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        ui.label("Configurações").classes("brand-type text-4xl font-bold")
                        ui.label("Gerencie seu perfil e os modelos usados pelo estúdio.").classes(
                            "text-[#8f9590]"
                        )
                    _theme_toggle()

                with (
                    ui.tabs()
                    .classes("text-[#989e99]")
                    .props("no-caps active-color=primary indicator-color=primary") as settings_tabs
                ):
                    profile_tab = ui.tab("Perfil", icon="person")
                    ai_tab = ui.tab("Inteligência artificial", icon="auto_awesome")
                    data_tab = ui.tab("Dados", icon="delete_sweep")
                with ui.tab_panels(settings_tabs, value=profile_tab).classes(
                    "w-full bg-transparent p-0"
                ):
                    with ui.tab_panel(profile_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Dados do usuário").classes("text-xl font-semibold")
                            ui.label("Informações exibidas no seu espaço de trabalho.").classes(
                                "text-sm text-[#858b86] mb-4"
                            )

                            @ui.refreshable
                            def avatar_preview() -> None:
                                with ui.row().classes("items-center gap-4 mb-5"):
                                    photo_avatar = _user_avatar(size="80px", navigate=False)
                                    photo_avatar.on(
                                        "click",
                                        lambda: ui.run_javascript(
                                            "document.querySelector('#avatar-upload input[type=file]').click()"
                                        ),
                                    ).tooltip("Clique para alterar a foto")
                                    with ui.column().classes("gap-1"):
                                        ui.label("Foto do perfil").classes("font-semibold")
                                        ui.label("JPG, PNG ou WebP · máximo de 5 MB").classes(
                                            "text-xs text-[#7f8580]"
                                        )
                                        ui.label("Clique na foto para alterar").classes(
                                            "text-xs acid"
                                        )

                            avatar_preview()

                            async def upload_avatar(event: Any) -> None:
                                suffix = Path(event.file.name).suffix.lower()
                                if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                                    ui.notify("Formato de imagem não permitido.", color="negative")
                                    return
                                content = await event.file.read()
                                target = await asyncio.to_thread(
                                    _save_avatar_file, event.file.name, content
                                )
                                save_preferences({"USER_AVATAR_PATH": target.as_posix()})
                                avatar_preview.refresh()
                                ui.notify("Foto do perfil atualizada.", color="positive")

                            ui.upload(
                                label="Escolher foto",
                                on_upload=upload_avatar,
                                on_rejected=lambda: ui.notify(
                                    "A imagem deve ter no máximo 5 MB.", color="warning"
                                ),
                                auto_upload=True,
                                max_file_size=5_000_000,
                            ).props("id=avatar-upload accept=.jpg,.jpeg,.png,.webp").classes(
                                "hidden"
                            )

                            display_name = (
                                ui.input("Nome", value=current.user_display_name)
                                .props("outlined")
                                .classes("w-full")
                            )
                            email = (
                                ui.input("E-mail", value=current.user_email)
                                .props("outlined type=email")
                                .classes("w-full mt-3")
                            )

                            def save_profile() -> None:
                                save_preferences(
                                    {
                                        "USER_DISPLAY_NAME": display_name.value or "",
                                        "USER_EMAIL": email.value or "",
                                    }
                                )
                                ui.notify("Perfil salvo.", color="positive")

                            ui.button("Salvar perfil", icon="save", on_click=save_profile).props(
                                "unelevated no-caps"
                            ).classes("acid-bg rounded-xl mt-5")
                    with ui.tab_panel(ai_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("OpenRouter").classes("text-xl font-semibold")
                            ui.label(
                                "Conecte sua conta e escolha modelos diferentes para cada mídia."
                            ).classes("text-sm text-[#858b86] mb-4")
                            api_key = (
                                ui.input(
                                    "Chave da API",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.openrouter_api_key
                                        else "sk-or-v1-..."
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full")
                            )
                            text_model = (
                                ui.input(
                                    "Modelo de texto",
                                    value=current.openrouter_default_model,
                                    placeholder="openai/gpt-4o-mini",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            image_model = (
                                ui.input(
                                    "Modelo de imagem",
                                    value=current.openrouter_image_model,
                                    placeholder="google/gemini-2.5-flash-image",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            video_model = (
                                ui.input(
                                    "Modelo de video",
                                    value=current.openrouter_video_model,
                                    placeholder="google/veo-3.1",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )

                            def save_ai() -> None:
                                values = {
                                    "OPENROUTER_DEFAULT_MODEL": text_model.value or "",
                                    "OPENROUTER_IMAGE_MODEL": image_model.value or "",
                                    "OPENROUTER_VIDEO_MODEL": video_model.value or "",
                                }
                                if api_key.value:
                                    values["OPENROUTER_API_KEY"] = api_key.value
                                save_preferences(values)
                                ui.notify("Configurações de IA salvas.", color="positive")

                            with ui.row().classes("mt-5 gap-3"):
                                ui.button(
                                    "Salvar configurações", icon="save", on_click=save_ai
                                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    with ui.tab_panel(data_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Gerenciamento de dados").classes("text-xl font-semibold")
                            ui.label(
                                "Ações destrutivas para limpar ideias e projetos do estúdio."
                            ).classes("text-sm text-[#858b86] mb-4")

                            def confirm_delete_ideas() -> None:
                                ideas_dialog.close()
                                _delete_all_ideas_from_ui()

                            async def confirm_delete_projects() -> None:
                                projects_dialog.close()
                                await _delete_all_projects_from_ui()

                            with ui.dialog() as ideas_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Apagar todas as ideias?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove ideias salvas e ideias geradas na página "
                                    "de ideias. Projetos já criados não serão apagados."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=ideas_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar ideias",
                                        icon="delete",
                                        on_click=confirm_delete_ideas,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with ui.dialog() as projects_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Apagar todos os projetos?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove todos os projetos da lista principal. "
                                    "Ideias salvas na página de ideias não serão apagadas."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=projects_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar projetos",
                                        icon="delete_forever",
                                        on_click=confirm_delete_projects,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with ui.column().classes("w-full gap-3"):
                                with ui.element("div").classes(
                                    "border border-[#343934] rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Ideias").classes("font-semibold")
                                        ui.label(
                                            f"{saved_idea_count} salva(s) e "
                                            f"{generated_idea_count} gerada(s)."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todas as ideias",
                                        icon="delete_sweep",
                                        on_click=ideas_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

                                with ui.element("div").classes(
                                    "border border-[#343934] rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos").classes("font-semibold")
                                        ui.label(
                                            f"{project_count} projeto(s) ativo(s) no estúdio."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todos os projetos",
                                        icon="delete_forever",
                                        on_click=projects_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

    @ui.page("/projects/{project_id}", response_timeout=15)
    async def project_workspace(project_id: str) -> None:
        ui.navigate.to(f"/projects/{project_id}/script")
        return

    @ui.page("/projects/{project_id}/{section}", response_timeout=15)
    async def project_studio(project_id: str, section: str) -> None:
        _body_style()
        if section not in {"script", "assets", "storyboard", "video"}:
            ui.navigate.to(f"/projects/{project_id}/script")
            return
        try:
            project_uuid = UUID(project_id)
            summary = await _project_summary(project_uuid)
        except (ValueError, TypeError):
            summary = None
        if summary is None:
            with ui.column().classes("w-full min-h-screen items-center justify-center gap-4"):
                ui.icon("movie_off").classes("text-6xl acid")
                ui.label("Projeto não encontrado").classes("brand-type text-3xl font-bold")
                ui.button("Voltar ao início", on_click=lambda: ui.navigate.to("/")).classes(
                    "acid-bg"
                )
            return
        project: Project = summary["project"]
        counts: dict[str, int] = summary["counts"]
        allowed, reason = _workspace_section_access(section, counts)
        if not allowed:
            fallback = _first_available_workspace_section(counts)
            ui.notify(reason, color="warning")
            ui.navigate.to(f"/projects/{project_id}/{fallback}")
            return
        _workspace_header(project, section, counts)
        with ui.row().classes("w-full items-start flex-nowrap"):
            with ui.column().classes(
                "workspace-main flex-1 min-w-0 p-8 lg:p-10 gap-4 h-[calc(100vh-64px)] overflow-y-auto"
            ):
                if section == "script":
                    _render_script_area(project_uuid, summary)
                elif section == "assets":
                    _render_assets_area(project_uuid, summary)
                elif section == "storyboard":
                    _render_storyboard_area(project_uuid, summary)
                else:
                    _render_video_area(project_uuid, summary)
            _assistant_panel(project_uuid, section, summary)
