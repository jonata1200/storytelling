import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact
from app.projects.versioning import (
    create_artifact_version,
    resolve_stale_artifacts_after_regeneration,
)
from app.storytelling.models import Scene, Script, ScriptVersion, Shot, StoryIdea
from app.storytelling.service import regenerate_scenes_and_shots
from app.ui.project.data import latest as _latest
from app.ui.project.data import scalar_count as _scalar_count
from app.ui.project.workflows import (
    _generate_missing_scenes_in_background,
    _reload_project_when_script_ready,
    _resume_initial_script_in_background,
)
from app.ui.shared.cost_display import SCRIPT_TEXT_ESTIMATED_TOKENS, text_generation_cost_text
from app.ui.shared.generation_progress import generation_progress_dialog
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    UI_GENERATION_TIMEOUT_SECONDS,
    loading_status_message,
    safe_close_ui_element,
)

LoadingDialogFactory = Callable[[str, Any], Any]
ProjectAiActionReader = Callable[[dict[str, Any]], dict[str, Any]]
AiActionStaleChecker = Callable[[dict[str, Any]], bool]
RetryInitialScriptHandler = Callable[[UUID, Any], Awaitable[None]]
SectionTitle = Callable[[str, str, str | None, Any | None], None]
NotifyCallback = Callable[[str, str], None]
ReloadCallback = Callable[[], None]


def script_generation_in_progress(
    *,
    script: object | None,
    scenes: list[Any],
    ai_status: str,
    should_recover_missing_scenes: bool,
    should_resume_stale_script: bool,
) -> bool:
    return (
        (script is None and ai_status in {"queued", "running"})
        or should_recover_missing_scenes
        or should_resume_stale_script
    )


async def _refresh_script_derivatives_from_ui(project_id: UUID, script_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        scenes = await regenerate_scenes_and_shots(session, project_id, script_id)
        if scenes is None:
            raise ValueError("não foi possível recriar cenas e planos para o roteiro.")
        await resolve_stale_artifacts_after_regeneration(session, project_id)


def _schedule_initial_script_resume(project_id: UUID) -> None:
    asyncio.create_task(_resume_initial_script_in_background(project_id))


def _schedule_missing_scenes_generation(project_id: UUID, script_id: UUID) -> None:
    asyncio.create_task(_generate_missing_scenes_in_background(project_id, script_id))


def script_editor_state(title: object, content: object) -> dict[str, str]:
    return {
        "title": str(title or ""),
        "content": str(content or ""),
        "saving": "false",
    }


def _is_deleted_slot_error(exc: RuntimeError) -> bool:
    return "parent element this slot belongs to has been deleted" in str(exc).lower()


def _notify_client(client: Any, message: str, color: str) -> None:
    try:
        if getattr(client, "is_deleted", False):
            return
        client.outbox.enqueue_message(
            "notify",
            {"message": str(message), "color": color},
            client.id,
        )
    except RuntimeError as exc:
        if not _is_deleted_slot_error(exc):
            raise


def _reload_client(client: Any) -> None:
    try:
        if getattr(client, "is_deleted", False):
            return
        client.run_javascript("history.go(0)")
    except RuntimeError as exc:
        if not _is_deleted_slot_error(exc):
            raise


def _ai_action_age_seconds(action: dict[str, Any]) -> float | None:
    raw_updated_at = str(action.get("updated_at") or "").strip()
    if not raw_updated_at:
        return None
    try:
        updated_at = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - updated_at.astimezone(UTC)).total_seconds()


def _ai_action_exceeded_generation_timeout(
    action: dict[str, Any],
    max_age_seconds: int = UI_GENERATION_TIMEOUT_SECONDS,
) -> bool:
    if str(action.get("status") or "") not in {"queued", "running"}:
        return False
    age_seconds = _ai_action_age_seconds(action)
    return age_seconds is not None and age_seconds > max_age_seconds


async def _close_loading_dialog_when_script_ready(project_id: UUID, loading_dialog: Any) -> None:
    ready = await _reload_project_when_script_ready(project_id)
    if ready and hasattr(loading_dialog, "close"):
        safe_close_ui_element(loading_dialog)


