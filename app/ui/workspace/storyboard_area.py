# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, Any], Any]


def render_storyboard_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:

    from app.ui.workspace import storyboard_actions_area as deps
    from app.video_generation.storyboard_export import slugify_file_part as _slugify_file_part

    ui = deps.ui
    BLOCKING_DIALOG_PROPS = deps.BLOCKING_DIALOG_PROPS
    build_continuous_video_view_model = deps.build_continuous_video_view_model
    continuous_video_segment_validation_errors = deps.continuous_video_segment_validation_errors
    continuous_video_status_label = deps.continuous_video_status_label
    generation_progress_dialog = deps.generation_progress_dialog
    safe_close_ui_element = deps.safe_close_ui_element
    _asset_content_url = deps._asset_content_url
    _cancel_continuous_video_segment_from_ui = deps._cancel_continuous_video_segment_from_ui
    _plan_continuous_video_segments_from_ui = deps._plan_continuous_video_segments_from_ui
    _delete_all_continuous_video_segments_from_ui = (
        deps._delete_all_continuous_video_segments_from_ui
    )
    _delete_continuous_video_segment_from_ui = deps._delete_continuous_video_segment_from_ui
    _remove_continuous_video_segment_frame_from_ui = (
        deps._remove_continuous_video_segment_frame_from_ui
    )
    _regenerate_continuous_video_segment_frame_from_ui = (
        deps._regenerate_continuous_video_segment_frame_from_ui
    )
    _render_continuous_media_preview = deps._render_continuous_media_preview
    _save_continuous_video_segment_prompts_from_ui = (
        deps._save_continuous_video_segment_prompts_from_ui
    )

    continuous_view_model = build_continuous_video_view_model(summary)
    continuous_segments = list(summary.get("continuous_video_segments", []))
    segments_are_planned = bool(continuous_segments)
    project_title_slug = _slugify_file_part(
        getattr(summary.get("project"), "title", "") or ""
    )

    try:
        ui_client: Any = ui.context.client or None
    except (AssertionError, RuntimeError):
        ui_client = None

    segment_plan_dialog, _segment_plan_progress_callback = generation_progress_dialog(
        "Planejando segmentos",
        1,
        "etapa",
        "Agora: separando o roteiro em blocos de storyboard.",
    )
    initial_frame_dialog, _initial_frame_progress_callback = generation_progress_dialog(
        "Gerando frame",
        1,
        "frame",
        "Agora: criando o quadro visual para o storyboard.",
    )

    has_any_frame_generated = any(
        bool(
            getattr(segment, "source_frame_asset_id", None)
            or (
                isinstance(getattr(segment, "metadata_json", {}), dict)
                and segment.metadata_json.get("initial_frame_asset_id")
            )
        )
        for segment in continuous_segments
    )

    # Contagem de quantos frames já estão gerados para poder habilitar download
    total_frames_generated = sum(
        1
        for segment in continuous_segments
        if getattr(segment, "source_frame_asset_id", None)
        or (
            isinstance(getattr(segment, "metadata_json", {}), dict)
            and segment.metadata_json.get("initial_frame_asset_id")
        )
    )
    can_download_selected = total_frames_generated >= 1

    with ui.row().classes("w-full items-start justify-between gap-4 mb-2 flex-wrap lg:flex-nowrap"):
        with ui.column().classes("gap-1 min-w-0 flex-1"):
            ui.label("Storyboards").classes("brand-type text-3xl font-bold")
            ui.label(
                "Planeje os blocos de cenas a partir do roteiro e gere os frames visuais correspondentes "
                "para construir a narrativa visual da história."
            ).classes("text-sm text-[#8e948f]")
        with ui.column().classes("items-end gap-2 ml-auto shrink-0"):
            with ui.row().classes("items-center justify-end gap-2 flex-wrap"):
                if not segments_are_planned:
                    ui.button(
                        "Planejar segmentos",
                        icon="view_timeline",
                        on_click=lambda: _plan_continuous_video_segments_from_ui(
                            project_id,
                            loading_dialog=segment_plan_dialog,
                        ),
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                elif not has_any_frame_generated:
                    ui.button(
                        "Replanejar",
                        icon="refresh",
                        on_click=lambda: _plan_continuous_video_segments_from_ui(
                            project_id,
                            loading_dialog=segment_plan_dialog,
                        ),
                    ).props("flat dense no-caps").classes("text-[#d8dbd8] rounded-xl")
                else:
                    ui.button(
                        "Replanejar",
                        icon="lock",
                    ).props("flat dense no-caps disable").classes(
                        "text-[#555a56] cursor-not-allowed rounded-xl"
                    ).tooltip(
                        "Replanejamento bloqueado: frames já foram gerados nos segmentos."
                    )
                if segments_are_planned:
                    def _confirm_delete_all() -> None:
                        with ui.dialog().classes("rounded-2xl") as confirm_dialog:
                            with ui.card().classes("rounded-2xl p-6 gap-4"):
                                ui.label("Apagar todos os segmentos?").classes(
                                    "brand-type text-xl font-bold"
                                )
                                ui.label(
                                    "Esta ação remove todos os segmentos e seus frames. "
                                    "Esta ação não pode ser desfeita."
                                ).classes("text-sm text-[#8d938e]")
                                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                                    ui.button(
                                        "Cancelar",
                                        on_click=confirm_dialog.close,
                                    ).props("flat no-caps")

                                    async def _confirm_delete_action() -> None:
                                        confirm_dialog.close()
                                        await _delete_all_continuous_video_segments_from_ui(
                                            project_id,
                                        )

                                    ui.button(
                                        "Apagar tudo",
                                        icon="delete_forever",
                                        on_click=_confirm_delete_action,
                                    ).props("unelevated no-caps").classes(
                                        "bg-[#6b2a2a] text-white rounded-xl"
                                    )
                        confirm_dialog.open()

                    ui.button(
                        "Apagar segmentos",
                        icon="delete_forever",
                        on_click=_confirm_delete_all,
                    ).props("flat dense no-caps").classes("text-[#d87a7a] rounded-xl")
                if can_download_selected:
                    ui.button(
                        "Baixar storyboards",
                        icon="download",
                        on_click=lambda: ui.download(
                            f"/api/v1/video/projects/{project_id}/continuous/segments/download",
                            f"{(project_title_slug or 'storyboard')}-storyboards.zip",
                        ),
                    ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
            if continuous_segments:
                ui.label(
                    f"{len(continuous_segments)} segmento(s) de storyboard planejado(s)"
                ).classes("text-xs text-[#8d938e]")

    with ui.element("div").classes(
        "w-full mt-2" if continuous_view_model.is_continuous_mode else "hidden"
    ):
        if continuous_segments:
            with ui.row().classes("w-full items-center justify-between flex-wrap gap-3 mt-3"):
                with ui.row().classes("flex-wrap gap-2"):
                    ui.badge(f"{len(continuous_segments)} segmento(s)").classes(
                        "blue-status-badge bg-[#243342]"
                    )
                    if continuous_view_model.pending_frame_count:
                        ui.badge(
                            f"{continuous_view_model.pending_frame_count} frame(s) pendente(s)"
                        ).classes("blue-status-badge bg-[#243342]")
                        ui.badge(
                            f"Frames: US$ {continuous_view_model.total_frame_cost_estimate}"
                        ).classes("blue-status-badge bg-[#26301f]")

            with ui.grid().classes("w-full grid-cols-1 xl:grid-cols-2 gap-4 mt-4"):
                for segment in continuous_segments:
                    metadata = (
                        getattr(segment, "metadata_json", {})
                        if isinstance(getattr(segment, "metadata_json", {}), dict)
                        else {}
                    )
                    names = [
                        *list(metadata.get("characters") or []),
                        *list(metadata.get("locations") or []),
                        *list(metadata.get("props") or []),
                    ]
                    visual_summary = ", ".join(str(name) for name in names if str(name).strip())
                    validation_errors = continuous_video_segment_validation_errors(segment)
                    status_value = str(
                        getattr(segment, "review_status", None)
                        or getattr(getattr(segment, "status", ""), "value", segment.status)
                    ).lower()
                    is_preparing_segment = status_value in {
                        "preparing",
                        "generating",
                        "running",
                        "sending",
                        "processing",
                    }
                    initial_asset_id = (
                        metadata.get("initial_frame_asset_id")
                        or getattr(segment, "source_frame_asset_id", None)
                    )
                    initial_frame_url = _asset_content_url(initial_asset_id)

                    dialog_card_classes = (
                        "segment-prompt-dialog-card entity-card rounded-2xl p-6 "
                        "h-[min(500px,80vh)] w-[min(640px,92vw)] flex flex-col overflow-hidden"
                    )
                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as segment_prompt_dialog,
                        ui.card().classes(dialog_card_classes),
                    ):
                        with ui.column().classes("w-full gap-1 shrink-0"):
                            ui.label(getattr(segment, "title", "") or "Segmento").classes(
                                "brand-type text-2xl font-bold"
                            )
                            ui.label("Prompt visual para o frame").classes(
                                "text-sm text-[#8d938e]"
                            )
                        with ui.column().classes(
                            "w-full gap-4 flex-1 min-h-0 mt-4 overflow-y-auto"
                        ):
                            initial_prompt_input = ui.textarea(
                                "Prompt do frame",
                                value=deps.segment_frame_prompts(segment)["initial"],
                            ).props("outlined autogrow").classes(
                                "storyboard-prompt-textarea w-full min-h-[190px]"
                            )

                        async def save_segment_prompt(
                            segment_id: UUID = segment.id,
                            frame_input: Any = initial_prompt_input,
                            dialog: Any = segment_prompt_dialog,
                        ) -> None:
                            new_prompt = str(frame_input.value or "").strip()
                            if not new_prompt:
                                ui.notify(
                                    "Informe o prompt do frame antes de salvar.", color="warning"
                                )
                                return
                            safe_close_ui_element(dialog)
                            await _save_continuous_video_segment_prompts_from_ui(
                                project_id,
                                segment_id,
                                new_prompt,
                                initial_frame_prompt=new_prompt,
                            )

                        with ui.row().classes(
                            "w-full justify-end gap-2 mt-4 pt-3 border-t border-[#343934] shrink-0"
                        ):
                            ui.button(
                                "Cancelar",
                                on_click=segment_prompt_dialog.close,
                            ).props("flat no-caps")
                            ui.button(
                                "Salvar",
                                icon="save",
                                on_click=save_segment_prompt,
                            ).props("unelevated no-caps").classes("acid-bg rounded-xl")

                    with (
                        ui.dialog().props(BLOCKING_DIALOG_PROPS) as segment_media_dialog,
                        ui.card().classes(
                            "entity-card rounded-2xl p-5 w-[min(1180px,96vw)] "
                            "h-[min(880px,92vh)] flex flex-col overflow-hidden"
                        ),
                    ):
                        with ui.row().classes("w-full items-center justify-between gap-3 shrink-0"):
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(
                                    getattr(segment, "title", "")
                                    or f"Segmento {segment.segment_number:02d}"
                                ).classes("brand-type text-2xl font-bold")
                                ui.label("Visualização expandida do storyboard").classes(
                                    "text-xs text-[#8d938e]"
                                )
                            ui.button(
                                icon="close",
                                on_click=segment_media_dialog.close,
                            ).props("flat round dense")
                        seg_id = segment.id
                        remove_initial_cb: Any = (
                            None
                            if is_preparing_segment
                            else (
                                lambda s_id=seg_id: _remove_continuous_video_segment_frame_from_ui(
                                    project_id,
                                    s_id,
                                    "initial",
                                )
                            )
                        )
                        with ui.grid().classes(
                            "w-full grid-cols-1 gap-4 mt-4 flex-1 min-h-0 overflow-y-auto"
                        ):
                            with ui.column().classes("w-full min-h-0 gap-2"):
                                if initial_frame_url:
                                    _render_continuous_media_preview(
                                        "Storyboard Frame",
                                        initial_frame_url,
                                        media_kind="image",
                                        large=True,
                                        remove_on_click=remove_initial_cb,
                                    )

                    with ui.element("div").classes("entity-card rounded-2xl p-4"):
                        with ui.row().classes("w-full items-start justify-between gap-3"):
                            with ui.column().classes("gap-1 min-w-0"):
                                ui.label(
                                    getattr(segment, "title", "")
                                    or f"Segmento {segment.segment_number:02d}"
                                ).classes("font-semibold")
                            
                            if initial_frame_url:
                                status_badge_classes = "bg-[#26301f] text-white"
                                status_label = "Concluído"
                            elif is_preparing_segment:
                                status_badge_classes = "blue-status-badge bg-[#243342]"
                                status_label = "Gerando..."
                            else:
                                status_badge_classes = "blue-status-badge bg-[#5aa3f0] text-white"
                                status_label = "Pendente"
                            ui.badge(status_label).classes(status_badge_classes)

                        with ui.grid().classes("w-full grid-cols-1 gap-3 mt-3"):
                            if initial_frame_url:
                                _render_continuous_media_preview(
                                    "Storyboard Frame",
                                    initial_frame_url,
                                    media_kind="image",
                                    remove_on_click=remove_initial_cb,
                                )
                            else:
                                _render_continuous_media_preview(
                                    "Storyboard Frame",
                                    "",
                                    media_kind="image",
                                )

                        if metadata.get("error"):
                            ui.label(str(metadata.get("error"))[:240]).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if validation_errors:
                            ui.label("; ".join(validation_errors)).classes(
                                "text-xs text-[#ffb4b4] mt-2"
                            )
                        if is_preparing_segment:
                            with ui.row().classes("items-center gap-2 mt-3 text-sm text-[#d1d4d1]"):
                                ui.spinner(size="sm").classes("acid")
                                ui.label("Gerando frame no Meta AI...")

                        if visual_summary:
                            ui.label(visual_summary).classes("text-xs text-[#8d938e] mt-2")

                        ui.label(str(getattr(segment, "prompt", "") or "")).classes(
                            "text-sm text-[#d1d4d1] whitespace-pre-wrap mt-3"
                        )

                        with ui.row().classes("w-full flex-wrap justify-end gap-2 mt-2"):
                            if is_preparing_segment and getattr(segment, "generation_job_id", None):
                                ui.button(
                                    "Cancelar",
                                    icon="stop",
                                    on_click=lambda segment_id=segment.id: (
                                        _cancel_continuous_video_segment_from_ui(
                                            project_id, segment_id
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("text-[#ffb4b4] rounded-xl")

                            if initial_frame_url:
                                ui.button(
                                    "Visualizar",
                                    icon="open_in_full",
                                    on_click=segment_media_dialog.open,
                                ).props("flat dense no-caps").classes("rounded-xl")

                            has_initial_frame = bool(initial_frame_url)
                            can_generate = not is_preparing_segment

                            if can_generate:
                                button_label = "Regerar frame" if has_initial_frame else "Gerar frame"
                                button_icon = "refresh" if has_initial_frame else "image"
                                ui.button(
                                    button_label,
                                    icon=button_icon,
                                    on_click=lambda segment_id=segment.id: (
                                        _regenerate_continuous_video_segment_frame_from_ui(
                                            project_id,
                                            segment_id,
                                            "initial",
                                            loading_dialog=initial_frame_dialog,
                                            client=ui_client,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes(
                                    "acid-bg rounded-xl min-w-[104px]"
                                )

                            ui.button(
                                "Editar prompt",
                                icon="edit",
                                on_click=segment_prompt_dialog.open,
                            ).props(
                                "flat dense no-caps" + (" disable" if is_preparing_segment else "")
                            ).classes("text-[#d8dbd8] rounded-xl")

                            def _confirm_delete_segment(segment_id: UUID = segment.id) -> None:
                                with ui.dialog().classes("rounded-2xl") as delete_dialog:
                                    with ui.card().classes("rounded-2xl p-6 gap-4"):
                                        ui.label("Excluir este segmento?").classes(
                                            "brand-type text-xl font-bold"
                                        )
                                        ui.label(
                                            "O segmento e seus quadros serão removidos. "
                                            "Os demais segmentos são renumerados para preencher o gap."
                                        ).classes("text-sm text-[#8d938e]")
                                        with ui.row().classes("w-full justify-end gap-2 mt-2"):
                                            ui.button(
                                                "Cancelar",
                                                on_click=delete_dialog.close,
                                            ).props("flat no-caps")

                                            async def _do_delete() -> None:
                                                delete_dialog.close()
                                                await _delete_continuous_video_segment_from_ui(
                                                    project_id, segment_id
                                                )

                                            ui.button(
                                                "Excluir",
                                                icon="delete",
                                                on_click=_do_delete,
                                            ).props("unelevated no-caps").classes(
                                                "bg-[#6b2a2a] text-white rounded-xl"
                                            )
                                delete_dialog.open()

                            ui.button(
                                "Excluir",
                                icon="delete",
                                on_click=_confirm_delete_segment,
                            ).props(
                                "flat dense no-caps" + (" disable" if is_preparing_segment else "")
                            ).classes("text-[#d87a7a] rounded-xl")
        else:
            with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
                ui.label("Nenhum segmento planejado").classes("brand-type text-xl font-bold")
                ui.label("Planeje os segmentos diretamente a partir do roteiro.").classes(
                    "text-sm text-[#8d938e] leading-6"
                )
