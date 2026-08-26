from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.jobs.service import enqueue_project_step
from app.production.service import get_or_create_production_settings
from app.projects.models import Artifact
from app.projects.versioning import (
    create_artifact_version,
)
from app.storytelling.models import Script, ScriptVersion, StoryIdea
from app.storytelling.service import (
    coerce_script_duration_minutes,
    generate_story_hooks,
    mark_scene_plan_stale,
)
from app.ui.project.data import latest as _latest
from app.ui.project.workflows import (
    _reload_project_when_script_ready,
    cancel_initial_script_generation,
    schedule_initial_script_resume,
)
from app.ui.shared.cost_display import SCRIPT_TEXT_ESTIMATED_TOKENS, text_generation_cost_text
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
)
from app.ui.shared.page_config import (
    BLOCKING_DIALOG_PROPS,
    SCRIPT_DURATION_OPTIONS,
    UI_GENERATION_TIMEOUT_SECONDS,
    block_if_missing_api_keys_for_step,
    friendly_ai_error,
    loading_status_message,
    play_completion_sound,
    safe_close_ui_element,
    script_progress_poll_interval,
    show_ai_error_popup,
)

# Flag para evitar som de conclusao duplicado quando o reload da pagina
# reativa o polling antes do backend commitar o script.
_completion_sound_played: dict[str, bool] = {}

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
    ai_status: str,
    should_resume_stale_script: bool,
) -> bool:
    return (
        (script is None and ai_status in {"queued", "running"})
        or should_resume_stale_script
    )