async def _script_generation_progress_state(project_id: UUID) -> tuple[int, int, str, bool]:
    async with AsyncSessionLocal() as session:
        idea = await _latest(session, StoryIdea, project_id)
        script = await _latest(session, Script, project_id)
        scene_count = await _scalar_count(session, Scene, project_id)
        shot_count = await _scalar_count(session, Shot, project_id)
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        action = metadata.get("ai_action") if isinstance(metadata, dict) else None
        status = str(action.get("status") or "") if isinstance(action, dict) else ""
        message = str(action.get("message") or "") if isinstance(action, dict) else ""
        action_timeout = (
            _ai_action_exceeded_generation_timeout(action) if isinstance(action, dict) else False
        )
    completed = 0
    if idea is not None:
        completed = 1
    if script is not None:
        completed = 2
    if scene_count > 0:
        completed = 3
    if status == "completed":
        completed = 3
    counts = {
        "ideas": 1 if idea is not None else 0,
        "scripts": 1 if script is not None else 0,
        "scenes": scene_count,
        "shots": shot_count,
    }
    failed = status == "failed"
    if action_timeout:
        detail = (
            "A geração demorou demais ou foi interrompida. Vou recarregar para liberar "
            "uma nova tentativa."
            f"\n{loading_status_message('script', counts)}"
        )
    elif failed:
        detail = (
            "A IA não conseguiu concluir o roteiro inicial."
            f"\n{loading_status_message('script', counts)}"
        )
    elif completed == 0:
        detail = loading_status_message(
            "script",
            counts,
            now=message or "Agora: criando uma ideia narrativa para orientar o roteiro.",
        )
    elif completed == 1:
        detail = loading_status_message(
            "script",
            counts,
            now=message or "Agora: escrevendo o roteiro cinematografico.",
        )
    elif completed == 2:
        detail = loading_status_message(
            "script",
            counts,
            now=message or "Agora: separando cenas e planos.",
        )
    else:
        detail = loading_status_message(
            "script",
            counts,
            now="Agora: roteiro, cenas e planos prontos.",
        )
    return completed, 3, detail, completed >= 3 or failed or action_timeout


async def _update_script_generation_progress(
    project_id: UUID,
    loading_dialog: Any,
    update_progress: Callable[[int, int, str], None],
) -> None:
    completed, total, detail, terminal = await _script_generation_progress_state(project_id)
    update_progress(completed, total, detail)
    if terminal and hasattr(loading_dialog, "close"):
        safe_close_ui_element(loading_dialog)
        ui.navigate.reload()


