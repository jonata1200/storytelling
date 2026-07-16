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
from app.generation.model_settings import (
    NARRATIVE_TASKS,
    TASK_LABELS,
    ensure_default_model_settings,
    set_model_setting,
)
from app.generation.models import ProjectModelSetting
from app.projects.models import Artifact, Project
from app.projects.schemas import ProjectCreate
from app.projects.service import create_project
from app.quality.models import ContinuityIssue, QualityCheck
from app.quality.service import run_quality_check
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame
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
    ui.query("body").classes("bg-slate-950 text-slate-100")
    ui.add_head_html(
        """
        <style>
          .q-field__label { color: #bae6fd !important; }
          .q-field__native, .q-field__input, .q-textarea textarea {
            color: #f8fafc !important;
          }
          .q-field__control {
            background: #020617 !important;
            border-radius: 6px !important;
          }
          .q-field__control::before { border-color: #334155 !important; }
          .q-field__control::after { color: #22d3ee !important; }
          .q-field--focused .q-field__label { color: #67e8f9 !important; }
          .q-placeholder::placeholder { color: #94a3b8 !important; }
          .q-menu { background: #0f172a !important; color: #f8fafc !important; }
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
        return {
            "project": project,
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
                    item.strip()
                    for item in form["constraints"].splitlines()
                    if item.strip()
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
                "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 "
                "border border-amber-800"
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
                        lambda task=task,
                        provider_select=provider_select,
                        model_input=model_input: _save_model_setting(
                            project_id,
                            task,
                            provider_select.value,
                            model_input.value,
                        )
                    ),
                ).classes("bg-slate-800 hover:bg-slate-700 rounded-md")

def register_ui_pages() -> None:
    settings = get_settings()

    @ui.page("/")
    async def dashboard() -> None:
        _body_style()
        metrics = await _dashboard_metrics()
        projects = await _project_cards()
        _render_header(settings.app_name, "Fluxo guiado para produzir videos verticais com IA")

        with ui.column().classes("w-full max-w-7xl mx-auto px-6 py-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-1"):
                    ui.label("Central de producao").classes("text-3xl font-bold")
                    _muted("Crie um projeto, avance pelas etapas e acompanhe tudo em um workspace.")
                ui.button(
                    "Novo projeto",
                    icon="add",
                    on_click=lambda: ui.navigate.to("/new"),
                ).classes(_button_classes())

            with ui.grid(columns=5).classes("w-full gap-3"):
                for label, value in metrics.items():
                    with ui.card().classes(_card_classes()):
                        ui.label(label).classes("text-xs uppercase text-slate-400")
                        ui.label(value).classes("text-2xl font-semibold")

            ui.label("Projetos recentes").classes("text-xl font-semibold")
            if not projects:
                with ui.card().classes(_card_classes("w-full")):
                    ui.label("Nenhum projeto criado ainda.").classes("font-semibold")
                    _muted("Comece pelo briefing para gerar uma historia completa.")
            else:
                with ui.grid(columns=3).classes("w-full gap-3"):
                    for project in projects:
                        with ui.card().classes(_card_classes("min-h-44")):
                            ui.label(project.title).classes("text-lg font-semibold")
                            ui.label(project.status.value).classes(
                                "text-xs text-cyan-200 font-mono"
                            )
                            ui.label(project.description or "Sem descricao").classes(
                                "text-sm text-slate-400 min-h-10"
                            )
                            ui.button(
                                "Abrir workspace",
                                icon="arrow_forward",
                                on_click=lambda pid=project.id: ui.navigate.to(f"/projects/{pid}"),
                            ).classes(_button_classes())

    @ui.page("/new")
    async def new_project() -> None:
        _body_style()
        _render_header(settings.app_name, "Novo projeto guiado")
        form: dict[str, Any] = {}
        with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-6 gap-5"):
            ui.label("Briefing inicial").classes("text-3xl font-bold")
            _muted("Preencha o essencial. Depois o workspace conduz as geracoes.")
            with ui.card().classes(_card_classes("w-full")):
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
        _body_style()
        project_uuid = UUID(project_id)
        summary = await _project_summary(project_uuid)
        if summary is None:
            _render_header(settings.app_name, "Projeto nao encontrado")
            ui.label("Projeto nao encontrado.").classes("p-6")
            return

        project: Project = summary["project"]
        counts: dict[str, int] = summary["counts"]
        _render_header(project.title, "Workspace de producao do video")

        with ui.column().classes("w-full max-w-7xl mx-auto px-6 py-6 gap-6"):
            with ui.row().classes("w-full gap-3"):
                for label, value in [
                    ("Status", project.status.value),
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

            with ui.row().classes("w-full gap-4 items-start"):
                with ui.column().classes("flex-1 gap-4"):
                    ui.label("Passos de criacao").classes("text-2xl font-bold")
                    with ui.grid(columns=3).classes("w-full gap-3"):
                        for step in PRODUCTION_STEPS:
                            _render_step_card(project_uuid, step, counts)

                with ui.column().classes("w-96 gap-4"):
                    _render_model_settings(project_uuid, summary["model_settings"])

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