async def _refresh_script_derivatives_from_ui(project_id: UUID, script_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        await mark_scene_plan_stale(session, project_id, script_id)
        await session.commit()


async def _enqueue_script_generation(
    project_id: UUID,
    target_duration: float,
    story_hook: dict | None,
    dialog: Any,
) -> None:
    try:
        safe_close_ui_element(dialog)
        _completion_sound_played.pop(str(project_id), None)
        payload: dict[str, Any] = {"target_duration_minutes": target_duration}
        if story_hook is not None:
            payload["story_hook"] = story_hook
        async with AsyncSessionLocal() as session:
            await enqueue_project_step(session, project_id, "script", payload)
        ui.notify(f"Roteiro de {target_duration:g} minutos agendado.", color="positive")
        ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Não foi possível iniciar o roteiro: {exc}", color="negative")


async def _queue_initial_script_from_ui(
    project_id: UUID,
    target_duration_minutes: object,
    duration_dialog: Any,
) -> None:
    if block_if_missing_api_keys_for_step("script"):
        return
    target_duration = coerce_script_duration_minutes(target_duration_minutes)
    await _enqueue_script_generation(project_id, target_duration, None, duration_dialog)


async def _prepare_script_with_story_hooks(
    project_id: UUID,
    target_duration_minutes: object,
    duration_dialog: Any,
    loading_dialog_factory: LoadingDialogFactory,
) -> None:
    if block_if_missing_api_keys_for_step("script"):
        return
    target_duration = coerce_script_duration_minutes(target_duration_minutes)

    async with AsyncSessionLocal() as session:
        idea = await _latest(session, StoryIdea, project_id)

    # Normalmente o dashboard agenda esta etapa ao criar o projeto. Este fallback
    # cobre projetos antigos ou jobs interrompidos sem pular a escolha de gancho.
    if idea is None:
        safe_close_ui_element(duration_dialog)
        async with AsyncSessionLocal() as session:
            await enqueue_project_step(session, project_id, "ideas")
        ui.notify(
            "Ideia base agendada. Quando ela ficar pronta, escolha a duração "
            "novamente para ver os ganchos.",
            color="positive",
        )
        ui.navigate.reload()
        return

    safe_close_ui_element(duration_dialog)
    loading_dialog = loading_dialog_factory(
        "Criando ganchos para a história",
        "A IA está analisando a ideia para sugerir 5 ganchos que melhorem o roteiro.",
    )
    loading_dialog.open()
    try:
        async with AsyncSessionLocal() as session:
            hooks = await generate_story_hooks(session, project_id, idea.id)
        safe_close_ui_element(loading_dialog)
        if not hooks:
            raise ValueError("A IA não retornou ganchos para a história.")
        play_completion_sound()
        _open_story_hooks_dialog(project_id, target_duration, hooks)
    except Exception as exc:
        safe_close_ui_element(loading_dialog)
        show_ai_error_popup(
            friendly_ai_error(exc),
            title="Não consegui criar os ganchos",
        )
        try:
            duration_dialog.open()
        except RuntimeError:
            # Contexto de UI removido (usuário navegou); nada a reabrir.
            pass


def _open_story_hooks_dialog(
    project_id: UUID,
    target_duration: float,
    hooks: list[dict],
) -> None:
    selection: dict[str, Any] = {"index": None}

    def choose_hook(index: int) -> None:
        selection["index"] = index
        for row_index, (row, icon) in enumerate(hook_rows):
            selected = row_index == index
            if selected:
                row.classes(add="ring-2 ring-cyan-400 border-cyan-400")
                icon.props("name=radio_button_checked").classes(add="text-cyan-300")
            else:
                row.classes(remove="ring-2 ring-cyan-400 border-cyan-400")
                icon.props("name=radio_button_unchecked").classes(remove="text-cyan-300")
        generate_button.enable()

    with ui.dialog().props(BLOCKING_DIALOG_PROPS) as hooks_dialog, ui.card().classes(
        "entity-card rounded-2xl p-6 w-[min(680px,94vw)] gap-4"
    ):
        ui.label("Escolha um gancho para a história").classes(
            "brand-type text-2xl font-bold"
        )
        ui.label(
            "A IA criou 5 ganchos a partir da sua ideia. Escolha como a história "
            "vai abrir e prender a audiência; o roteiro será gerado com o gancho escolhido."
        ).classes("text-sm text-[#8f9590] leading-6")
        hook_rows: list[tuple[Any, Any]] = []
        with ui.column().classes("w-full gap-2 max-h-[52vh] overflow-y-auto pr-1"):
            for index, hook in enumerate(hooks):
                with ui.element("div").classes(
                    "w-full rounded-xl border border-[#2a2f2a] bg-[#171a17] p-3 cursor-pointer"
                ) as hook_row:
                    with ui.row().classes("w-full items-start gap-3"):
                        icon = ui.icon("radio_button_unchecked").classes(
                            "text-[#6b726c] shrink-0 mt-0.5"
                        )
                        with ui.column().classes("gap-1 flex-1"):
                            ui.label(str(hook.get("title") or "")).classes(
                                "font-semibold text-[#e6e9e6]"
                            )
                            ui.label(str(hook.get("description") or "")).classes(
                                "text-sm text-[#aab1ac] leading-5"
                            )
                    hook_row.on("click", lambda index=index: choose_hook(index))
                    hook_rows.append((hook_row, icon))
        with ui.row().classes("w-full justify-end gap-2"):
            generate_button = ui.button(
                "Gerar roteiro com este gancho",
                icon="auto_awesome",
                on_click=lambda: _enqueue_script_generation(
                    project_id,
                    target_duration,
                    hooks[selection["index"]],
                    hooks_dialog,
                ),
            )
            generate_button.props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
            generate_button.disable()
    hooks_dialog.open()


def _schedule_initial_script_resume(project_id: UUID) -> None:
    schedule_initial_script_resume(project_id)


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
        settings = await get_or_create_production_settings(session, project_id)
        metadata = settings.metadata_json or {}
        action = metadata.get("ai_action") if isinstance(metadata, dict) else None
        status = str(action.get("status") or "") if isinstance(action, dict) else ""
        message = str(action.get("message") or "") if isinstance(action, dict) else ""
        action_timeout = (
            _ai_action_exceeded_generation_timeout(action) if isinstance(action, dict) else False
        )
    completed = 0
    if script is not None:
        completed = 1
    if status == "completed":
        completed = 1
    counts = {
        "ideas": 1 if idea is not None else 0,
        "scripts": 1 if script is not None else 0,
        "scenes": 0,
        "shots": 0,
    }
    failed = status == "failed"
    cancelled = status == "cancelled"
    if action_timeout:
        detail = (
            "A geração demorou demais ou foi interrompida. Vou recarregar para liberar "
            "uma nova tentativa."
            f"\n{loading_status_message('script', counts)}"
        )
    elif cancelled:
        detail = (
            "Geração de roteiro cancelada pelo usuário."
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
            now=message or "Escrevendo roteiro cinematografico.",
        )
    else:
        detail = loading_status_message(
            "script",
            counts,
            now="Agora: roteiro pronto.",
        )
    return completed, 1, detail, completed >= 1 or failed or cancelled or action_timeout


async def _update_script_generation_progress(
    project_id: UUID,
    loading_dialog: Any,
    update_progress: Callable[[int, int, str], None],
    attempt: int = 0,
) -> None:
    completed, total, detail, terminal = await _script_generation_progress_state(project_id)
    update_progress(completed, total, detail)
    if terminal and hasattr(loading_dialog, "close"):
            safe_close_ui_element(loading_dialog)
            project_key = str(project_id)
            if completed >= total and not _completion_sound_played.get(project_key):
                _completion_sound_played[project_key] = True
                play_completion_sound()
            ui.navigate.reload()
            return
    ui.timer(
        script_progress_poll_interval(attempt + 1),
        lambda: _update_script_generation_progress(
            project_id,
            loading_dialog,
            update_progress,
            attempt + 1,
        ),
        once=True,
    )


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
        await _refresh_script_derivatives_from_ui(project_id, script_id)
        notify_user("Roteiro salvo.", "positive")
        if notify is None:
            play_completion_sound()
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
    should_resume_stale_script = (
        script is None
        and ai_action_name == "create_initial_script"
        and ai_status in {"queued", "running"}
        and ai_action_is_stale(ai_action)
    )
    if should_resume_stale_script:
        ui.timer(0.1, lambda: _schedule_initial_script_resume(project_id), once=True)
    generation_in_progress = script_generation_in_progress(
        script=script,
        ai_status=ai_status,
        should_resume_stale_script=should_resume_stale_script,
    )
    if generation_in_progress:
        generating_ideas = ai_action_name == "ideas"
        loading_title = (
            "Retomando roteiro"
            if should_resume_stale_script
            else ("Criando ideia base" if generating_ideas else "Gerando roteiro")
        )
        loading_message = (
            loading_status_message(
                "script",
                summary["counts"],
                now="Agora: retomando a criação do roteiro internamente.",
            )
            if should_resume_stale_script
            else loading_status_message(
                "ideas" if generating_ideas else "script",
                summary["counts"],
                now=str(
                    ai_action.get("message")
                    or "Agora: desenvolvendo o roteiro com base na ideia do projeto."
                ),
            )
        )

        async def cancel_script_generation() -> None:
            await cancel_initial_script_generation(project_id)
            safe_close_ui_element(loading_dialog)
            ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
            ui.navigate.reload()

        loading_dialog, update_script_progress = generation_progress_dialog(
            loading_title,
            1,
            "etapa",
            loading_message,
            on_cancel=cancel_script_generation,
        )
        loading_dialog.open()
        update_script_progress(0, 1, loading_message)
        ui.timer(
            2.0,
            lambda: _update_script_generation_progress(
                project_id,
                loading_dialog,
                update_script_progress,
            ),
            once=True,
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
    duration_dialog = None
    if script is None and not generation_in_progress:
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as duration_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(460px,92vw)] gap-4"
        ):
            ui.label("Duração do roteiro").classes("brand-type text-2xl font-bold")
            ui.label(
                "Escolha a duração alvo da história antes de gerar o roteiro."
            ).classes("text-sm text-[#8f9590] leading-6")
            duration_select = (
                ui.select(
                    SCRIPT_DURATION_OPTIONS,
                    label="Duração",
                    value=5,
                )
                .props("outlined suffix='min'")
                .classes("w-full")
            )
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Depois", on_click=duration_dialog.close).props("flat no-caps")
                ui.button(
                    "Continuar",
                    icon="auto_awesome",
                    on_click=lambda: _prepare_script_with_story_hooks(
                        project_id,
                        duration_select.value,
                        duration_dialog,
                        loading_dialog_factory,
                    ),
                ).props("unelevated no-caps").classes("acid-bg rounded-xl font-semibold")
        ui.timer(0.4, duration_dialog.open, once=True)
    section_title(
        "Roteiro",
        "Edite e revise o roteiro cinematográfico que orienta as próximas etapas.",
        "Editar roteiro" if edit_dialog is not None else "Gerar roteiro",
        edit_dialog.open if edit_dialog is not None else (
            duration_dialog.open if duration_dialog is not None else None
        ),
    )
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("flex-1 gap-4"):
            if script is None:
                ui.label(
                    text_generation_cost_text(
                        summary,
                        "generate_script",
                        SCRIPT_TEXT_ESTIMATED_TOKENS,
                        "ideia e roteiro",
                    )
                ).classes("text-xs text-[#8d938e]")
            if script is None and ai_status == "failed":
                async def cancel_retry_generation() -> None:
                    await cancel_initial_script_generation(project_id)
                    safe_close_ui_element(retry_loading_dialog)
                    ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
                    ui.navigate.reload()

                retry_loading_dialog, update_retry_progress = generation_progress_dialog(
                    "Retomando roteiro",
                    1,
                    "etapa",
                    loading_status_message(
                        "script",
                        summary["counts"],
                        now="Agora: tentando criar o roteiro inicial novamente.",
                    ),
                    on_cancel=cancel_retry_generation,
                )

                async def retry_initial_script() -> None:
                    _completion_sound_played.pop(str(project_id), None)
                    await retry_initial_script_from_ui(project_id, retry_loading_dialog)
                    update_retry_progress(
                        0,
                        1,
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
                        once=True,
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




