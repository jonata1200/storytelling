# ruff: noqa: E501

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from nicegui import ui
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.costs.models import CostEntry
from app.database.session import AsyncSessionLocal
from app.finalization.models import Export, SubtitleTrack
from app.finalization.service import (
    create_final_timeline,
    export_timeline,
    generate_subtitles,
    synthesize_narration,
)
from app.generation.director_agent import ask_director_agent
from app.generation.model_settings import (
    NARRATIVE_TASKS,
    TASK_LABELS,
    ensure_default_model_settings,
    set_model_setting,
)
from app.generation.models import ProjectModelSetting
from app.production.models import ProjectProductionSettings
from app.production.service import (
    ASPECT_RATIOS,
    CONTENT_TYPES,
    RESOLUTIONS,
    WORKFLOW_MODES,
    get_or_create_production_settings,
    update_production_settings,
    workflow_mode_label,
)
from app.projects.models import Artifact, Project
from app.projects.schemas import ProjectCreate
from app.projects.service import create_project
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
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryBible, StoryIdea
from app.storytelling.schemas import BriefingCreate
from app.storytelling.service import (
    create_briefing,
    generate_scenes_and_shots,
    generate_script,
    generate_story_bible,
    generate_story_ideas,
)
from app.video_generation.models import GenerationJob, VideoClip
from app.video_generation.service import generate_video_clips
from app.visual_bible.models import Character, Location, Prop, VisualReference
from app.visual_bible.service import generate_visual_bible, generate_visual_references


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
    ui.query("body").classes("studio-body")
    ui.add_head_html(
        """
        <style>
          @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
          :root { --ink:#080a09; --panel:#111412; --line:#272c28; --acid:#eefb72; --muted:#969c97; }
          body.studio-body { background:var(--ink); color:#f4f5f2; font-family:'DM Sans',sans-serif; }
          .studio-body .nicegui-content { padding:0; }
          .brand-type { font-family:'Manrope',sans-serif; letter-spacing:-.04em; }
          .glass { background:rgba(17,20,18,.88); border:1px solid var(--line); }
          .acid { color:var(--acid); }
          .acid-bg { background:var(--acid)!important; color:#10120d!important; }
          .nav-pill { border:1px solid transparent; color:#8c918d; transition:.2s ease; }
          .nav-pill:hover { color:white; background:#171a18; }
          .nav-active { color:#111!important; background:var(--acid)!important; border-color:#fff!important; }
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
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Project).order_by(Project.created_at.desc()))
        return list(result.scalars())


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
        project = await session.get(Project, project_id)
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
        "script": counts["scripts"] > 0 and counts["shots"] > 0,
        "visual": counts["characters"] > 0,
        "storyboard": counts["frames"] > 0 and counts["animatics"] > 0,
        "video": counts["clips"] > 0,
        "finalization": counts["exports"] > 0,
        "quality": counts["qa_issues"] >= 0,
    }
    return readiness[step_key]


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
            ui.button("Projetos", icon="dashboard", on_click=lambda: ui.navigate.to("/")).classes(
                "bg-slate-800 hover:bg-slate-700 rounded-md"
            )
            ui.link("API docs", "/docs").classes(
                "text-slate-100 bg-slate-800 hover:bg-slate-700 px-3 py-2 rounded-md"
            )


async def _create_project_from_form(form: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as session:
            project = await create_project(
                session,
                ProjectCreate(title=form["title"], description=form["description"]),
            )
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
                    "metadata_json": {"one_line_idea": form["one_line_idea"]},
                },
            )
            briefing = BriefingCreate(
                theme=form["theme"],
                audience=form["audience"],
                genre=form["genre"],
                primary_emotion=form["emotion"],
                emotional_intensity=int(form["intensity"]),
                ending_type=form["ending"],
                desired_duration_minutes=Decimal(str(form["duration"])),
                visual_style=form["visual_style"],
                content_objective=form["objective"],
                call_to_action=form["cta"] or None,
                constraints=[
                    item.strip() for item in form["constraints"].splitlines() if item.strip()
                ],
            )
            await create_briefing(session, project.id, briefing)
        ui.notify("Projeto criado com briefing inicial.", color="positive")
        ui.navigate.to(f"/projects/{project.id}")
    except Exception as exc:
        ui.notify(f"Nao foi possivel criar o projeto: {exc}", color="negative")


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
            project = await session.get(Project, project_id)
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
                "Editar novo projeto",
                icon="add",
                on_click=lambda: ui.navigate.to("/new"),
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
        with ui.element("div").classes(
            "w-9 h-9 acid-bg rounded-xl flex items-center justify-center"
        ):
            ui.icon("movie_creation").classes("text-xl")
        if not compact:
            ui.label("FrameFlow").classes("brand-type text-xl font-extrabold")


def _home_sidebar() -> None:
    with ui.column().classes(
        "desktop-nav fixed left-0 top-0 bottom-0 w-24 border-r border-[#222622] items-center py-6 gap-6 bg-[#0b0d0c] z-20"
    ):
        _studio_logo(compact=True)
        for icon, label, target in [
            ("chat_bubble_outline", "Criar", "/"),
            ("folder_open", "Projetos", "/#projects"),
            ("collections_bookmark", "Ativos", "/#projects"),
        ]:
            with (
                ui.column()
                .classes("items-center gap-1 cursor-pointer text-[#8d928e] hover:text-white")
                .on("click", lambda t=target: ui.navigate.to(t))
            ):
                ui.icon(icon).classes("text-2xl")
                ui.label(label).classes("text-[11px]")
        ui.space()
        ui.avatar("J", color="grey-9").classes("mb-2")


def _workspace_header(project: Project, active: str) -> None:
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
        with ui.row().classes("desktop-nav flex-1 justify-center gap-2"):
            for label, key in tabs:
                ui.button(
                    label, on_click=lambda k=key: ui.navigate.to(f"/projects/{project.id}/{k}")
                ).props("flat no-caps").classes(
                    f"nav-pill rounded-full px-4 {'nav-active' if active == key else ''}"
                )
        ui.label("PT-BR").classes("desktop-nav text-sm text-[#a9aea9]")
        ui.button("Exportar", icon="ios_share").props("unelevated no-caps").classes(
            "acid-bg rounded-xl font-semibold"
        )


def _assistant_panel(project_id: UUID, active: str, summary: dict[str, Any]) -> None:
    prompts = {
        "script": "Peça ajustes de tom, diálogo ou estrutura.",
        "assets": "Descreva um personagem, local ou objeto.",
        "storyboard": "Diga ao diretor o que enquadrar.",
        "video": "Descreva movimento, câmera ou ritmo.",
    }
    messages: list[dict[str, str]] = [
        {
            "role": "assistant",
            "content": (
                "Estou acompanhando esta etapa. Posso revisar, propor variações "
                "e orientar a próxima ação mantendo a continuidade do projeto."
            ),
        }
    ]
    context = {
        "project": summary["project"].title,
        "section": active,
        "summary": (
            f"{summary['counts']['scripts']} roteiro(s), "
            f"{summary['counts']['characters']} personagem(ns), "
            f"{summary['counts']['frames']} quadro(s) e "
            f"{summary['counts']['clips']} clipe(s)"
        ),
    }

    with ui.column().classes(
        "right-assistant w-[340px] min-w-[340px] border-l border-[#252925] bg-[#0d0f0e] h-[calc(100vh-64px)] p-4 gap-4 sticky top-16"
    ):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("auto_awesome").classes("acid")
                ui.label("Diretor IA").classes("font-semibold")
            ui.badge("online").classes("bg-[#26301f] text-[#dff57b]")

        @ui.refreshable
        def conversation() -> None:
            with ui.column().classes("w-full gap-3 overflow-y-auto flex-1"):
                for item in messages:
                    sent = item["role"] == "user"
                    with ui.row().classes(f"w-full {'justify-end' if sent else 'justify-start'}"):
                        ui.label(item["content"]).classes(
                            "max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-5 "
                            + (
                                "acid-bg rounded-br-sm"
                                if sent
                                else "glass text-[#c8ccc8] rounded-bl-sm"
                            )
                        )

        conversation()
        ui.label("Sugestões").classes("text-xs uppercase tracking-widest text-[#747a75]")
        suggestions = [
            "Deixe a cena mais cinematográfica",
            "Crie uma segunda versão",
            "Verifique a continuidade visual",
        ]
        ui.space()
        prompt = (
            ui.textarea(placeholder=prompts[active]).props("outlined autogrow").classes("w-full")
        )

        async def send_message(text: str | None = None) -> None:
            user_message = (text or prompt.value or "").strip()
            if not user_message:
                return
            messages.append({"role": "user", "content": user_message})
            prompt.value = ""
            conversation.refresh()
            try:
                async with AsyncSessionLocal() as session:
                    response = await ask_director_agent(
                        session,
                        project_id,
                        active,
                        user_message,
                        context,
                        messages,
                    )
            except Exception as exc:
                response = f"Não consegui responder agora ({type(exc).__name__}). Tente novamente."
            messages.append({"role": "assistant", "content": response})
            conversation.refresh()

        with ui.row().classes("w-full gap-2 overflow-x-auto flex-nowrap"):
            for text in suggestions:
                ui.button(text, on_click=lambda value=text: send_message(value)).props(
                    "outline no-caps dense"
                ).classes("border-[#303530] text-[#b8bdb8] rounded-full whitespace-nowrap")
        with ui.row().classes("w-full items-center"):
            ui.button(icon="add").props("flat round").classes("text-[#aeb3ae]")
            ui.space()
            ui.button(
                icon="arrow_upward",
                on_click=send_message,
            ).props("round unelevated").classes("acid-bg")


def _section_title(title: str, subtitle: str, action: str, callback: Any) -> None:
    with ui.row().classes("w-full items-end justify-between mb-2"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("brand-type text-3xl font-bold")
            ui.label(subtitle).classes("text-sm text-[#8e948f]")
        ui.button(action, icon="auto_awesome", on_click=callback).props(
            "unelevated no-caps"
        ).classes("acid-bg rounded-xl font-semibold")


def _render_script_area(project_id: UUID, summary: dict[str, Any]) -> None:
    script = summary["script"]
    _section_title(
        "Roteiro",
        "Estruture a narrativa e transforme o texto em cenas e planos.",
        "Gerar roteiro",
        lambda: _run_step(project_id, "script"),
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            with ui.element("div").classes("entity-card rounded-2xl p-7 min-h-[520px] w-full"):
                ui.label(script.title if script else "Seu roteiro começa aqui").classes(
                    "brand-type text-2xl font-bold mb-5"
                )
                content = (
                    script.content
                    if script
                    else "Conte a ideia do seu filme no chat inicial ou use o Diretor IA. Quando o roteiro for gerado, ele aparecerá neste editor organizado em cenas, ações e diálogos."
                )
                ui.label(content).classes("whitespace-pre-wrap leading-8 text-[#d9dcd9]")
        with ui.column().classes("w-64 gap-3"):
            ui.label("Cenas").classes("font-semibold")
            for scene in summary["scenes"]:
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
        "Gerar ativos",
        lambda: _run_step(project_id, "visual"),
    )
    with (
        ui.tabs()
        .classes("text-[#8d938e]")
        .props("no-caps active-color=lime-3 indicator-color=lime-3") as tabs
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
                            ui.label("Use Gerar ativos para montar esta coleção.").classes(
                                "text-sm text-[#888e89]"
                            )


def _render_storyboard_area(project_id: UUID, summary: dict[str, Any]) -> None:
    _section_title(
        "Storyboard",
        "Planeje enquadramentos e ritmo antes de gerar os clipes.",
        "Gerar storyboard",
        lambda: _run_step(project_id, "storyboard"),
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
            ui.label("Gere o roteiro e os ativos antes de criar os quadros.").classes(
                "text-[#858b86]"
            )


def _render_video_area(project_id: UUID, summary: dict[str, Any]) -> None:
    _section_title(
        "Produção de vídeo",
        "Gere clipes, escolha variações e finalize sua montagem.",
        "Gerar clipes",
        lambda: _run_step(project_id, "video"),
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
            ui.label("Seus clipes aparecerão aqui depois do storyboard.").classes("text-[#858b86]")
    ui.label("Timeline").classes("brand-type text-2xl font-bold mt-6")
    _render_timeline_strip(summary["timeline"], summary["timeline_items"])


def register_ui_pages() -> None:
    settings = get_settings()

    @ui.page("/")
    async def dashboard() -> None:
        _body_style()
        projects = await _project_cards()
        _home_sidebar()
        with ui.column().classes("ml-0 md:ml-24 min-h-screen px-5 md:px-12 py-7 gap-10"):
            with ui.row().classes("w-full items-center justify-between"):
                _studio_logo()
                with ui.row().classes("items-center gap-3"):
                    ui.label("Estúdio pessoal").classes("text-sm text-[#939994]")
                    ui.avatar("J", color="grey-9")
            with ui.column().classes(
                "w-full max-w-5xl mx-auto items-center text-center gap-5 pt-6"
            ):
                with ui.element("div").classes(
                    "chat-shell glass rounded-3xl p-5 w-full min-h-[360px] flex flex-col"
                ):
                    idea = (
                        ui.textarea(
                            placeholder="Descreva sua história, cole um roteiro ou peça uma ideia..."
                        )
                        .props("borderless autogrow input-style='min-height:260px'")
                        .classes("w-full text-lg flex-1 text-left")
                    )
                    with ui.row().classes("w-full items-center px-2 pb-1 gap-2"):
                        ui.button(icon="add").props("flat round").classes("text-[#a4aaa5]")
                        ui.button("Enviar roteiro", icon="description").props(
                            "flat no-caps"
                        ).classes("text-[#b8bdb8]")
                        ui.space()
                        ui.select(
                            ["Filme narrativo", "Clipe musical", "Vídeo de produto"],
                            value="Filme narrativo",
                        ).props("borderless dense").classes("w-44")
                        ui.button(
                            icon="arrow_upward",
                            on_click=lambda: ui.navigate.to(f"/new?idea={idea.value or ''}"),
                        ).props("round unelevated").classes("acid-bg")
                with ui.row().classes("justify-center gap-2"):
                    for suggestion in [
                        "Uma ficção científica intimista",
                        "Documentário de marca",
                        "Terror em 60 segundos",
                    ]:
                        ui.button(suggestion).props("outline rounded no-caps").classes(
                            "border-[#343934] text-[#aeb3ae]"
                        )
            with ui.column().props("id=projects").classes("w-full max-w-6xl mx-auto gap-4 pt-10"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Projetos recentes").classes("brand-type text-3xl font-bold")
                    ui.button(
                        "Novo projeto", icon="add", on_click=lambda: ui.navigate.to("/new")
                    ).props("flat no-caps").classes("acid")
                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"):
                    for project in projects:
                        with (
                            ui.element("div")
                            .classes("entity-card rounded-2xl overflow-hidden cursor-pointer")
                            .on(
                                "click",
                                lambda p=project.id: ui.navigate.to(f"/projects/{p}/script"),
                            )
                        ):
                            with ui.element("div").classes(
                                "visual-placeholder aspect-video p-5 flex items-end"
                            ):
                                ui.icon("play_circle").classes("text-4xl acid")
                            with ui.column().classes("p-4 gap-1"):
                                ui.label(project.title).classes("brand-type text-xl font-bold")
                                ui.label(
                                    project.description or "Projeto em desenvolvimento"
                                ).classes("text-sm text-[#8d938e] line-clamp-2")
                    with (
                        ui.element("div")
                        .classes(
                            "border border-dashed border-[#363b36] rounded-2xl min-h-52 flex flex-col items-center justify-center cursor-pointer text-[#969c97]"
                        )
                        .on("click", lambda: ui.navigate.to("/new"))
                    ):
                        ui.icon("add_circle_outline").classes("text-4xl acid")
                        ui.label("Criar novo projeto").classes("mt-2 font-semibold")

    @ui.page("/new")
    async def new_project() -> None:
        _body_style()
        _render_header(settings.app_name, "Novo projeto guiado")
        form: dict[str, Any] = {}
        with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-6 gap-5"):
            ui.label("Briefing inicial").classes("text-3xl font-bold")
            _muted("Preencha o essencial. Depois o workspace conduz as geracoes.")
            with ui.card().classes(_card_classes("w-full")):
                one_line_idea = ui.textarea(
                    "Ideia em linguagem natural",
                    value=(
                        "Um drama emocional de 3 minutos sobre uma pessoa que encontra "
                        "uma carta antiga e descobre uma verdade familiar."
                    ),
                ).classes("w-full")
                with ui.grid(columns=2).classes("w-full gap-4"):
                    title = ui.input("Titulo do projeto", value="Historia emocional vertical")
                    description = ui.textarea("Descricao", value="Video curto emocional para reels")
                    theme = ui.input("Tema", value="uma lembranca familiar reencontrada")
                    audience = ui.input(
                        "Publico",
                        value="adultos que gostam de historias emocionais",
                    )
                    genre = ui.input("Genero", value="drama emocional")
                    emotion = ui.input("Emocao principal", value="esperanca")
                    intensity = ui.number("Intensidade emocional", value=8, min=1, max=10)
                    ending = ui.input("Tipo de final", value="final com revelacao afetiva")
                    duration = ui.number(
                        "Duracao em minutos",
                        value=3.0,
                        min=3.0,
                        max=8.0,
                        step=0.5,
                    )
                    visual_style = ui.input("Estilo visual", value="cinematico realista vertical")
                    objective = ui.input("Objetivo", value="reter audiencia com historia curta")
                    cta = ui.input("Chamada para acao", value="comentar uma lembranca parecida")
                ui.label("Core Setup").classes("text-lg font-semibold")
                with ui.grid(columns=3).classes("w-full gap-4"):
                    content_type = ui.select(
                        CONTENT_TYPES,
                        label="Tipo de conteudo",
                        value="short_drama",
                    )
                    aspect_ratio = ui.select(ASPECT_RATIOS, label="Aspect ratio", value="9:16")
                    workflow_mode = ui.select(
                        WORKFLOW_MODES,
                        label="Workflow",
                        value="keyframes_i2v",
                    )
                    image_resolution = ui.select(
                        RESOLUTIONS,
                        label="Resolucao de imagem",
                        value="1080x1920",
                    )
                    video_resolution = ui.select(
                        RESOLUTIONS,
                        label="Resolucao de video",
                        value="1080x1920",
                    )
                    motion_intensity = ui.number(
                        "Intensidade de movimento",
                        value=5,
                        min=1,
                        max=10,
                    )
                    image_model = ui.input("Modelo de imagem", value="mock-image")
                    video_model = ui.input("Modelo de video", value="mock-video")
                constraints = ui.textarea(
                    "Restricoes",
                    value="evitar violencia grafica\nmanter tom familiar",
                ).classes("w-full")

                async def submit() -> None:
                    form.update(
                        {
                            "title": title.value,
                            "description": description.value,
                            "theme": theme.value,
                            "audience": audience.value,
                            "genre": genre.value,
                            "emotion": emotion.value,
                            "intensity": intensity.value,
                            "ending": ending.value,
                            "duration": duration.value,
                            "visual_style": visual_style.value,
                            "objective": objective.value,
                            "cta": cta.value,
                            "constraints": constraints.value,
                            "one_line_idea": one_line_idea.value,
                            "content_type": content_type.value,
                            "aspect_ratio": aspect_ratio.value,
                            "workflow_mode": workflow_mode.value,
                            "image_resolution": image_resolution.value,
                            "video_resolution": video_resolution.value,
                            "motion_intensity": motion_intensity.value,
                            "image_model": image_model.value,
                            "video_model": video_model.value,
                        }
                    )
                    await _create_project_from_form(form)

                ui.button(
                    "Criar projeto e abrir workspace",
                    icon="rocket_launch",
                    on_click=submit,
                ).classes(_button_classes())

    @ui.page("/projects/{project_id}")
    async def project_workspace(project_id: str) -> None:
        ui.navigate.to(f"/projects/{project_id}/script")
        return
        _body_style()
        project_uuid = UUID(project_id)
        summary = await _project_summary(project_uuid)
        if summary is None:
            _render_header(settings.app_name, "Projeto nao encontrado")
            ui.label("Projeto nao encontrado.").classes("p-6")
            return

        project: Project = summary["project"]
        production_settings: ProjectProductionSettings = summary["production_settings"]
        counts: dict[str, int] = summary["counts"]
        _render_header(
            project.title,
            f"{workflow_mode_label(production_settings.workflow_mode)} · "
            f"{production_settings.aspect_ratio} · {production_settings.video_resolution}",
        )

        with ui.column().classes("w-full max-w-7xl mx-auto px-6 py-6 gap-6"):
            with ui.row().classes("w-full gap-3"):
                for label, value in [
                    ("Status", project.status.value),
                    ("Workflow", workflow_mode_label(production_settings.workflow_mode)),
                    ("Custo estimado", f"USD {summary['cost_total']}"),
                    (
                        "Score QA",
                        str(summary["quality"].score) if summary["quality"] else "sem check",
                    ),
                    ("Export", summary["export"].status if summary["export"] else "pendente"),
                ]:
                    with ui.card().classes(_card_classes("flex-1")):
                        ui.label(label).classes("text-xs uppercase text-slate-400")
                        ui.label(value).classes("text-xl font-semibold")

            _render_director_cockpit(production_settings, counts)

            with ui.row().classes("w-full gap-4 items-start"):
                with ui.column().classes("flex-1 gap-4"):
                    _render_core_setup(project_uuid, production_settings)
                    ui.label("Passos de criacao").classes("text-2xl font-bold")
                    with ui.grid(columns=3).classes("w-full gap-3"):
                        for step in PRODUCTION_STEPS:
                            _render_step_card(project_uuid, step, counts)
                    _render_asset_canvas(summary)
                    _render_storyboard_grid(summary["frames"])
                    _render_timeline_strip(summary["timeline"], summary["timeline_items"])

                with ui.column().classes("w-96 gap-4"):
                    _render_model_settings(project_uuid, summary["model_settings"])
                    ui.button(
                        "Criar proximo episodio",
                        icon="queue_play_next",
                        on_click=lambda: _create_next_episode(project_uuid),
                    ).classes(_button_classes())

                    ui.label("Resumo do projeto").classes("text-2xl font-bold")
                    with ui.card().classes(_card_classes("w-full")):
                        for label, key in [
                            ("Ideias", "ideas"),
                            ("Story Bible", "bibles"),
                            ("Roteiros", "scripts"),
                            ("Cenas", "scenes"),
                            ("Planos", "shots"),
                            ("Referencias visuais", "visual_refs"),
                            ("Storyboards", "frames"),
                            ("Clipes", "clips"),
                            ("Audios", "audio"),
                            ("Legendas", "subtitles"),
                            ("Exports", "exports"),
                        ]:
                            with ui.row().classes("w-full justify-between"):
                                ui.label(label).classes("text-sm text-slate-300")
                                ui.label(str(counts[key])).classes("font-mono text-cyan-200")
                        ui.separator().classes("bg-slate-800")
                        ui.link(
                            "Ver observabilidade JSON",
                            f"/api/v1/quality/projects/{project_id}/observability",
                        ).classes("text-cyan-200")

    @ui.page("/projects/{project_id}/{section}")
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
        _workspace_header(project, section)
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
