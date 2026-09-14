"""Regressões do processamento de falhas no MediaWorker.

Bugs observados em produção (2026-09):
1. UserClosedBrowserError (usuário fechou o navegador) era tratado como
   exceção genérica e reenfileirado pelo loop de recuperação — queimando as
   3 tentativas do job com o usuário sem saber o motivo.
2. O caminho de gravação da falha podia crashar (MissingGreenlet ao acessar
   atributo ORM expirado após rollback), mascarando o erro original e
   deixando o job órfão em RUNNING.
"""

from __future__ import annotations

import inspect

from app.core.enums import GenerationJobStatus
from app.jobs import service as jobs_service
from app.providers.browser_bridge import UserClosedBrowserError
from app.workers.worker import MediaWorker


def test_user_closed_browser_is_terminal_before_generic_failure_path() -> None:
    """O handler de UserClosedBrowserError deve vir ANTES do except genérico.

    Regressão: a exceção cairia no except Exception, marcava FAILED e o loop
    de recuperação reenfileirava o job (recover_stale_database_jobs reenvia
    PENDING), queimando as tentativas com erro genérico "Limite de
    tentativas atingido".
    """
    source = inspect.getsource(MediaWorker._process_claimed_message)

    terminal_pos = source.find("except UserClosedBrowserError")
    generic_pos = source.find("except Exception as exc:")
    handler_pos = source.find("response = await handler(job)")

    assert terminal_pos > 0, (
        "Handler de UserClosedBrowserError não encontrado em "
        "_process_claimed_message."
    )
    assert generic_pos > terminal_pos, (
        "UserClosedBrowserError deve ser capturado ANTES do except genérico."
    )
    assert handler_pos > 0 and handler_pos < terminal_pos


def test_user_closed_browser_failure_marks_job_failed_without_requeue() -> None:
    """O caminho terminal grava FAILED com a mensagem de retomada ao usuário."""
    source = inspect.getsource(MediaWorker._process_claimed_message)

    terminal_block = source.split("except UserClosedBrowserError", 1)[1]
    terminal_block = terminal_block.split("except Exception as exc:", 1)[0]

    assert "mark_job_failed" in terminal_block
    assert "navegador fechado manualmente" in terminal_block
    # Sem reenfileiramento automático no caminho terminal.
    assert "self.queue.enqueue" not in terminal_block
    assert "requeue_after_release = True" not in terminal_block


def test_set_project_job_action_captures_project_id_before_session_io() -> None:
    """Regressão MissingGreenlet: project_id é capturado antes de qualquer IO.

    Após um rollback, acessar job.project_id poderia disparar reload lazy do
    atributo ORM fora do greenlet (MissingGreenlet), crashando o
    mark_job_failed e deixando o job órfão em RUNNING.
    """
    source = inspect.getsource(jobs_service._set_project_job_action)

    capture_pos = source.find("project_id = job.project_id")
    io_pos = source.find("await get_or_create_production_settings(session, project_id)")

    assert capture_pos > 0, (
        "_set_project_job_action deve capturar project_id do ORM antes de IO."
    )
    assert io_pos > capture_pos, (
        "A captura de project_id deve vir ANTES da primeira IO da session."
    )
    # O corpo restante não deve mais acessar job.project_id após o capture.
    body = source[source.find("await get_or_create_production_settings"):]
    assert "job.project_id" not in body


def test_worker_failure_path_records_original_error_even_if_mark_fails() -> None:
    """O except genérico protege a gravação da falha contra crash secundário."""
    source = inspect.getsource(MediaWorker._process_claimed_message)

    generic_block = source.split("except Exception as exc:", 1)[1]

    assert "try:" in generic_block
    assert "mark_job_failed" in generic_block
    assert "media_worker_mark_failed_failed" in generic_block


def test_user_closed_browser_error_type_exists_for_ui_resume_flow() -> None:
    """A UI importa resume_after_user_browser_close para retomada explícita."""
    from app.ui.workspace import visual_bible_area

    assert hasattr(visual_bible_area, "resume_after_user_browser_close")
    # Status FAILED não conta como "ativo" no resume do lote da UI.
    from app.ui.workspace.visual_reference_state import (
        ACTIVE_VISUAL_REFERENCE_JOB_STATUSES,
    )

    assert GenerationJobStatus.FAILED not in ACTIVE_VISUAL_REFERENCE_JOB_STATUSES