async def save_script_from_ui(
    project_id: UUID,
    script_id: UUID,
    title: str,
    content: str,
    *,
    notify: NotifyCallback | None = None,
    reload_page: ReloadCallback | None = None,
) -> None:
    notify_user = notify or (lambda message, color: ui.notify(message, color=color))
    reload_user = reload_page or ui.navigate.reload
    try:
        notify_user("Salvando roteiro...", "info")
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("Informe um título para o roteiro.")
        if not clean_content:
            raise ValueError("O roteiro não pode ficar vazio.")

        async with AsyncSessionLocal() as session:
            script = await session.get(Script, script_id)
            if script is None or script.project_id != project_id:
                raise ValueError("Roteiro não encontrado.")
            artifact = await session.get(Artifact, script.artifact_id)
            if artifact is None:
                raise ValueError("Artefato do roteiro não encontrado.")

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
                mark_downstream_stale=False,
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
        notify_user(
            "Roteiro salvo. Atualizando apenas cenas e planos...",
            "info",
        )
        try:
            await _refresh_script_derivatives_from_ui(project_id, script_id)
        except Exception as exc:
            notify_user(
                (
                    "Roteiro salvo, mas não consegui atualizar automaticamente "
                    f"cenas e planos: {exc}"
                ),
                "warning",
            )
            reload_user()
            return
        notify_user("Roteiro salvo. Cenas e planos atualizados.", "positive")
        reload_user()
    except Exception as exc:
        notify_user(f"Não consegui salvar o roteiro: {exc}", "negative")


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
    scene_generation_failed = (
        ai_action_name in {"create_script_scenes", "scenes"} and ai_status == "failed"
    )
    should_recover_missing_scenes = (
        missing_scenes and ai_status not in {"queued", "running"} and not scene_generation_failed
    )
    should_resume_stale_script = (
        script is None
        and ai_status in {"queued", "running"}
        and ai_action_is_stale(ai_action)
    )
    if should_recover_missing_scenes:
        script_id = getattr(script, "id", None)
        if isinstance(script_id, UUID):
            ui.timer(
                0.1,
                lambda: _schedule_missing_scenes_generation(project_id, script_id),
                once=True,
            )
    if should_resume_stale_script:
        ui.timer(0.1, lambda: _schedule_initial_script_resume(project_id), once=True)
    generation_in_progress = script_generation_in_progress(
        script=script,
        scenes=summary["scenes"],
        ai_status=ai_status,
        should_recover_missing_scenes=should_recover_missing_scenes,
        should_resume_stale_script=should_resume_stale_script,
    )
    if generation_in_progress:
        loading_title = (
            "Gerando cenas"
            if missing_scenes
            else (
                "Retomando roteiro"
                if should_resume_stale_script
                else "Gerando roteiro"
            )
        )
        loading_message = (
            loading_status_message(
                "script",
                summary["counts"],
                now="Agora: criando cenas e planos para o roteiro.",
            )
            if missing_scenes
            else (
                loading_status_message(
                    "script",
                    summary["counts"],
                    now="Agora: retomando a criação do roteiro internamente.",
                )
                if should_resume_stale_script
                else loading_status_message(
                    "script",
                    summary["counts"],
                    now=str(
                        ai_action.get("message")
                        or "Agora: desenvolvendo o roteiro com base na ideia do projeto."
                    ),
                )
            )
        )
        loading_dialog, update_script_progress = generation_progress_dialog(
            loading_title,
            3,
            "etapa",
            loading_message,
        )
        loading_dialog.open()
        update_script_progress(0, 3, loading_message)
        ui.timer(
            2.0,
            lambda: _update_script_generation_progress(
                project_id,
                loading_dialog,
                update_script_progress,
            ),
        )
    edit_dialog = None
    if script is not None:
        script_id = script.id
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as edit_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(1040px,94vw)] h-[min(860px,92vh)] "
            "max-h-[92vh] flex flex-col"
        ):
            edit_state = script_editor_state(script.title, script.content)

            async def save_current_script() -> None:
                if edit_state["saving"] == "true":
                    return
                client = ui.context.client
                edit_state["saving"] = "true"
                if save_button is not None:
                    save_button.disable()
                if edit_dialog is not None:
                    edit_dialog.close()
                await save_script_from_ui(
                    project_id,
                    script_id,
                    edit_state["title"],
                    edit_state["content"],
                    notify=lambda message, color: _notify_client(client, message, color),
                    reload_page=lambda: _reload_client(client),
                )

            ui.label("Editar roteiro").classes("brand-type text-2xl font-bold shrink-0")
            ui.input("Título").bind_value(edit_state, "title").props("outlined").classes(
                "w-full"
            )
            ui.textarea("Conteúdo do roteiro").bind_value(edit_state, "content").props(
                "outlined"
            ).classes("script-editor-textarea w-full flex-1 min-h-0 font-mono text-sm")
            with ui.row().classes("w-full justify-end gap-2 shrink-0"):
                ui.button("Cancelar", on_click=edit_dialog.close).props("flat no-caps")
                save_button = ui.button(
                    "Salvar",
                    icon="save",
                    on_click=save_current_script,
                )
                save_button.props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
    section_title(
        "Roteiro",
        "Edite e revise o roteiro cinematográfico que orienta as próximas etapas.",
        "Editar roteiro" if edit_dialog is not None else None,
        edit_dialog.open if edit_dialog is not None else None,
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            if script is None:
                ui.label(
                    text_generation_cost_text(
                        summary,
                        "generate_script",
                        SCRIPT_TEXT_ESTIMATED_TOKENS,
                        "ideia, roteiro e cenas",
                    )
                ).classes("text-xs text-[#8d938e]")
            if script is None and ai_status == "failed":
                retry_loading_dialog, update_retry_progress = generation_progress_dialog(
                    "Retomando roteiro",
                    3,
                    "etapa",
                    loading_status_message(
                        "script",
                        summary["counts"],
                        now="Agora: tentando criar o roteiro inicial novamente.",
                    ),
                )

                async def retry_initial_script() -> None:
                    await retry_initial_script_from_ui(project_id, retry_loading_dialog)
                    update_retry_progress(
                        0,
                        3,
                        loading_status_message(
                            "script",
                            summary["counts"],
                            now="Agora: tentando criar o roteiro inicial novamente.",
                        ),
                    )
                    ui.timer(
                        2.0,
                        lambda: _update_script_generation_progress(
                            project_id,
                            retry_loading_dialog,
                            update_retry_progress,
                        ),
                    )

                with ui.element("div").classes(
                    "border border-red-900 bg-red-950/40 rounded-2xl p-4 text-red-100"
                ):
                    ui.label("A IA não conseguiu criar o roteiro inicial.").classes(
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
                    else "A IA está desenvolvendo o roteiro com base na ideia do projeto."
                )
                ui.label(content).classes("whitespace-pre-wrap leading-8 text-[#d9dcd9]")




