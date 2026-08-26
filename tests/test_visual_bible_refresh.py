import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.ui.workspace.visual_bible_area as visual_bible_area
from app.core.enums import GenerationJobStatus
from app.ui.workspace.visual_bible_area import (
    VisualReferencePollStatus,
    _all_visual_references_generated,
    _cancel_bare_watch_on_completion,
    _final_reference_prompt,
    _open_image_from_event,
    _prompt_word_counter,
    _start_visual_reference_generation_watch,
    _visual_reference_batch_error,
    _visual_reference_poll_decision,
    _visual_reference_resume_keys,
    _visual_reference_user_error,
    _watch_visual_reference_generation,
)


def test_visual_reference_click_opens_the_asset_url_instead_of_the_event(monkeypatch: Any) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr(visual_bible_area, "_open_image_dialog", opened_urls.append)

    _open_image_from_event(object(), url="/api/v1/assets/reference-id/content")

    assert opened_urls == ["/api/v1/assets/reference-id/content"]


@pytest.mark.asyncio
async def test_cancel_bare_watch_cancels_running_task_on_completion_watch() -> None:
    # O watcher "nu" (render da página) e o de acompanhamento (botão) ambos
    # fazem navigate() ao concluir. Disparar a geração pelo botão deve cancelar
    # o nu para não haver reload duplo que derruba o pop-up de progresso.
    async def _noop() -> None:
        return None

    bare_task = asyncio.create_task(_noop())
    slot: list[asyncio.Task[Any] | None] = [bare_task]

    _cancel_bare_watch_on_completion(slot, show_completion=True)
    await asyncio.sleep(0)

    assert slot[0] is None
    assert bare_task.cancelled()


@pytest.mark.asyncio
async def test_cancel_bare_watch_keeps_task_when_not_completion_watch() -> None:
    async def _noop() -> None:
        return None

    bare_task = asyncio.create_task(_noop())
    slot: list[asyncio.Task[Any] | None] = [bare_task]

    _cancel_bare_watch_on_completion(slot, show_completion=False)

    assert slot[0] is bare_task
    assert not bare_task.cancelled()


@pytest.mark.asyncio
async def test_cancel_bare_watch_ignores_already_done_task() -> None:
    async def _noop() -> None:
        return None

    bare_task = asyncio.create_task(_noop())
    await bare_task
    slot: list[asyncio.Task[Any] | None] = [bare_task]

    _cancel_bare_watch_on_completion(slot, show_completion=True)

    assert slot[0] is None
    assert not bare_task.cancelled()


@pytest.mark.asyncio
async def test_queued_generation_starts_a_fresh_client_watcher(monkeypatch: Any) -> None:
    project_id = uuid4()
    known_ids = frozenset({uuid4()})
    watched: list[tuple[object, object, object]] = []
    delete_callbacks: list[object] = []
    client = SimpleNamespace(
        id="client-id",
        on_delete=delete_callbacks.append,
    )

    async def watch(
        current_project_id: object,
        current_ids: object,
        current_client: object,
    ) -> None:
        watched.append((current_project_id, current_ids, current_client))

    monkeypatch.setattr(visual_bible_area, "_watch_visual_reference_generation", watch)
    monkeypatch.setattr(
        visual_bible_area.background_tasks,
        "create",
        lambda awaitable, **_kwargs: asyncio.create_task(awaitable),
    )

    task = _start_visual_reference_generation_watch(project_id, known_ids, client)
    await task

    assert watched == [(project_id, known_ids, client)]
    assert len(delete_callbacks) == 1
    assert not inspect.signature(delete_callbacks[0]).parameters  # type: ignore[arg-type]


def test_visual_reference_poll_keeps_watching_active_generation() -> None:
    reference_id = uuid4()
    has_new_reference, has_active_generation = _visual_reference_poll_decision(
        frozenset({reference_id}),
        [SimpleNamespace(id=reference_id)],
        [
            SimpleNamespace(
                status=GenerationJobStatus.RUNNING,
                request_payload={"operation": "generate_visual_reference"},
            )
        ],
    )

    assert has_new_reference is False
    assert has_active_generation is True


def test_visual_reference_poll_reloads_when_worker_persists_new_reference() -> None:
    has_new_reference, has_active_generation = _visual_reference_poll_decision(
        frozenset({uuid4()}),
        [SimpleNamespace(id=uuid4())],
        [],
    )

    assert has_new_reference is True
    assert has_active_generation is False


def test_visual_reference_poll_ignores_unrelated_image_jobs() -> None:
    reference_id = uuid4()
    has_new_reference, has_active_generation = _visual_reference_poll_decision(
        frozenset({reference_id}),
        [SimpleNamespace(id=reference_id)],
        [
            SimpleNamespace(
                status=GenerationJobStatus.PENDING,
                request_payload={"operation": "generate_storyboard_frame"},
            )
        ],
    )

    assert has_new_reference is False
    assert has_active_generation is False


