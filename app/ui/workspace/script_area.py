from collections.abc import Callable
from typing import Any
from uuid import UUID

from nicegui import background_tasks, ui

from app.database.session import AsyncSessionLocal
from app.projects.models import Artifact
from app.projects.versioning import create_artifact_version
from app.storytelling.models import Script, ScriptVersion
from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS, STEP_LOADING_COPY
from app.ui.project.workflows import (
    _generate_missing_scenes_in_background,
    _reload_project_when_script_ready,
    _resume_initial_script_in_background,
)

LoadingDialogFactory = Callable[[str, str], Any]
ProjectAiActionReader = Callable[[dict[str, Any]], dict[str, Any]]
AiActionStaleChecker = Callable[[dict[str, Any]], bool]
RetryInitialScriptHandler = Callable[[UUID, Any], None]
SectionTitle = Callable[[str, str, str | None, Any | None], None]


async def save_script_from_ui(
    project_id: UUID,
    script_id: UUID,
    title: str,
    content: str,
) -> None:
    try:
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("Informe um titulo para o roteiro.")
        if not clean_content:
            raise ValueError("O roteiro nao pode ficar vazio.")

        async with AsyncSessionLocal() as session:
            script = await session.get(Script, script_id)
            if script is None or script.project_id != project_id:
                raise ValueError("Roteiro nao encontrado.")
            artifact = await session.get(Artifact, script.artifact_id)
            if artifact is None:
                raise ValueError("Artefato do roteiro nao encontrado.")

            script.title = clean_title[:220]
            script.content = clean_content
            script.word_count = len(clean_content.split())
            payload = {
                "title": script.title,
                "language": script.language,
                "target_duration_seconds": script.target_duration_seconds,
                "word_count": script.word_count,
                "content": script.content,
            }
            artifact.name = script.title
            await create_artifact_version(
                session,
                artifact,
                payload,
                change_note="Script edited manually in UI",
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
            await session.commit()
        ui.notify("Roteiro salvo.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Nao consegui salvar o roteiro: {exc}", color="negative")


def render_script_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    project_ai_action: ProjectAiActionReader,
    ai_action_is_stale: AiActionStaleChecker,
    loading_dialog_factory: LoadingDialogFactory,
    retry_initial_script_from_ui: RetryInitialScriptHandler,
    section_title: SectionTitle,
) -> None:
    script = summary["script"]
    ai_action = project_ai_action(summary)
    ai_status = str(ai_action.get("status") or "")
    ai_action_name = str(ai_action.get("action") or "")
    missing_scenes = script is not None and not summary["scenes"]
    scene_generation_failed = ai_action_name == "create_script_scenes" and ai_status == "failed"
    should_recover_missing_scenes = (
        missing_scenes and ai_status not in {"queued", "running"} and not scene_generation_failed
    )
    should_resume_stale_script = (
        script is None
        and ai_status in {"queued", "running"}
        and ai_action_is_stale(ai_action)
    )
    if should_recover_missing_scenes:
        background_tasks.create(
            _generate_missing_scenes_in_background(project_id, script.id),
            name=f"generate missing scenes {project_id}",
        )
    if should_resume_stale_script:
        background_tasks.create(
            _resume_initial_script_in_background(project_id),
            name=f"resume initial script {project_id}",
        )
    generation_in_progress = (
        ai_status in {"queued", "running"}
        or should_recover_missing_scenes
        or should_resume_stale_script
    )
    if generation_in_progress:
        loading_title = (
            "Gerando cenas"
            if missing_scenes
            else (
                "Retomando roteiro"
                if should_resume_stale_script
                else STEP_LOADING_COPY["script"][0]
            )
        )
        loading_message = (
            "A IA esta criando cenas e planos para o roteiro."
            if missing_scenes
            else str(
                ai_action.get("message")
                or "A IA esta desenvolvendo o roteiro com base na ideia."
            )
        )
        loading_dialog = loading_dialog_factory(loading_title, loading_message)
        loading_dialog.open()
        ui.timer(5.0, lambda: _reload_project_when_script_ready(project_id))
    edit_dialog = None
    if script is not None:
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as edit_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(1040px,94vw)] h-[min(860px,92vh)] "
            "max-h-[92vh] flex flex-col"
        ):
            ui.label("Editar roteiro").classes("brand-type text-2xl font-bold shrink-0")
            title_input = ui.input("Titulo", value=script.title).props("outlined").classes("w-full")
            content_input = ui.textarea("Conteudo do roteiro", value=script.content).props(
                "outlined"
            ).classes("script-editor-textarea w-full flex-1 min-h-0 font-mono text-sm")
            with ui.row().classes("w-full justify-end gap-2 shrink-0"):
                ui.button("Cancelar", on_click=edit_dialog.close).props("flat no-caps")
                ui.button(
                    "Salvar",
                    icon="save",
                    on_click=lambda: save_script_from_ui(
                        project_id,
                        script.id,
                        str(title_input.value or ""),
                        str(content_input.value or ""),
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
    section_title(
        "Roteiro",
        "Edite e revise o roteiro cinematografico que orienta as proximas etapas.",
        "Editar roteiro" if edit_dialog is not None else None,
        edit_dialog.open if edit_dialog is not None else None,
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            if script is None and ai_status == "failed":
                retry_loading_dialog = loading_dialog_factory(
                    "Retomando roteiro",
                    "A IA esta tentando criar o roteiro inicial novamente.",
                )

                def retry_initial_script() -> None:
                    retry_initial_script_from_ui(project_id, retry_loading_dialog)

                with ui.element("div").classes(
                    "border border-red-900 bg-red-950/40 rounded-2xl p-4 text-red-100"
                ):
                    ui.label("A IA nao conseguiu criar o roteiro inicial.").classes(
                        "font-semibold"
                    )
                    ui.label(str(ai_action.get("error") or ai_action.get("message") or "")).classes(
                        "text-sm opacity-80"
                    )
                    ui.button(
                        "Tentar novamente",
                        icon="refresh",
                        on_click=retry_initial_script,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl mt-3")
            with ui.element("div").classes("entity-card rounded-2xl p-7 min-h-[640px] w-full"):
                ui.label(script.title if script else "Seu roteiro começa aqui").classes(
                    "brand-type text-2xl font-bold mb-5"
                )
                content = (
                    script.content
                    if script
                    else "A IA esta desenvolvendo o roteiro com base na ideia do projeto."
                )
                ui.label(content).classes("whitespace-pre-wrap leading-8 text-[#d9dcd9]")




