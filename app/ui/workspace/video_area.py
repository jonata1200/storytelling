# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

SectionTitle = Callable[[str, str, str | None, Any | None], None]
LoadingDialogFactory = Callable[[str, Any], Any]


def render_video_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: SectionTitle,
    loading_dialog_factory: LoadingDialogFactory | None = None,
) -> None:

    from app.ui.workspace import storyboard_video_area as deps

    ui = deps.ui
    BLOCKING_DIALOG_PROPS = deps.BLOCKING_DIALOG_PROPS
    build_continuous_video_view_model = deps.build_continuous_video_view_model
    continuous_video_segment_validation_errors = deps.continuous_video_segment_validation_errors
    continuous_video_status_label = deps.continuous_video_status_label
    generation_progress_dialog = deps.generation_progress_dialog
    safe_close_ui_element = deps.safe_close_ui_element
    _asset_content_url = deps._asset_content_url
    _generate_continuous_video_from_ui = deps._generate_continuous_video_from_ui
    _cancel_continuous_video_segment_from_ui = deps._cancel_continuous_video_segment_from_ui
    _approve_continuous_video_segment_from_ui = (
        deps._approve_continuous_video_segment_from_ui
    )
    _reject_continuous_video_segment_from_ui = deps._reject_continuous_video_segment_from_ui
    _plan_continuous_video_segments_from_ui = deps._plan_continuous_video_segments_from_ui
    _delete_all_continuous_video_segments_from_ui = (
        deps._delete_all_continuous_video_segments_from_ui
    )
    _remove_continuous_video_segment_frame_from_ui = (
        deps._remove_continuous_video_segment_frame_from_ui
    )
    _render_continuous_media_preview = deps._render_continuous_media_preview
    _save_continuous_video_segment_prompt_from_ui = (
        deps._save_continuous_video_segment_prompt_from_ui
    )
    _video_clip_asset_url = deps._video_clip_asset_url
    continuous_view_model = build_continuous_video_view_model(summary)
    continuous_segments = list(summary.get("continuous_video_segments", []))
    qa_results_by_segment = dict(summary.get("qa_results_by_segment", {}))
    segments_are_planned = bool(continuous_segments)
    segment_total_duration = sum(
        int(getattr(segment, "duration_seconds", 0) or 0) for segment in continuous_segments
    )
    segment_plan_dialog, _segment_plan_progress_callback = generation_progress_dialog(
        "Planejando segmentos",
        1,
        "etapa",
        "Agora: separando o roteiro em blocos de vídeo.",
    )
    video_generate_dialog, _video_generate_progress_callback = generation_progress_dialog(
        "Gerando vídeo",
        1,
        "vídeo",
        "Agora: enviando requisição para o provider de vídeo...",
    )

    has_any_frame_generated = any(
        bool(
            getattr(segment, "source_frame_asset_id", None)
            or getattr(segment, "final_frame_asset_id", None)
            or getattr(segment, "generated_video_asset_id", None)
            or getattr(segment, "asset_id", None)
            or (
                isinstance(getattr(segment, "metadata_json", {}), dict)
                and (
                    segment.metadata_json.get("initial_frame_asset_id")
                    or segment.metadata_json.get("final_frame_asset_id")
                    or segment.metadata_json.get("extracted_last_frame_asset_id")
                    or segment.metadata_json.get("video_asset_id")
                )
            )
        )
        for segment in continuous_segments
    )

    with ui.row().classes("w-full items-start justify-between gap-4 mb-2 flex-wrap lg:flex-nowrap"):
        with ui.column().classes("gap-1 min-w-0 flex-1"):
            ui.label("Produção de vídeo").classes("brand-type text-3xl font-bold")
            ui.label(
                "Gere o vídeo de cada segmento individualmente em cadeia com o provider configurado usando o "
                "prompts e os frames extraídos dos vídeos anteriores."
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
                        "Replanejamento bloqueado: frames ou vídeos já foram gerados nos segmentos."
                    )
                if segments_are_planned:

                    def _confirm_delete_all() -> None:
                        with ui.dialog().classes("rounded-2xl") as confirm_dialog:
                            with ui.card().classes("rounded-2xl p-6 gap-4"):
                                ui.label("Apagar todos os segmentos?").classes(
                                    "brand-type text-xl font-bold"
                                )
                                ui.label(
                                    "Esta ação remove todos os segmentos, prompts e conteúdos "
                                    "da etapa de produção de vídeo. Esta ação não pode ser desfeita."
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
            if continuous_segments:
                ui.label(
                    f"{len(continuous_segments)} segmento(s) · {segment_total_duration}s total"
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
                    ui.badge(f"{segment_total_duration}s").classes("blue-status-badge bg-[#26301f]")
                    if continuous_view_model.pending_frame_count:
                        ui.badge(
                            f"{continuous_view_model.pending_frame_count} frame(s) pendente(s)"
                        ).classes("blue-status-badge bg-[#243342]")
                        ui.badge(
                            f"Frames: US$ {continuous_view_model.total_frame_cost_estimate}"
                        ).classes("blue-status-badge bg-[#26301f]")
                    if continuous_view_model.can_conclude:
                        ui.badge("pacote pronto para concluir").classes(
                            "blue-status-badge bg-[#26301f]"
                        )

            with ui.grid().classes("w-full grid-cols-1 xl:grid-cols-2 gap-4 mt-4"):
                for idx, segment in enumerate(continuous_segments):
                    qa_result = qa_results_by_segment.get(segment.id)
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
                    prev_segment = continuous_segments[idx - 1] if idx > 0 else None
                    prev_metadata = (
                        getattr(prev_segment, "metadata_json", {})
                        if prev_segment
                        and isinstance(getattr(prev_segment, "metadata_json", {}), dict)
                        else {}
                    )
                    initial_asset_id = (
                        metadata.get("initial_frame_asset_id")
                        or getattr(segment, "source_frame_asset_id", None)
                        or (
                            getattr(prev_segment, "final_frame_asset_id", None)
                            or prev_metadata.get("extracted_last_frame_asset_id")
                            if prev_segment
                            else None
                        )
                    )
                    initial_frame_url = _asset_content_url(initial_asset_id)
                    final_frame_url = _asset_content_url(
                        getattr(segment, "final_frame_asset_id", None)
                        or metadata.get("final_frame_asset_id")
                    )
                    video_url = _asset_content_url(
                        getattr(segment, "generated_video_asset_id", None)
                    )
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
                            ui.label("Prompt de vídeo do segmento").classes(
                                "text-sm text-[#8d938e]"
                            )
                        with ui.grid().classes(
                            "w-full grid-cols-1 gap-4 flex-1 min-h-0 mt-4 overflow-hidden"
                        ):
                            segment_prompt_input = (
                                ui.textarea(
                                    "Prompt de vídeo",
                                    value=str(getattr(segment, "prompt", "") or ""),
                                )
                                .props("outlined")
                                .classes("storyboard-prompt-textarea w-full h-full")
                            )

                        async def save_segment_prompt(
                            segment_id: UUID = segment.id,
                            flow_input: Any = segment_prompt_input,
                            dialog: Any = segment_prompt_dialog,
                        ) -> None:
                            new_prompt = str(flow_input.value or "").strip()
                            if not new_prompt:
                                ui.notify(
                                    "Informe o prompt de vídeo antes de salvar.", color="warning"
                                )
                                return
                            safe_close_ui_element(dialog)
                            await _save_continuous_video_segment_prompt_from_ui(
                                project_id,
                                segment_id,
                                new_prompt,
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
                                ui.label("Frame inicial e frame final").classes(
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
                        remove_final_cb: Any = (
                            None
                            if is_preparing_segment
                            else (
                                lambda s_id=seg_id: _remove_continuous_video_segment_frame_from_ui(
                                    project_id,
                                    s_id,
                                    "final",
                                )
                            )
                        )
                        with ui.grid().classes(
                            "w-full grid-cols-1 lg:grid-cols-2 gap-4 mt-4 flex-1 min-h-0 overflow-y-auto"
                        ):
                            with ui.column().classes("w-full min-h-0 gap-2"):
                                if video_url:
                                    _render_continuous_media_preview(
                                        "Vídeo gerado",
                                        video_url,
                                        media_kind="video",
                                        large=True,
                                    )
                                elif segment.segment_number > 1 and initial_frame_url:
                                    _render_continuous_media_preview(
                                        "Frame inicial (Continuado)",
                                        initial_frame_url,
                                        media_kind="image",
                                        large=True,
                                        remove_on_click=remove_initial_cb,
                                    )
                            with ui.column().classes("w-full min-h-0 gap-2"):
                                if final_frame_url:
                                    _render_continuous_media_preview(
                                        "Último frame extraído",
                                        final_frame_url,
                                        media_kind="image",
                                        large=True,
                                        remove_on_click=remove_final_cb,
                                    )
                                elif not video_url and initial_frame_url:
                                    _render_continuous_media_preview(
                                        "Frame inicial",
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
                                ui.label(
                                    f"{int(getattr(segment, 'duration_seconds', 0) or 0)}s "
                                    f"· {continuous_video_status_label(status_value)}"
                                ).classes("text-xs text-[#8d938e]")
                            if status_value in {"ready", "ready_for_review"}:
                                status_badge_classes = "blue-status-badge bg-[#5aa3f0] text-white"
                            elif status_value in {"done", "approved", "succeeded"}:
                                status_badge_classes = "bg-[#26301f] text-white"
                            elif status_value in {"failed", "rejected"}:
                                status_badge_classes = "bg-[#4b2a2a] text-[#ffd4d4]"
                            else:
                                status_badge_classes = "blue-status-badge bg-[#243342]"
                            ui.badge(
                                continuous_video_status_label(status_value) or "pendente"
                            ).classes(status_badge_classes)
                        if video_url or final_frame_url or initial_frame_url:
                            with ui.grid().classes("w-full grid-cols-2 gap-3 mt-3"):
                                # Slot esquerdo: video ou frame inicial
                                if video_url:
                                    _render_continuous_media_preview(
                                        "Video gerado",
                                        video_url,
                                        media_kind="video",
                                    )
                                elif segment.segment_number > 1 and initial_frame_url:
                                    _render_continuous_media_preview(
                                        "Frame inicial (Continuado)",
                                        initial_frame_url,
                                        media_kind="image",
                                        remove_on_click=remove_initial_cb,
                                    )
                                elif initial_frame_url:
                                    _render_continuous_media_preview(
                                        "Frame inicial",
                                        initial_frame_url,
                                        media_kind="image",
                                        remove_on_click=remove_initial_cb,
                                    )
                                else:
                                    _render_continuous_media_preview(
                                        "Video", "", media_kind="video"
                                    )
                                # Slot direito: frame extraido ou video
                                if final_frame_url:
                                    _render_continuous_media_preview(
                                        "Ultimo frame extraido",
                                        final_frame_url,
                                        media_kind="image",
                                        remove_on_click=remove_final_cb,
                                    )
                                elif video_url:
                                    _render_continuous_media_preview(
                                        "Video", video_url, media_kind="video"
                                    )
                                else:
                                    _render_continuous_media_preview(
                                        "Video", "", media_kind="video"
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
                                ui.label("Gerando vídeo contínuo. Atualize para verificar.")
                        if visual_summary:
                            ui.label(visual_summary).classes("text-xs text-[#8d938e] mt-2")
                        if qa_result is not None:
                            with ui.row().classes("items-center gap-2 mt-2 flex-wrap"):
                                ui.badge(f"QA {qa_result.total_score}/100").classes(
                                    "blue-status-badge bg-[#243342]"
                                )
                                ui.badge(
                                    "Revisão humana" if qa_result.needs_human_review
                                    else "Falha objetiva"
                                ).classes("blue-status-badge bg-[#26301f]")
                            if qa_result.reasons:
                                ui.label("; ".join(str(x) for x in qa_result.reasons[:3])).classes(
                                    "text-xs text-[#d1d4d1] mt-1"
                                )
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
                                ).props("flat dense no-caps").classes(
                                    "text-[#ffb4b4] rounded-xl"
                                )
                            if status_value in {"ready", "ready_for_review"}:
                                ui.button(
                                    "Aprovar",
                                    icon="check",
                                    on_click=lambda segment_id=segment.id: (
                                        _approve_continuous_video_segment_from_ui(
                                            project_id, segment_id
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes("acid-bg rounded-xl")
                                ui.button(
                                    "Rejeitar",
                                    icon="close",
                                    on_click=lambda segment_id=segment.id: (
                                        _reject_continuous_video_segment_from_ui(
                                            project_id, segment_id
                                        )
                                    ),
                                ).props("flat dense no-caps").classes(
                                    "text-[#ffb4b4] rounded-xl"
                                )
                            if initial_frame_url or final_frame_url or video_url:
                                ui.button(
                                    "Visualizar",
                                    icon="open_in_full",
                                    on_click=segment_media_dialog.open,
                                ).props("flat dense no-caps").classes("rounded-xl")
                            has_initial_frame = bool(initial_frame_url)
                            can_generate_video = (
                                not video_url
                                and not is_preparing_segment
                                and (has_initial_frame or segment.segment_number <= 1)
                            )
                            if can_generate_video:
                                ui.button(
                                    "Gerar vídeo",
                                    icon="movie_creation",
                                    on_click=lambda segment_id=segment.id: (
                                        _generate_continuous_video_from_ui(
                                            project_id,
                                            segment_ids=[segment_id],
                                            loading_dialog=video_generate_dialog,
                                            progress_callback=_video_generate_progress_callback,
                                        )
                                    ),
                                ).props("unelevated dense no-caps").classes(
                                    "acid-bg rounded-xl min-w-[104px]"
                                )
                            elif (
                                not video_url
                                and not is_preparing_segment
                                and segment.segment_number > 1
                            ):
                                prev_num = segment.segment_number - 1
                                ui.label(
                                    f"Gere o vídeo do Segmento {prev_num:02d} primeiro para obter o frame inicial"
                                ).classes("text-xs text-amber-300/80 self-center")
                            elif video_url and not is_preparing_segment:
                                ui.button(
                                    "Regenerar vídeo",
                                    icon="refresh",
                                    on_click=lambda segment_id=segment.id: (
                                        _generate_continuous_video_from_ui(
                                            project_id,
                                            segment_ids=[segment_id],
                                            loading_dialog=video_generate_dialog,
                                            progress_callback=_video_generate_progress_callback,
                                        )
                                    ),
                                ).props("flat dense no-caps").classes("text-[#d8dbd8] rounded-xl")
                            ui.button(
                                "Editar prompt",
                                icon="edit",
                                on_click=segment_prompt_dialog.open,
                            ).props(
                                "flat dense no-caps" + (" disable" if is_preparing_segment else "")
                            ).classes("text-[#d8dbd8] rounded-xl")
        else:
            with ui.element("div").classes("entity-card rounded-2xl p-6 w-full mt-4"):
                ui.label("Nenhum segmento planejado").classes("brand-type text-xl font-bold")
                ui.label("Planeje os segmentos diretamente a partir do roteiro.").classes(
                    "text-sm text-[#8d938e] leading-6"
                )

    if summary["clips"]:
        with ui.row().classes("w-full items-end justify-between gap-3 mt-6"):
            with ui.column().classes("gap-0"):
                ui.label("Clipes legados").classes("brand-type text-2xl font-bold")
                ui.label(
                    "Hist\u00f3rico de clipes gerados antes da transi\u00e7\u00e3o de vídeo."
                ).classes("text-sm text-[#8d938e]")
            ui.badge(f"{len(summary['clips'])} clipe(s)").classes("blue-status-badge bg-[#243342]")
        with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
            for i, clip in enumerate(summary["clips"], 1):
                clip_url = _video_clip_asset_url(clip)
                with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
                    with ui.element("div").classes(
                        "visual-placeholder aspect-video flex items-center justify-center relative bg-black overflow-hidden"
                    ):
                        if clip_url:
                            ui.video(clip_url, controls=True).classes(
                                "w-full h-full object-contain"
                            )
                        else:
                            ui.icon("movie_creation").classes("text-5xl text-[#bdc77b]")
                    with ui.column().classes("p-4 gap-2"):
                        with ui.row().classes("w-full justify-between"):
                            ui.label(f"Clipe {i:02d}").classes("font-semibold")
                            ui.badge(
                                "Selecionado" if clip.selected else "Varia\u00e7\u00e3o"
                            ).classes("bg-[#30362b] text-[#eaf878]")
                        ui.label(f"{clip.duration_seconds}s \u00b7 {clip.model}").classes(
                            "text-xs text-[#878d88]"
                        )