def test_visual_reference_resume_preserves_completed_and_active_items() -> None:
    completed_target_id = uuid4()
    active_target_id = uuid4()
    completed, active = _visual_reference_resume_keys(
        [
            SimpleNamespace(
                target_kind="character",
                target_id=completed_target_id,
                view_type="full_body",
                status="approved",
                asset_id=uuid4(),
            )
        ],
        [
            SimpleNamespace(
                status=GenerationJobStatus.RUNNING,
                request_payload={
                    "operation": "generate_visual_reference",
                    "target_kind": "location",
                    "target_id": str(active_target_id),
                    "view_type": "establishing",
                },
            )
        ],
    )

    assert ("character", str(completed_target_id), "full_body") in completed
    assert ("location", str(active_target_id), "establishing") in active


def test_visual_reference_resume_requeues_failed_or_rejected_items() -> None:
    target_id = uuid4()
    completed, active = _visual_reference_resume_keys(
        [
            SimpleNamespace(
                target_kind="character",
                target_id=target_id,
                view_type="full_body",
                status="rejected",
                asset_id=uuid4(),
            )
        ],
        [
            SimpleNamespace(
                status=GenerationJobStatus.FAILED,
                request_payload={
                    "operation": "generate_visual_reference",
                    "target_kind": "character",
                    "target_id": str(target_id),
                    "view_type": "full_body",
                },
            )
        ],
    )

    assert completed == set()
    assert active == set()


def test_generate_all_button_can_hide_only_when_every_target_has_a_reference() -> None:
    character_id = uuid4()
    location_id = uuid4()
    characters = [SimpleNamespace(id=character_id)]
    locations = [SimpleNamespace(id=location_id)]
    complete_references = [
        SimpleNamespace(
            target_kind="character",
            target_id=character_id,
            view_type="full_body",
            status="approved",
            asset_id=uuid4(),
        ),
        SimpleNamespace(
            target_kind="location",
            target_id=location_id,
            view_type="establishing",
            status="generated",
            asset_id=uuid4(),
        ),
    ]

    assert _all_visual_references_generated(characters, locations, complete_references) is True
    assert _all_visual_references_generated(characters, locations, complete_references[:1]) is False


@pytest.mark.asyncio
async def test_visual_reference_watcher_reloads_captured_client_without_ui_timer() -> None:
    project_id = uuid4()
    client = SimpleNamespace(is_deleted=False)
    states = iter(
        [
            VisualReferencePollStatus(False, True),
            VisualReferencePollStatus(True, False),
        ]
    )
    polled: list[tuple[object, object]] = []
    navigations: list[tuple[object, str | None]] = []

    async def poll_state(
        current_project_id: object, known_ids: object
    ) -> VisualReferencePollStatus:
        polled.append((current_project_id, known_ids))
        return next(states)

    async def no_wait(_: float) -> None:
        return None

    await _watch_visual_reference_generation(
        project_id,
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda current_client, target: navigations.append((current_client, target)),
    )

    assert len(polled) == 2
    assert navigations == [(client, None)]


@pytest.mark.asyncio
async def test_visual_reference_watcher_stops_after_client_is_deleted() -> None:
    client = SimpleNamespace(is_deleted=False)
    poll_calls = 0

    async def delete_during_wait(_: float) -> None:
        client.is_deleted = True

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        nonlocal poll_calls
        poll_calls += 1
        return VisualReferencePollStatus(False, True)

    await _watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=delete_during_wait,
    )

    assert poll_calls == 0


@pytest.mark.asyncio
async def test_visual_reference_watcher_shows_worker_error_popup() -> None:
    client = SimpleNamespace(is_deleted=False)
    popups: list[tuple[object, str]] = []
    navigations: list[tuple[object, str | None]] = []

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        return VisualReferencePollStatus(False, False, "Perfil Meta não autorizado")

    async def no_wait(_: float) -> None:
        return None

    await _watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda current_client, target: navigations.append((current_client, target)),
        show_error=lambda current_client, error: popups.append((current_client, error)),
    )

    assert popups == [(client, "Perfil Meta não autorizado")]
    # Lote encerrado COM erro: a página recarrega para mostrar o que succeeded.
    assert navigations == [(client, None)]


