import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, cast
from uuid import UUID, uuid4

from nicegui import background_tasks, ui
from redis.asyncio import from_url
from sqlalchemy import select

from app.config.settings import get_settings
from app.core.enums import GenerationJobStatus, GenerationJobType
from app.database.session import AsyncSessionLocal
from app.storytelling.models import Script
from app.ui.shared.assistant_state import safe_client_navigation
from app.ui.shared.generation_progress import (
    OPERATION_CANCELLED_MESSAGE,
    generation_progress_dialog,
    mark_dialog_task_cancelable,
)
from app.ui.shared.page_config import (
    friendly_ai_error,
    play_completion_sound,
    safe_close_ui_element,
    show_ai_error_popup,
)
from app.ui.workspace.visual_reference_state import (
    ACTIVE_VISUAL_REFERENCE_JOB_STATUSES,
    VisualReferencePollStatus,
    visual_reference_batch_progress,
)
from app.ui.workspace.visual_reference_state import (
    visual_reference_generation_key as _visual_reference_generation_key,
)
from app.ui.workspace.visual_reference_state import (
    visual_reference_poll_decision as _visual_reference_poll_decision,
)
from app.ui.workspace.visual_reference_state import (
    visual_reference_resume_keys as _visual_reference_resume_keys,
)
from app.video_generation.models import GenerationJob
from app.visual_bible.image_generation import (
    _strip_view_instructions,
    enqueue_visual_reference_generation,
    visual_reference_generation_issue,
)
from app.visual_bible.manual_references import (
    ManualReferenceError,
    delete_visual_profile,
    delete_visual_reference,
    remove_visual_exclusion,
    save_manual_visual_reference,
)
from app.visual_bible.models import VisualReference
from app.visual_bible.profiles import _character_profile, _location_profile
from app.visual_bible.prompt_balance import (
    CHARACTER_PROMPT_MAX_WORDS,
    CHARACTER_PROMPT_MIN_WORDS,
    LOCATION_PROMPT_MAX_WORDS,
    LOCATION_PROMPT_MIN_WORDS,
    VISUAL_PROMPT_MAX_WORDS,
    VISUAL_PROMPT_MIN_WORDS,
    prompt_word_count,
    repair_portuguese_mojibake,
)
from app.visual_bible.reference_planning import TargetKind, plan_visual_references
from app.visual_bible.service import generate_visual_bible

VISUAL_REFERENCE_POLL_INTERVAL_SECONDS = 2.0
VISUAL_REFERENCE_STALLED_AFTER = timedelta(seconds=20)
VISUAL_REFERENCE_STALLED_WITH_WORKER_AFTER = timedelta(minutes=5)


def _all_visual_references_generated(
    characters: list[Any],
    locations: list[Any],
    references: list[Any],
) -> bool:
    completed, _ = _visual_reference_resume_keys(references, [])
    expected: set[tuple[str, str, str]] = set()
    for target_kind, targets in (("character", characters), ("location", locations)):
        for target in targets:
            plan = plan_visual_references(
                cast(TargetKind, target_kind),
                target.id,
                {"canonical_prompt": "referência visual"},
            )
            expected.update(
                _visual_reference_generation_key(target_kind, target.id, item.view_type)
                for item in plan.items
            )
    return bool(expected) and expected.issubset(completed)


