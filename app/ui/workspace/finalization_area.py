"""Área de UI para a etapa de Finalização: concatenação e download do vídeo final."""

import logging
from typing import Any, cast
from uuid import UUID

from nicegui import ui

from app.ui.shared.page_config import play_completion_sound

logger = logging.getLogger(__name__)


def _safe_notify(message: str, color: str = "info") -> None:
    try:
        ui.notify(message, color=color)
    except Exception:
        logger.debug("Could not show notification")


def render_finalization_area(project_id: UUID, summary: dict[str, Any]) -> None:
    """Renderiza a área de finalização do vídeo."""

    # Verificar status da finalização
    status = _get_finalization_status(project_id)

    with ui.column().classes("w-full gap-4"):
        # Título da seção
        ui.label("Finalização do Vídeo").classes("brand-type text-2xl font-bold leading-tight")

        # Status dos segmentos
        total = status.get("total_segments", 0)
        completed = status.get("completed_segments", 0)
        has_min = status.get("has_min_segments", completed >= 3)
        has_final = status.get("has_final_video", False)

        # Card de status
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-4"):
                ui.icon("info", color="blue").classes("text-2xl")
                with ui.column().classes("gap-1"):
                    ui.label("Status dos Vídeos").classes("font-bold")
                    ui.label(f"{completed}/{total} vídeo(s) de segmentos gerado(s) (Mínimo: 3)")

            # Barra de progresso
            progress = min(1.0, completed / max(total, 3)) if max(total, 3) > 0 else 0
            ui.linear_progress(value=progress, show_value=True).classes("w-full")

        # Ações
        if not has_min:
            # Menos de 3 vídeos gerados
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-4"):
                    ui.icon("hourglass_empty", color="orange").classes("text-2xl")
                    with ui.column().classes("gap-1"):
                        ui.label("Requisito Mínimo Não Atingido").classes("font-bold")
                        ui.label(
                            f"Gere pelo menos 3 vídeos de segmentos na aba Produção de Vídeo "
                            f"antes de finalizar. Atualmente: {completed}/3 vídeos gerados."
                        )
        else:
            # Pelo menos 3 vídeos gerados - pronto para finalizar
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-4"):
                    ui.icon("check_circle", color="green").classes("text-2xl")
                    with ui.column().classes("gap-1"):
                        ui.label("Pronto para Finalizar").classes("font-bold")
                        ui.label(f"{completed} vídeos de segmentos prontos para concatenação!")

            # Botões de ação
            with ui.row().classes("gap-4"):
                if has_final:
                    # Já existe vídeo final
                    ui.button(
                        "📥 Baixar Vídeo Final",
                        on_click=lambda: _download_final_video(project_id),
                        icon="download",
                    ).classes("acid-bg rounded-xl")

                    ui.button(
                        "🔄 Regenerar",
                        on_click=lambda: _regenerate_final_video(project_id),
                        icon="refresh",
                        color="orange",
                    ).classes("rounded-xl")
                else:
                    # Criar vídeo final
                    ui.button(
                        "🎬 Criar Vídeo Final",
                        on_click=lambda: _create_final_video(project_id),
                        icon="movie_creation",
                    ).classes("acid-bg rounded-xl")

            # Informações do vídeo final
            if has_final:
                _render_final_video_info(project_id, status)


def _render_final_video_info(project_id: UUID, status: dict[str, Any]) -> None:
    """Renderiza informações sobre o vídeo final existente."""
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("movie", color="purple").classes("text-2xl")
            with ui.column().classes("gap-1"):
                ui.label("Vídeo Final Disponível").classes("font-bold")
                ui.label("O vídeo final está pronto para download.")


def _get_finalization_status(project_id: UUID) -> dict[str, Any]:
    """Obtém o status da finalização via API."""
    import httpx

    try:
        response = httpx.get(
            f"http://127.0.0.1:8000/api/v1/video-finalization/{project_id}/status",
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
    except Exception as exc:
        logger.warning(f"Erro ao obter status de finalização: {exc}")

    return {
        "all_segments_completed": False,
        "total_segments": 0,
        "completed_segments": 0,
        "has_final_video": False,
    }


def _create_final_video(project_id: UUID) -> None:
    """Cria o vídeo final via API."""
    import httpx

    ui.notify("Criando vídeo final...", color="info")

    try:
        response = httpx.post(
            f"http://127.0.0.1:8000/api/v1/video-finalization/{project_id}/finalize",
            timeout=300,  # 5 minutos
        )

        if response.status_code == 200:
            ui.notify("Vídeo final criado com sucesso!", color="positive")
            play_completion_sound()
            ui.navigate.reload()
        else:
            error = response.json().get("detail", "Erro desconhecido")
            ui.notify(f"Erro ao criar vídeo final: {error}", color="negative")
    except Exception as exc:
        ui.notify(f"Erro ao criar vídeo final: {exc}", color="negative")


def _download_final_video(project_id: UUID) -> None:
    """Baixa o vídeo final."""
    ui.download(
        f"/api/v1/video-finalization/{project_id}/download",
        f"video_final_{project_id}.mp4",
    )


def _regenerate_final_video(project_id: UUID) -> None:
    """Regenera o vídeo final (deleta e cria novamente)."""
    import httpx

    ui.notify("Regenerando vídeo final...", color="info")

    try:
        # Deletar existente
        httpx.delete(
            f"http://127.0.0.1:8000/api/v1/video-finalization/{project_id}/finalize",
            timeout=30,
        )

        # Criar novo
        _create_final_video(project_id)
    except Exception as exc:
        ui.notify(f"Erro ao regenerar vídeo final: {exc}", color="negative")