@pytest.mark.asyncio
async def test_visual_reference_bare_watcher_does_not_popup_on_terminal_error() -> None:
    """O watcher "nu" (sem show_error) NÃO exibe popup nem recarrega em erro.

    Bug real: a recusa da Meta reaparecia como popup a cada load da página
    porque o watcher nu (iniciado em todo render) elevava o erro terminal a
    popup e recarregava — recarregar re-disparava o watcher nu, num loop
    infinito. O job FAILED já está refletido no card; só o watcher de
    acompanhamento (show_completion) deve elevar o erro a popup.
    """
    client = SimpleNamespace(is_deleted=False)
    popups: list[tuple[object, str]] = []
    navigations: list[tuple[object, str | None]] = []

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        return VisualReferencePollStatus(False, False, "A Meta AI recusou o prompt")

    async def no_wait(_: float) -> None:
        return None

    await _watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda current_client, target: navigations.append((current_client, target)),
    )

    assert popups == []
    assert navigations == []


@pytest.mark.asyncio
async def test_visual_reference_watcher_keeps_watching_after_partial_batch_error() -> None:
    """Falha parcial com o lote em andamento NÃO encerra o acompanhamento.

    Bug real (2026-09-06): 2 falhas rápidas no lote fechavam o pop-up com 9+
    referências ainda na fila — o usuário perdia o acompanhamento e as
    referências só apareciam "do nada" nos cards depois.
    """
    client = SimpleNamespace(is_deleted=False)
    popups: list[tuple[object, str]] = []
    polls: list[VisualReferencePollStatus] = []
    navigations: list[object] = []

    # Poll 1: erro parcial com lote ativo; Poll 2: idem (mesma mensagem,
    # aviso único); Poll 3: lote acabou com erro -> popup final; fim.
    states = iter(
        [
            VisualReferencePollStatus(False, True, "page.goto: Timeout 15000ms exceeded."),
            VisualReferencePollStatus(False, True, "page.goto: Timeout 15000ms exceeded."),
            VisualReferencePollStatus(True, False, "page.goto: Timeout 15000ms exceeded."),
        ]
    )

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        status = next(states)
        polls.append(status)
        return status

    async def no_wait(_: float) -> None:
        return None

    await _watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda current_client, _target: navigations.append(current_client),
        show_error=lambda current_client, error: popups.append((current_client, error)),
        show_success=lambda current_client: None,
    )

    assert len(polls) == 3
    assert len(popups) == 1  # apenas o erro FINAL (lote encerrado)
    assert navigations == [client]


@pytest.mark.asyncio
async def test_visual_reference_watcher_partial_error_notifies_once_per_message() -> None:
    client = SimpleNamespace(is_deleted=False)
    popups: list[tuple[object, str]] = []
    notifications: list[str] = []

    # Mesma mensagem de erro repetida em 4 polls com lote ativo: o aviso
    # parcial deve disparar UMA vez; o popup só no fim do lote.
    states = iter(
        [
            VisualReferencePollStatus(False, True, "timeout na geração"),
            VisualReferencePollStatus(False, True, "timeout na geração"),
            VisualReferencePollStatus(False, True, "timeout na geração"),
            VisualReferencePollStatus(False, True, "timeout na geração"),
            VisualReferencePollStatus(True, False, "timeout na geração"),
        ]
    )

    async def poll_state(*_: object) -> VisualReferencePollStatus:
        return next(states)

    async def no_wait(_: float) -> None:
        return None

    await _watch_visual_reference_generation(
        uuid4(),
        frozenset(),
        client,
        poll_state=poll_state,
        sleep=no_wait,
        navigate=lambda current_client, _target: None,
        show_error=lambda current_client, error: popups.append((current_client, error)),
        show_success=lambda current_client: None,
        on_partial_error=lambda current_client, error: notifications.append(error),
    )

    assert len(popups) == 1  # erro final
    assert len(notifications) == 1  # aviso parcial deduplicado


def test_visual_reference_authentication_error_has_actionable_message() -> None:
    message = _visual_reference_user_error(
        "Perfil Meta não autorizado. Use Autorizar Meta nos Ajustes."
    )

    assert "sessão da Meta ou do Vibes" in message
    assert "Ajustes" in message


def test_visual_reference_meta_refusal_error_has_actionable_message() -> None:
    raw = (
        "A Meta AI recusou o prompt de imagem (marcador: \\\"versão segura\\\"). "
        "Resposta: Não consegui gerar essa imagem exatamente como você descreveu. "
        "Diagnóstico: C:/tmp/meta-refusal-1.png"
    )
    message = _visual_reference_user_error(raw)

    assert message != raw
    assert "recusou gerar esta referência" in message
    assert "referência manual" in message


def test_visual_reference_navigation_timeout_has_actionable_message() -> None:
    raw = (
        'page.goto: Timeout 15000ms exceeded.\nCall log:\n  - navigating to '
        '"https://www.meta.ai/prompt/[REDACTED]", waiting until "domcontentloaded"'
    )
    message = _visual_reference_user_error(raw)

    assert message != raw
    assert "não respondeu a tempo" in message
    assert "reprocessado automaticamente" in message