async def _visual_reference_generation_poll_state(
    project_id: UUID,
    known_reference_ids: frozenset[UUID],
) -> VisualReferencePollStatus:
    async with AsyncSessionLocal() as session:
        reference_result = await session.execute(
            select(VisualReference).where(
                VisualReference.project_id == project_id,
                VisualReference.status != "rejected",
            )
        )
        job_result = await session.execute(
            select(GenerationJob)
            .where(
                GenerationJob.project_id == project_id,
                GenerationJob.job_type == GenerationJobType.IMAGE,
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(50)
        )
    references = [
        reference
        for reference in reference_result.scalars()
        if reference.target_kind != "character" or reference.view_type == "full_body"
    ]
    jobs = [
        job
        for job in job_result.scalars()
        if str((job.request_payload or {}).get("operation") or "") == "generate_visual_reference"
    ]
    has_new_reference, has_active_generation = _visual_reference_poll_decision(
        known_reference_ids,
        references,
        jobs,
    )
    batch_jobs = _latest_visual_reference_job_batch(jobs)
    worker_alive = await _visual_reference_worker_alive()
    error = _visual_reference_batch_error(
        batch_jobs,
        worker_alive=worker_alive,
        references=references,
    )
    # Progresso do lote para o pop-up: total = referências solicitadas no lote
    # mais recente; concluídas = as desse lote que já têm asset persistido.
    batch_completed, batch_total, active_kind = 0, 0, ""
    if batch_jobs:
        completed_keys, active_keys = _visual_reference_resume_keys(references, batch_jobs)
        requested_keys = {
            _visual_reference_generation_key(
                (job.request_payload or {}).get("target_kind"),
                (job.request_payload or {}).get("target_id"),
                (job.request_payload or {}).get("view_type"),
            )
            for job in batch_jobs
        }
        batch_completed, batch_total, active_kind = visual_reference_batch_progress(
            completed_keys, active_keys, requested_keys
        )
    return VisualReferencePollStatus(
        has_new_reference,
        has_active_generation,
        error,
        completed=batch_completed,
        total=batch_total,
        active_kind=active_kind,
    )


async def _visual_reference_worker_alive() -> bool:
    settings = get_settings()
    redis = from_url(settings.redis_url)
    try:
        pattern = f"{settings.worker_queue_name}:heartbeat:*"
        async for key in redis.scan_iter(match=pattern, count=20):
            if await redis.ttl(key) > 0:
                return True
        return False
    finally:
        await redis.aclose()


def _latest_visual_reference_job_batch(jobs: list[Any]) -> list[Any]:
    if not jobs:
        return []
    latest = jobs[0]
    attempt_key = str((latest.request_payload or {}).get("attempt_key") or "")
    match = re.match(r"^(generate-[0-9a-fA-F-]{36})-", attempt_key)
    if not match:
        return [latest]
    batch_prefix = f"{match.group(1)}-"
    return [
        job
        for job in jobs
        if str((job.request_payload or {}).get("attempt_key") or "").startswith(batch_prefix)
    ]


def _visual_reference_batch_error(
    jobs: list[Any],
    *,
    now: datetime | None = None,
    worker_alive: bool = False,
    references: list[Any] | None = None,
) -> str | None:
    # Um FAILED só é erro real se o alvo do job NÃO tem referência com asset —
    # quando o mesmo alvo foi recuperado (retry do worker ou geração seguinte
    # do lote), a falha antiga já cumpriu seu papel e não pode reaparecer como
    # popup em cada poll (bug real: lote 100% nos cards + aviso eterno).
    recovered_keys = {
        _visual_reference_generation_key(
            getattr(reference, "target_kind", None),
            getattr(reference, "target_id", None),
            getattr(reference, "view_type", None),
        )
        for reference in (references or [])
        if getattr(reference, "asset_id", None) is not None
    }
    failed = next(
        (
            job
            for job in jobs
            if job.status == GenerationJobStatus.FAILED
            and _visual_reference_generation_key(
                (job.request_payload or {}).get("target_kind"),
                (job.request_payload or {}).get("target_id"),
                (job.request_payload or {}).get("view_type"),
            )
            not in recovered_keys
        ),
        None,
    )
    if failed is not None:
        return str(failed.error or "A Meta não concluiu a geração da referência visual.")
    running = any(job.status == GenerationJobStatus.RUNNING for job in jobs)
    pending = [job for job in jobs if job.status == GenerationJobStatus.PENDING]
    current_time = now or datetime.now(UTC)
    stalled_after = (
        VISUAL_REFERENCE_STALLED_WITH_WORKER_AFTER
        if worker_alive
        else VISUAL_REFERENCE_STALLED_AFTER
    )
    latest_activity = max(
        (
            activity
            for job in jobs
            for activity in (
                getattr(job, "updated_at", None),
                getattr(job, "started_at", None),
                getattr(job, "completed_at", None),
                getattr(job, "created_at", None),
            )
            if activity is not None
        ),
        default=None,
    )
    batch_has_recent_progress = bool(
        latest_activity is not None and current_time - latest_activity < stalled_after
    )
    if (
        not running
        and pending
        and not batch_has_recent_progress
        and all(current_time - job.created_at >= stalled_after for job in pending)
    ):
        return (
            "A fila de referências visuais não avançou no tempo esperado. O worker pode estar "
            "parado ou o perfil de navegador da Meta pode estar bloqueado por uma execução "
            "anterior. Reinicie a aplicação e tente novamente."
        )
    return None


async def _visual_reference_generation_poll_once(
    project_id: UUID,
    known_reference_ids: frozenset[UUID],
) -> VisualReferencePollStatus:
    try:
        return await _visual_reference_generation_poll_state(project_id, known_reference_ids)
    except Exception:
        # Uma falha transitória de leitura não deve encerrar o acompanhamento da geração.
        return VisualReferencePollStatus(False, True)


def _visual_reference_user_error(error: str) -> str:
    normalized = error.casefold()
    if "user-closed-browser" in normalized:
        return (
            "O navegador da automação foi fechado manualmente e o fechamento foi "
            "respeitado — nenhuma geração reabre o navegador por conta própria. "
            "Para retomar, abra Ajustes e use “Autorizar Meta”/“Autorizar Vibes” "
            "ou dispare uma nova geração."
        )
    if any(
        marker in normalized
        for marker in (
            "não autorizado",
            "nao autorizado",
            "conclua o login",
            "login required",
            "sign in",
            "sessão expirada",
            "sessao expirada",
        )
    ):
        return (
            "A sessão da Meta ou do Vibes não está autorizada. Abra Ajustes, selecione "
            "“Autorizar Meta” ou “Autorizar Vibes”, conclua o login e tente novamente."
        )
    if "meta ai recusou o prompt" in normalized:
        return (
            "A Meta AI recusou gerar esta referência visual — normalmente por um traço "
            "físico sensível no perfil (armas, ferimentos, sangue). A resposta completa "
            "está nos detalhes técnicos. Revise as características marcantes do perfil "
            "canônico ou envie uma referência manual e gere novamente."
        )
    if "page.goto" in normalized or "navegação" in normalized:
        return (
            "A página do Meta AI não respondeu a tempo (rede instável ou site lento). "
            "O job será reprocessado automaticamente; se o aviso se repetir, verifique "
            "sua conexão e gere novamente."
        )
    return error


def _show_visual_reference_error(client: Any, error: str) -> None:
    if getattr(client, "is_deleted", False):
        return
    with client:
        show_ai_error_popup(
            _visual_reference_user_error(error),
            title="Falha ao gerar referências visuais",
            details=error,
        )


async def _watch_visual_reference_generation(
    project_id: UUID,
    known_reference_ids: frozenset[UUID],
    client: Any,
    *,
    poll_state: Callable[
        [UUID, frozenset[UUID]], Awaitable[VisualReferencePollStatus]
    ] = _visual_reference_generation_poll_once,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    navigate: Callable[[Any, str | None], None] = safe_client_navigation,
    show_error: Callable[[Any, str], None] | None = None,
    show_success: Callable[[Any], None] | None = None,
    on_progress: Callable[[Any, VisualReferencePollStatus], None] | None = None,
    on_partial_error: Callable[[Any, str], None] | None = None,
) -> None:
    """Acompanha o worker sem criar timers ligados a elementos da pagina.

    ``show_error`` é None no watcher "nu" (iniciado em todo render da página):
    nesse modo o watcher NÃO exibe popup nem recarrega em erro terminal — o
    job FAILED já está no card, e recarregar re-dispararia o watcher nu num
    loop infinito de popup. Só o watcher de acompanhamento (show_completion)
    passa um show_error real e eleva o erro a popup.
    """

    _error_notified: dict[str, bool] = {}
    while not getattr(client, "is_deleted", False):
        await sleep(VISUAL_REFERENCE_POLL_INTERVAL_SECONDS)
        if getattr(client, "is_deleted", False):
            return
        status = await poll_state(
            project_id,
            known_reference_ids,
        )
        # Erro com o lote AINDA EM ANDAMENTO não encerra o acompanhamento: o
        # worker processa o lote em série e os jobs restantes continuam
        # gerando (bug real: 2 falhas rápidas no lote fechavam o pop-up com
        # 9+ referências ainda na fila — o usuário perdia o acompanhamento e
        # as referências só apareciam "do nada" nos cards). O erro vira aviso
        # e o watcher segue até o fim do lote; o erro final só é elevado a
        # popup quando não há mais geração ativa.
        if status.error and not status.has_active_generation:
            # O watcher "nu" (iniciado em todo render da página, sem
            # show_error) NÃO deve exibir popup nem recarregar num erro
            # terminal: o job FAILED já está refletido no card, e recarregar
            # re-dispara o watcher nu → loop infinito de popup de erro a cada
            # load (bug real: recusa da Meta reaparecia eternamente). Só o
            # watcher de acompanhamento (show_completion=True) eleva o erro a
            # popup e recarrega para mostrar o que succeeded.
            if show_error is not None:
                show_error(client, status.error)
                # Lote encerrado COM erro: recarrega a página mesmo assim — as
                # referências que succeeded precisam aparecer nos cards.
                navigate(client, None)
            return
        if status.error and status.has_active_generation and not _error_notified.get(
            str(status.error)
        ):
            _error_notified[str(status.error)] = True
            if on_partial_error is not None:
                on_partial_error(client, status.error)
        if status.has_active_generation:
            if on_progress is not None and status.total > 0:
                on_progress(client, status)
            continue
        if status.has_new_reference:
            if show_success is not None:
                show_success(client)
            navigate(client, None)
            return
        if show_success is not None:
            show_success(client)
            navigate(client, None)
        return


def _start_visual_reference_generation_watch(
    project_id: UUID,
    known_reference_ids: frozenset[UUID],
    client: Any,
    *,
    show_success: Callable[[Any], None] | None = None,
    show_error: Callable[[Any, str], None] | None = None,
    on_progress: Callable[[Any, VisualReferencePollStatus], None] | None = None,
    on_partial_error: Callable[[Any, str], None] | None = None,
) -> asyncio.Task[Any]:
    """Start a page-independent watcher for a generation that was just queued."""

    watch = (
        _watch_visual_reference_generation(project_id, known_reference_ids, client)
        if show_success is None and show_error is None and on_progress is None
        else _watch_visual_reference_generation(
            project_id,
            known_reference_ids,
            client,
            show_success=show_success,
            show_error=show_error or _show_visual_reference_error,
            on_progress=on_progress,
            on_partial_error=on_partial_error,
        )
    )
    task = background_tasks.create(
        watch,
        name=f"visual-reference-poll-{project_id}-{client.id}-{uuid4()}",
    )

    def cancel_task() -> None:
        task.cancel()

    client.on_delete(cancel_task)
    return task


def _cancel_bare_watch_on_completion(
    bare_watch_task: list[asyncio.Task[Any] | None],
    *,
    show_completion: bool,
) -> None:
    """Cancela o watcher "nu" quando um watcher de acompanhamento inicia.

    O watcher nu (iniciado no render da página) e o watcher de acompanhamento
    (show_completion=True, iniciado pelo botão de geração) ambos fazem
    navigate() ao concluir. Sem cancelar o nu, o reload duplo derruba o
    pop-up de progresso assim que a primeira referência é gerada.
    """
    if not show_completion:
        return
    task = bare_watch_task[0]
    if task is not None and not task.done():
        task.cancel()
    bare_watch_task[0] = None


def render_visual_bible_area(project_id: UUID, summary: dict[str, Any]) -> None:
    characters = list(summary.get("characters") or [])
    locations = list(summary.get("locations") or [])
    references = list(summary.get("visual_refs") or [])
    assets = {asset.id: asset for asset in summary.get("assets") or []}
    generation_issue = visual_reference_generation_issue()
    known_reference_ids = frozenset(reference.id for reference in references)
    client = ui.context.client

    profile_dialog, _update_profile_progress = generation_progress_dialog(
        "Criando Bíblia Visual",
        1,
        "etapa",
        "Agora: criando os perfis de personagens e locais a partir do roteiro.",
    )
    reference_dialog, _update_reference_progress = generation_progress_dialog(
        "Gerando referências visuais",
        1,
        "referência",
        "Agora: gerando as imagens canônicas de personagens e locais.",
    )

    def show_reference_success(current_client: Any) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        with current_client:
            safe_close_ui_element(reference_dialog)
            ui.notify("Referências visuais geradas com sucesso.", color="positive")
            play_completion_sound()

    def show_reference_error(current_client: Any, error: str) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        with current_client:
            safe_close_ui_element(reference_dialog)
            show_ai_error_popup(
                _visual_reference_user_error(error),
                title="Falha ao gerar referências visuais",
                details=error,
            )

    def show_reference_progress(current_client: Any, status: VisualReferencePollStatus) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        # status.total == 0: o job do lote ainda não foi persistido/observado —
        # mantém o texto inicial do diálogo sem sobrescrever com "0/0".
        if status.total <= 0:
            return
        with current_client:
            _update_reference_progress(
                status.completed,
                status.total,
                (
                    f"Agora: gerando a imagem de {status.active_kind or 'referência'} "
                    "na conversa do Meta AI."
                ),
            )

    def show_reference_partial_error(current_client: Any, error: str) -> None:
        if getattr(current_client, "is_deleted", False):
            return
        with current_client:
            ui.notify(
                "Falha parcial no lote: "
                f"{_visual_reference_user_error(error)[:200]} "
                "As demais referências continuam sendo geradas.",
                color="warning",
                timeout=10000,
                close_button=True,
            )

    # Watcher "nu" iniciado no render da página (retomada de geração em
    # andamento). Quando o usuário dispara uma geração pelo botão, um SEGUNDO
    # watcher (show_completion=True) é criado; sem cancelar o nu, os dois
    # fazem navigate() assim que a PRIMEIRA referência é gerada, derrubando o
    # pop-up de progresso e deixando o resto do lote gerar em silêncio.
    bare_watch_task: list[asyncio.Task[Any] | None] = [None]

    def start_generation_watch(*, show_completion: bool = False) -> None:
        _cancel_bare_watch_on_completion(bare_watch_task, show_completion=show_completion)
        _start_visual_reference_generation_watch(
            project_id,
            known_reference_ids,
            client,
            show_success=show_reference_success if show_completion else None,
            show_error=show_reference_error if show_completion else None,
            on_progress=show_reference_progress if show_completion else None,
            on_partial_error=show_reference_partial_error if show_completion else None,
        )

    with ui.row().classes("w-full items-center justify-between gap-3"):
        with ui.column().classes("gap-1"):
            ui.label("Bíblia Visual").classes("text-3xl font-bold")
            ui.label("Personagens, locais e referências canônicas versionadas.").classes(
                "text-sm text-slate-400"
            )
        ui.badge(f"{len(references)} referências").classes("bg-slate-800")

    async def restore_exclusion(key: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await remove_visual_exclusion(session, project_id, key)
            ui.notify(
                "Exclusão removida. O card volta na próxima geração da Bíblia Visual.",
                color="positive",
            )
            ui.navigate.reload()
        except Exception as exc:
            show_ai_error_popup(friendly_ai_error(exc), details=str(exc))

    exclusions = list(summary.get("visual_exclusions") or [])
    if exclusions:
        with ui.expansion(
            f"Exclusões manuais ({len(exclusions)})",
            icon="delete_sweep",
        ).classes("w-full border border-slate-800 rounded-lg text-sm"):
            ui.label(
                "Perfis excluídos manualmente. Eles não voltam ao gerar a Bíblia "
                "Visual novamente. Use \"Restaurar\" para permitir o retorno na "
                "próxima geração."
            ).classes("text-xs text-slate-400")
            for entry in exclusions:
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(str(entry.get("label") or entry.get("key") or "")).classes(
                        "text-sm text-slate-200"
                    )
                    exclusion_key = str(entry.get("key") or "")
                    ui.button(
                        "Restaurar",
                        icon="undo",
                        on_click=partial(restore_exclusion, exclusion_key),
                    ).props("flat dense no-caps").classes("text-slate-300")

    if not characters and not locations:
        with ui.card().classes("w-full border border-amber-800 bg-amber-950/30 p-6 gap-3"):
            ui.label("A Bíblia Visual ainda não foi criada.").classes(
                "text-xl font-semibold text-amber-100"
            )
            ui.label(
                "Gere os perfis de personagens e locais a partir do roteiro para poder "
                "criar e aprovar as referências visuais."
            ).classes("text-sm text-amber-200")

            async def generate_profiles() -> None:
                profile_dialog.open()
                mark_dialog_task_cancelable(profile_dialog)
                try:
                    async with AsyncSessionLocal() as session:
                        script = await session.get(Script, summary["script"].id)
                        if script is None:
                            raise ValueError("roteiro não encontrado")
                        result = await generate_visual_bible(session, project_id, script.id)
                        if result is None:
                            raise ValueError("não foi possível criar os perfis")
                    ui.notify("Bíblia Visual criada.", color="positive")
                    play_completion_sound()
                    ui.navigate.reload()
                except asyncio.CancelledError:
                    ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
                except Exception as exc:
                    show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
                finally:
                    safe_close_ui_element(profile_dialog)

            ui.button(
                "Criar Bíblia Visual",
                icon="auto_awesome",
                on_click=generate_profiles,
            ).props("unelevated no-caps")
        return

    if generation_issue:
        with ui.card().classes("w-full border border-amber-800 bg-amber-950/30 p-4 gap-2"):
            ui.label("Geração de imagens indisponível").classes(
                "text-base font-semibold text-amber-100"
            )
            ui.label(generation_issue).classes("text-sm text-amber-200")

    prompt_inputs: list[tuple[str, Any, Any]] = []

    async def generate_all_references() -> None:
        reference_dialog.open()
        mark_dialog_task_cancelable(reference_dialog)
        keep_dialog_open = False
        try:
            generation_batch = uuid4()
            queued = 0
            requested = 0
            already_complete = 0
            already_active = 0
            async with AsyncSessionLocal() as session:
                reference_result = await session.execute(
                    select(VisualReference).where(
                        VisualReference.project_id == project_id,
                        VisualReference.status != "rejected",
                    )
                )
                job_result = await session.execute(
                    select(GenerationJob).where(
                        GenerationJob.project_id == project_id,
                        GenerationJob.job_type == GenerationJobType.IMAGE,
                        GenerationJob.status.in_(ACTIVE_VISUAL_REFERENCE_JOB_STATUSES),
                    )
                )
                completed_keys, active_keys = _visual_reference_resume_keys(
                    list(reference_result.scalars()),
                    list(job_result.scalars()),
                )
                for kind, target, prompt_input in prompt_inputs:
                    canonical_prompt = repair_portuguese_mojibake(prompt_input.value).strip()
                    if not canonical_prompt:
                        raise ValueError(f"Informe o prompt visual de {target.name}.")
                    profile = {
                        **dict(target.canonical_profile or {}),
                        "canonical_prompt": canonical_prompt,
                    }
                    plan = plan_visual_references(cast(TargetKind, kind), target.id, profile)
                    for item in plan.items:
                        requested += 1
                        item_key = _visual_reference_generation_key(
                            kind,
                            target.id,
                            item.view_type,
                        )
                        if item_key in completed_keys:
                            already_complete += 1
                            continue
                        if item_key in active_keys:
                            already_active += 1
                            continue
                        decision = await enqueue_visual_reference_generation(
                            session,
                            project_id,
                            kind,
                            target.id,
                            item.view_type,
                            prompt_override=item.prompt,
                            attempt_key=(
                                f"generate-{generation_batch}-{kind}-{target.id}-{item.view_type}"
                            ),
                        )
                        queued += int(decision.should_dispatch)
                        active_keys.add(item_key)
            if queued:
                details = [f"{queued} referência(s) pendente(s) enviada(s) ao worker"]
                if already_complete:
                    details.append(f"{already_complete} já pronta(s)")
                if already_active:
                    details.append(f"{already_active} já em andamento")
                ui.notify("; ".join(details) + ".", color="positive")
            elif already_active:
                ui.notify(
                    f"Nenhuma geração duplicada: {already_active} referência(s) já estão "
                    "em andamento.",
                    color="info",
                )
            elif requested and already_complete == requested:
                ui.notify("Todas as referências visuais já estão prontas.", color="positive")
            else:
                ui.notify("Não há referências pendentes para gerar.", color="info")
            if queued or already_active:
                keep_dialog_open = True
                start_generation_watch(show_completion=True)
        except asyncio.CancelledError:
            ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
        except Exception as exc:
            show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
        finally:
            if not keep_dialog_open:
                safe_close_ui_element(reference_dialog)

    if not _all_visual_references_generated(characters, locations, references):
        with ui.row().classes("w-full items-center justify-end gap-3 mt-4"):
            generate_all_button = ui.button(
                "Gerar todas as referências",
                icon="auto_awesome",
                on_click=generate_all_references,
            ).props("unelevated no-caps disable" if generation_issue else "unelevated no-caps")
            if generation_issue:
                generate_all_button.tooltip(generation_issue)

    for target_kind, targets in (("character", characters), ("location", locations)):
        ui.label("Personagens" if target_kind == "character" else "Locais").classes(
            "text-xl font-semibold mt-4"
        )
        with ui.element("div").classes("grid grid-cols-1 xl:grid-cols-2 gap-4 w-full"):
            for target in targets:
                target_refs = [
                    item
                    for item in references
                    if item.target_kind == target_kind and item.target_id == target.id
                ]
                prompt_input = _target_card(
                    project_id,
                    target_kind,
                    target,
                    target_refs,
                    assets,
                    start_generation_watch=start_generation_watch,
                    reference_dialog=reference_dialog,
                    generation_issue=generation_issue,
                )
                prompt_inputs.append((target_kind, target, prompt_input))

    bare_watch_task[0] = _start_visual_reference_generation_watch(
        project_id, known_reference_ids, client
    )


def _target_card(
    project_id: UUID,
    target_kind: str,
    target: Any,
    references: list[Any],
    assets: dict[UUID, Any],
    *,
    start_generation_watch: Callable[..., None],
    reference_dialog: Any,
    generation_issue: str = "",
) -> Any:
    with ui.card().classes("w-full border border-slate-800 bg-slate-950"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label(str(target.name)).classes("text-lg font-semibold")
                ui.label(str(getattr(target, "role", "") or target_kind)).classes(
                    "text-xs text-slate-400"
                )

            async def delete_profile_card() -> None:
                confirm = ui.dialog()
                with confirm, ui.card().classes("gap-3"):
                    ui.label(f"Excluir {target.name}?").classes("text-base font-semibold")
                    ui.label(
                        "O perfil e suas referências visuais serão removidos da Bíblia "
                        "Visual e os arquivos apagados. O card NÃO volta ao gerar a "
                        "Bíblia Visual novamente (pode ser restaurado na seção "
                        "\"Exclusões manuais\")."
                    ).classes("text-xs text-slate-400")
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancelar", on_click=confirm.close).props("flat no-caps")

                        async def _confirm_profile_delete() -> None:
                            confirm.close()
                            try:
                                async with AsyncSessionLocal() as session:
                                    await delete_visual_profile(
                                        session,
                                        project_id,
                                        target_kind,
                                        target.id,
                                    )
                                ui.notify(
                                    f"{target.name} foi excluído da Bíblia Visual.",
                                    color="positive",
                                )
                                ui.navigate.reload()
                            except Exception as exc:
                                show_ai_error_popup(
                                    friendly_ai_error(exc), details=str(exc)
                                )

                        ui.button(
                            "Excluir",
                            icon="delete",
                            on_click=_confirm_profile_delete,
                        ).props("unelevated no-caps").classes("bg-red-900 text-white")
                confirm.open()

            ui.button(
                icon="delete",
                on_click=delete_profile_card,
            ).props("flat dense round").classes("text-red-300 hover:bg-red-950").tooltip(
                "Excluir card da Bíblia Visual"
            )

        canonical_prompt = _balanced_target_prompt(target_kind, target)
        prompt_input = (
            ui.textarea(
                "Prompt can\u00f4nico base",
                value=canonical_prompt,
            )
            .props("outlined stack-label rows=6")
            .classes("w-full visual-prompt-input")
        )
        word_counter = ui.label(_prompt_word_counter(canonical_prompt, target_kind)).classes(
            "text-xs text-slate-400"
        )
        with ui.expansion("Prompt final enviado \u00e0 Meta", icon="visibility").classes(
            "w-full border border-slate-800 rounded-lg text-sm"
        ):
            final_prompt = ui.label(
                _final_reference_prompt(target_kind, target.id, canonical_prompt)
            ).classes("whitespace-pre-wrap text-sm text-slate-300 leading-6 p-2")

        def update_prompt_preview(event: Any) -> None:
            value = str(event.value or "").strip()
            word_counter.set_text(_prompt_word_counter(value, target_kind))
            final_prompt.set_text(_final_reference_prompt(target_kind, target.id, value))

        prompt_input.on_value_change(update_prompt_preview)

        grid_classes = (
            "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 w-full"
            if target_kind == "character"
            else "grid grid-cols-1 xl:grid-cols-2 gap-5 w-full"
        )
        image_aspect = "aspect-[9/16]"
        with ui.element("div").classes(grid_classes):
            for reference in references:
                asset = assets.get(reference.asset_id)

                async def remove_reference(ref: Any = reference) -> None:
                    confirm = ui.dialog()
                    with confirm, ui.card().classes("gap-3"):
                        ui.label("Remover esta referência visual?").classes(
                            "text-base font-semibold"
                        )
                        ui.label(
                            "A referência será marcada como removida e o arquivo "
                            "excluído do armazenamento."
                        ).classes("text-xs text-slate-400")
                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("Cancelar", on_click=confirm.close).props(
                                "flat no-caps"
                            )

                            async def _confirm_delete(removed: Any = ref) -> None:
                                confirm.close()
                                try:
                                    async with AsyncSessionLocal() as session:
                                        await delete_visual_reference(
                                            session,
                                            project_id,
                                            removed.id,
                                        )
                                    ui.notify(
                                        "Referência removida.",
                                        color="positive",
                                    )
                                    ui.navigate.reload()
                                except Exception as exc:
                                    show_ai_error_popup(
                                        friendly_ai_error(exc),
                                        details=str(exc),
                                    )

                            ui.button(
                                "Remover",
                                icon="delete",
                                on_click=_confirm_delete,
                            ).props("unelevated no-caps").classes(
                                "bg-red-900 text-white"
                            )
                    confirm.open()

                with ui.card().classes("p-3 gap-3 bg-slate-900 min-w-0"):
                    if asset is not None:
                        image_url = f"/api/v1/assets/{asset.id}/content"
                        open_image = partial(_open_image_from_event, url=image_url)
                        with (
                            ui.element("div")
                            .classes(
                                f"relative w-full {image_aspect} rounded-lg overflow-hidden "
                                "bg-black cursor-zoom-in group"
                            )
                            .on("click", open_image)
                        ):
                            ui.image(image_url).classes(
                                "absolute inset-0 w-full h-full object-contain"
                            )
                            with ui.element("div").classes(
                                "absolute inset-x-0 top-0 flex justify-between p-2 "
                                "bg-gradient-to-b from-black/70 to-transparent "
                                "opacity-0 group-hover:opacity-100 transition-opacity"
                            ):
                                ui.icon("zoom_in").classes("text-white text-2xl")
                                ui.button(
                                    icon="delete",
                                    on_click=remove_reference,
                                ).props("flat dense round").classes(
                                    "text-red-300 bg-black/50"
                                ).tooltip("Excluir referência")
                    with ui.row().classes("w-full items-center justify-end gap-1"):
                        if asset is not None:
                            ui.button(
                                "Visualizar imagem",
                                icon="open_in_full",
                                on_click=open_image,
                            ).props("flat dense no-caps")

                        ui.button(
                            "Remover",
                            icon="delete",
                            on_click=remove_reference,
                        ).props("flat dense no-caps").classes("text-red-300")

                        async def regenerate(ref: Any = reference) -> None:
                            reference_dialog.open()
                            mark_dialog_task_cancelable(reference_dialog)
                            try:
                                # INC-08: deriva o override do prompt canônico
                                # BASE (metadata ou prompt salvo sem as
                                # instruções técnicas de vista), nunca do
                                # prompt final acumulado entre regenerações.
                                metadata = dict(ref.metadata_json or {})
                                base_prompt = str(
                                    metadata.get("canonical_base_prompt") or ""
                                ).strip()
                                if not base_prompt:
                                    base_prompt = _strip_view_instructions(
                                        str(ref.prompt or ""), ref.target_kind
                                    )
                                async with AsyncSessionLocal() as session:
                                    await enqueue_visual_reference_generation(
                                        session,
                                        project_id,
                                        ref.target_kind,
                                        ref.target_id,
                                        ref.view_type,
                                        prompt_override=repair_portuguese_mojibake(base_prompt),
                                        attempt_key=f"regenerate-{uuid4()}",
                                    )
                                start_generation_watch(show_completion=True)
                            except asyncio.CancelledError:
                                safe_close_ui_element(reference_dialog)
                                ui.notify(OPERATION_CANCELLED_MESSAGE, color="warning")
                            except Exception as exc:
                                safe_close_ui_element(reference_dialog)
                                show_ai_error_popup(friendly_ai_error(exc), details=str(exc))

                        regenerate_button = ui.button(
                            "Gerar novamente",
                            icon="refresh",
                            on_click=regenerate,
                        ).props(
                            "flat dense no-caps disable"
                            if generation_issue
                            else "flat dense no-caps"
                        )
                        regenerate_button.tooltip(generation_issue or "Regenerar")

            async def upload_manual_image() -> None:
                upload_dialog = ui.dialog()
                status_label: dict[str, Any] = {"element": None}

                async def handle_upload(event: Any) -> None:
                    # NiceGUI 3.x: o evento expõe `file` (FileUpload), com leitura
                    # async; o antigo `event.content` síncrono não existe mais.
                    file = getattr(event, "file", None)
                    if file is None:
                        ui.notify("Selecione uma imagem antes de salvar.", color="warning")
                        return
                    data = await file.read()
                    try:
                        async with AsyncSessionLocal() as session:
                            await save_manual_visual_reference(
                                session,
                                project_id,
                                target_kind,
                                target.id,
                                "full_body",
                                filename=str(getattr(file, "name", "") or "imagem"),
                                content_type=str(getattr(file, "content_type", "") or ""),
                                data=data,
                                target=target,
                                source_artifact_id=target.artifact_id,
                            )
                        safe_close_ui_element(upload_dialog)
                        ui.notify(
                            "Referência enviada e definida como canônica.",
                            color="positive",
                        )
                        ui.navigate.reload()
                    except ManualReferenceError as exc:
                        element = status_label["element"]
                        if element is not None:
                            element.set_text(str(exc))
                        else:
                            ui.notify(str(exc), color="warning")
                    except Exception as exc:
                        safe_close_ui_element(upload_dialog)
                        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))

                with upload_dialog, ui.card().classes("w-[min(520px,92vw)] gap-3"):
                    ui.label(f"Enviar imagem para {target.name}").classes(
                        "text-base font-semibold"
                    )
                    ui.label(
                        "A imagem enviada substitui a referência atual deste "
                        + ("personagem." if target_kind == "character" else "local.")
                    ).classes("text-xs text-slate-400")
                    ui.upload(
                        on_upload=handle_upload,
                        auto_upload=True,
                    ).props(
                        'accept="image/png,image/jpeg,image/webp" flat bordered '
                        'label="Escolher imagem" color=slate'
                    ).classes("w-full")
                    status_label["element"] = ui.label("").classes("text-xs text-red-300")
                    with ui.row().classes("w-full justify-end"):
                        ui.button("Fechar", on_click=upload_dialog.close).props("flat no-caps")
                upload_dialog.open()

            with ui.row().classes("w-full items-center justify-end gap-1 mt-1"):
                ui.button(
                    "Enviar imagem manual",
                    icon="upload",
                    on_click=upload_manual_image,
                ).props("flat dense no-caps").classes("text-slate-300")
    return prompt_input


def _balanced_target_prompt(target_kind: str, target: Any) -> str:
    profile = {**dict(target.canonical_profile or {}), "name": str(target.name)}
    if target_kind == "character":
        profile.setdefault("role", str(getattr(target, "role", "") or "personagem"))
        normalized = _character_profile(profile)
    else:
        normalized = _location_profile(profile)
    return str(normalized.get("canonical_prompt") or "").strip()


def _prompt_word_counter(prompt: str, target_kind: str = "") -> str:
    count = prompt_word_count(repair_portuguese_mojibake(prompt))
    if target_kind == "character":
        minimum, maximum = CHARACTER_PROMPT_MIN_WORDS, CHARACTER_PROMPT_MAX_WORDS
    elif target_kind == "location":
        minimum, maximum = LOCATION_PROMPT_MIN_WORDS, LOCATION_PROMPT_MAX_WORDS
    else:
        minimum, maximum = VISUAL_PROMPT_MIN_WORDS, VISUAL_PROMPT_MAX_WORDS
    if count < minimum:
        assessment = "curto"
    elif count > maximum:
        assessment = "longo"
    else:
        assessment = "equilibrado"
    return f"{count} palavras \u00b7 {assessment} \u00b7 recomendado: {minimum}\u2013{maximum}"


def _final_reference_prompt(target_kind: str, target_id: UUID, canonical_prompt: str) -> str:
    canonical_prompt = repair_portuguese_mojibake(canonical_prompt)
    if not canonical_prompt.strip():
        return "Informe o prompt can\u00f4nico base para visualizar o prompt final."
    plan = plan_visual_references(
        cast(TargetKind, target_kind),
        target_id,
        {"canonical_prompt": canonical_prompt.strip()},
    )
    return plan.items[0].prompt if plan.items else canonical_prompt.strip()


def _open_image_dialog(url: str) -> None:
    with ui.dialog().props("transition-show=scale transition-hide=scale") as dialog:
        with ui.card().classes(
            "relative max-w-[92vw] max-h-[92vh] bg-slate-950 p-3 rounded-2xl overflow-hidden"
        ):
            with ui.row().classes("absolute top-3 right-3 z-10"):
                ui.button(icon="close", on_click=dialog.close).props(
                    "round unelevated color=grey-9 text-color=white"
                ).tooltip("Fechar visualização")
            with ui.element("div").classes(
                "flex items-center justify-center w-[88vw] h-[84vh] overflow-hidden"
            ):
                ui.image(url).props("fit=contain").classes("block w-full h-full")
    dialog.open()


def _open_image_from_event(_event: Any, *, url: str) -> None:
    """Open the image URL while deliberately discarding NiceGUI's click event."""

    _open_image_dialog(url)