def test_visual_reference_prep_budget_timeout_maps_to_navigation_message() -> None:
    raw = "A navegação para a conversa do Meta AI demorou demais (orçamento de preparação)."
    message = _visual_reference_user_error(raw)

    assert message != raw
    assert "não respondeu a tempo" in message


def test_visual_reference_unrelated_error_passes_through_unchanged() -> None:
    raw = "Meta AI não apresentou uma nova imagem vertical em alta resolução."

    assert _visual_reference_user_error(raw) == raw


def test_visual_reference_pending_job_reports_stalled_worker_without_heartbeat() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        created_at=now - timedelta(seconds=30),
        error=None,
    )

    error = _visual_reference_batch_error([job], now=now, worker_alive=False)

    assert error is not None
    assert "fila de referências visuais não avançou" in error


def test_visual_reference_pending_job_keeps_waiting_while_worker_is_alive() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        status=GenerationJobStatus.PENDING,
        created_at=now - timedelta(seconds=30),
        error=None,
    )

    error = _visual_reference_batch_error([job], now=now, worker_alive=True)

    assert error is None


def test_visual_reference_batch_keeps_waiting_after_recent_completed_item() -> None:
    now = datetime.now(UTC)
    jobs = [
        SimpleNamespace(
            status=GenerationJobStatus.PENDING,
            created_at=now - timedelta(minutes=7),
            updated_at=now - timedelta(minutes=7),
            started_at=None,
            completed_at=None,
            error=None,
        ),
        SimpleNamespace(
            status=GenerationJobStatus.SUCCEEDED,
            created_at=now - timedelta(minutes=7),
            updated_at=now - timedelta(seconds=20),
            started_at=now - timedelta(minutes=2),
            completed_at=now - timedelta(seconds=20),
            error=None,
        ),
    ]

    error = _visual_reference_batch_error(jobs, now=now, worker_alive=True)

    assert error is None


def test_visual_reference_batch_error_suppressed_when_target_was_recovered() -> None:
    """FAILED antigo cujo alvo já tem referência com asset não é erro real.

    Bug real (O Último Sorveteiro da Rua): o lote inteiro nos cards, mas o
    popup de falha reaparecia em cada poll porque o job FAILED ficava no lote
    para sempre — o retry do worker recuperou o mesmo alvo depois.
    """
    target_id = uuid4()
    jobs = [
        SimpleNamespace(
            status=GenerationJobStatus.FAILED,
            request_payload={
                "operation": "generate_visual_reference",
                "target_kind": "character",
                "target_id": str(target_id),
                "view_type": "full_body",
            },
            error="page.goto: Timeout 15000ms exceeded.",
        ),
    ]
    references = [
        SimpleNamespace(
            target_kind="character",
            target_id=target_id,
            view_type="full_body",
            status="approved",
            asset_id=uuid4(),
        ),
    ]

    error = _visual_reference_batch_error(jobs, references=references)

    assert error is None


def test_visual_reference_batch_error_kept_when_target_has_no_reference() -> None:
    """FAILED cujo alvo NÃO tem referência com asset continua sendo erro."""
    failed_target = uuid4()
    other_target = uuid4()
    jobs = [
        SimpleNamespace(
            status=GenerationJobStatus.FAILED,
            request_payload={
                "operation": "generate_visual_reference",
                "target_kind": "character",
                "target_id": str(failed_target),
                "view_type": "full_body",
            },
            error="A Meta AI recusou o prompt de imagem.",
        ),
    ]
    references = [
        SimpleNamespace(
            target_kind="character",
            target_id=other_target,
            view_type="full_body",
            status="approved",
            asset_id=uuid4(),
        ),
    ]

    error = _visual_reference_batch_error(jobs, references=references)

    assert error == "A Meta AI recusou o prompt de imagem."


def test_visual_prompt_counter_and_final_meta_preview_are_explicit() -> None:
    counter = _prompt_word_counter("personagem com casaco azul")
    final_prompt = _final_reference_prompt(
        "character",
        uuid4(),
        "Clara, personagem com casaco azul.",
    )

    assert "curto" in counter
    assert "20" in counter and "65" in counter
    assert "corpo inteiro" in final_prompt
    assert "fundo da imagem seja um cinza claro" in final_prompt
    assert "seu enquadramento deve ser vertical 9:16" in final_prompt
    assert "Não inclua textos, letras, legendas, logotipos" in final_prompt


def test_visual_prompt_counter_uses_correct_portuguese_punctuation() -> None:
    counter = _prompt_word_counter("quatro palavras sem erro")

    assert counter == "4 palavras \u00b7 curto \u00b7 recomendado: 20\u201365"
