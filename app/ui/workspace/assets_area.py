from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from nicegui import app as nicegui_app
from nicegui import ui

from app.assets.models import Asset
from app.ui.shared.page_config import BLOCKING_DIALOG_PROPS
from app.ui.visual.actions import (
    _approve_all_visual_targets_from_ui,
    _approve_visual_target_from_ui,
    _generate_all_visual_prompts_from_ui,
    _regenerate_visual_reference_from_ui,
    _update_visual_prompt_from_ui,
    _visual_batch_requests,
    _visual_prompts_need_generation,
)
from app.ui.visual.helpers import (
    asset_url,
)
from app.ui.visual.helpers import (
    visual_card_detail as _visual_card_detail,
)
from app.ui.visual.helpers import (
    visual_reference_asset as _visual_reference_asset,
)
from app.ui.visual.helpers import (
    visual_reference_views_for as _visual_reference_views_for,
)
from app.ui.visual.helpers import (
    visual_references_for as _visual_references_for,
)
from app.visual_bible.models import VisualReference
from app.visual_bible.service import (
    default_views_for,
    initial_view_for,
    visual_reference_aspect_ratio,
    visual_reference_prompt,
)

VISUAL_LIBRARY_TAB_DEFAULT = "characters"
VISUAL_LIBRARY_TAB_KEYS = {"characters", "locations", "props"}
CHARACTER_REFERENCE_SHEET_VIEW = "character_reference_sheet"
ReferenceAsset = tuple[VisualReference, Asset, str]


def _progress_ratio(done: int, total: int) -> float:
    return min(max(done / total, 0.0), 1.0) if total else 0.0


def _visual_reference_progress_for(
    summary: dict[str, Any],
    target_kind: str,
    items: list[Any],
) -> dict[str, int]:
    required_views = default_views_for(target_kind)
    expected = len(items) * len(required_views)
    generated = 0
    for item in items:
        existing_views = _visual_reference_views_for(summary, target_kind, item.id)
        generated += sum(1 for view in required_views if view in existing_views)
    return {
        "generated": generated,
        "expected": expected,
        "missing": max(expected - generated, 0),
    }


def _visual_reference_progress_summary(summary: dict[str, Any]) -> dict[str, Any]:
    by_kind = {
        "characters": _visual_reference_progress_for(
            summary, "character", summary["characters"]
        ),
        "locations": _visual_reference_progress_for(summary, "location", summary["locations"]),
        "props": _visual_reference_progress_for(summary, "prop", summary["props"]),
    }
    generated = sum(item["generated"] for item in by_kind.values())
    expected = sum(item["expected"] for item in by_kind.values())
    return {
        "generated": generated,
        "expected": expected,
        "missing": max(expected - generated, 0),
        "by_kind": by_kind,
    }


def _render_visual_progress_summary(summary: dict[str, Any]) -> None:
    progress = _visual_reference_progress_summary(summary)
    expected = progress["expected"]
    generated = progress["generated"]
    missing = progress["missing"]
    labels = {
        "characters": "Personagens",
        "locations": "Locais",
        "props": "Objetos",
    }
    with ui.element("div").classes(
        "w-full border border-[#343934] rounded-xl px-4 py-3 bg-[#0d100e] mb-2"
    ):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("gap-0"):
                ui.label(f"Referências obrigatórias: {generated}/{expected}").classes(
                    "text-sm font-semibold text-[#d8dbd8]"
                )
                ui.label(f"Faltam {missing} imagem(ns).").classes("text-xs text-[#8d938e]")
            ui.badge("pronto" if missing == 0 and expected else "pendente").classes(
                "bg-[#26301f] text-[#eaf878]"
                if missing == 0 and expected
                else "blue-status-badge bg-[#243342]"
            )
        ui.linear_progress(value=_progress_ratio(generated, expected)).classes(
            "w-full mt-3"
        ).props("instant-feedback rounded")
        with ui.row().classes("w-full gap-2 mt-3"):
            for key, label in labels.items():
                item = progress["by_kind"][key]
                ui.badge(f"{label}: {item['generated']}/{item['expected']}").classes(
                    "blue-status-badge bg-[#243342]"
                )


def _visual_library_tab_storage_key(project_id: UUID) -> str:
    return f"visual_library_active_tab:{project_id}"


def _read_visual_library_active_tab(project_id: UUID) -> str:
    raw_value = str(
        nicegui_app.storage.user.get(
            _visual_library_tab_storage_key(project_id), VISUAL_LIBRARY_TAB_DEFAULT
        )
    ).strip()
    return raw_value if raw_value in VISUAL_LIBRARY_TAB_KEYS else VISUAL_LIBRARY_TAB_DEFAULT


def _store_visual_library_active_tab(project_id: UUID, tab_name: str) -> None:
    value = tab_name if tab_name in VISUAL_LIBRARY_TAB_KEYS else VISUAL_LIBRARY_TAB_DEFAULT
    nicegui_app.storage.user[_visual_library_tab_storage_key(project_id)] = value


def _visual_reference_aspect_class(profile: dict, reference: VisualReference) -> str:
    metadata = reference.metadata_json if isinstance(reference.metadata_json, dict) else {}
    aspect_ratio = str(
        metadata.get("aspect_ratio")
        or visual_reference_aspect_ratio(profile, reference.view_type)
        or ""
    ).strip()
    if aspect_ratio == "1:1":
        return "aspect-square"
    if aspect_ratio in {"16:9", "4:3"}:
        return "aspect-video"
    return "aspect-[9/16]"


def _visual_reference_preview_width_class(profile: dict, reference: VisualReference) -> str:
    metadata = reference.metadata_json if isinstance(reference.metadata_json, dict) else {}
    aspect_ratio = str(
        metadata.get("aspect_ratio")
        or visual_reference_aspect_ratio(profile, reference.view_type)
        or ""
    ).strip()
    if aspect_ratio == "1:1":
        return "w-[min(720px,94vw)]"
    if aspect_ratio in {"16:9", "4:3"}:
        return "w-[min(1180px,94vw)]"
    return "w-[min(520px,94vw)]"


def _character_reference_sheet_asset(
    target_kind: str,
    reference_assets: list[ReferenceAsset],
) -> ReferenceAsset | None:
    if target_kind != "character":
        return None
    return next(
        (
            reference_asset
            for reference_asset in reference_assets
            if reference_asset[0].view_type == "character_reference_sheet"
        ),
        None,
    )


def _render_reference_preview_dialog(
    profile: dict,
    reference_asset: ReferenceAsset | None,
) -> Any:
    with ui.dialog() as image_preview_dialog:
        if reference_asset is not None:
            reference, _asset, preview_url = reference_asset
            aspect_class = _visual_reference_aspect_class(profile, reference)
            preview_width_class = _visual_reference_preview_width_class(profile, reference)
            with ui.element("div").classes(
                f"relative {preview_width_class} max-h-[92vh]"
            ):
                ui.image(preview_url).classes(
                    "w-full max-h-[92vh] "
                    f"{aspect_class} bg-black rounded-xl overflow-hidden"
                ).props("fit=contain")
                ui.button(
                    icon="close",
                    on_click=image_preview_dialog.close,
                ).props("round dense unelevated").classes(
                    "absolute top-3 right-3 bg-black/70 text-white"
                )
    return image_preview_dialog


def _entity_card(
    project_id: UUID,
    target_kind: str,
    target_id: UUID,
    profile: dict,
    existing_views: set[str],
    references: list[VisualReference],
    asset_map: dict[UUID, Asset],
    icon: str,
    title: str,
    subtitle: str,
    detail: str,
    loading_dialog_factory: Callable[[str, str], Any],
) -> None:
    if not existing_views:
        requested_views = [initial_view_for(target_kind)]
        approval_label = "Aprovar prompt"
    else:
        requested_views = [
            view for view in default_views_for(target_kind) if view not in existing_views
        ]
        approval_label = "Aprovar vistas"
    required_views = default_views_for(target_kind)
    required_generated = sum(1 for view in required_views if view in existing_views)
    required_expected = len(required_views)
    optional_sheet_views = (
        [CHARACTER_REFERENCE_SHEET_VIEW]
        if target_kind == "character"
        and initial_view_for(target_kind) in existing_views
        and CHARACTER_REFERENCE_SHEET_VIEW not in existing_views
        else []
    )
    prompt_previews = [
        (view_type, visual_reference_prompt(profile, view_type))
        for view_type in requested_views
    ]
    optional_sheet_prompt_previews = [
        (view_type, visual_reference_prompt(profile, view_type))
        for view_type in optional_sheet_views
    ]
    current_prompt = str(profile.get("canonical_prompt") or title).strip()
    reference_assets: list[ReferenceAsset] = [
        (reference, asset, asset_url(asset.storage_uri))
        for reference in references
        if (asset := _visual_reference_asset(asset_map, reference)) is not None
    ]
    reference_assets = [
        (reference, asset, image_url)
        for reference, asset, image_url in reference_assets
        if image_url
    ]
    hero_reference = reference_assets[0] if reference_assets else None
    character_reference_sheet = _character_reference_sheet_asset(
        target_kind, reference_assets
    )
    show_character_reference_sheet = (
        character_reference_sheet is not None
        and character_reference_sheet != hero_reference
    )
    hero_aspect_class = (
        _visual_reference_aspect_class(profile, hero_reference[0])
        if hero_reference
        else "aspect-[9/16]"
    )
    loading_dialog = loading_dialog_factory(
        "Gerando imagem",
        f"A IA está criando a referência visual de {title}.",
    )

    with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
        image_preview_dialog = _render_reference_preview_dialog(profile, hero_reference)
        reference_sheet_preview_dialog = _render_reference_preview_dialog(
            profile, character_reference_sheet if show_character_reference_sheet else None
        )
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as gallery_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(980px,94vw)] max-h-[90vh]"
        ):
            ui.label(f"Referências visuais - {title}").classes("brand-type text-2xl font-bold")
            if reference_assets:
                with ui.scroll_area().classes("w-full max-h-[72vh] pr-2"):
                    with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 gap-4"):
                        for reference, asset, image_url in reference_assets:
                            with ui.element("div").classes(
                                "border border-[#343934] rounded-xl overflow-hidden"
                            ):
                                ui.image(image_url).classes(
                                    "w-full "
                                    f"{_visual_reference_aspect_class(profile, reference)} "
                                    "object-contain bg-black"
                                ).props("fit=contain")
                                with ui.column().classes("p-3 gap-1"):
                                    ui.label(reference.view_type).classes(
                                        "text-xs acid uppercase"
                                    )
                                    ui.label(asset.name).classes("text-sm text-[#d8dbd8]")
                                    ui.label(reference.prompt).classes(
                                        "text-xs text-[#8d938e] line-clamp-3"
                                    )
                                    async def regenerate_gallery_reference(
                                        view_type: str = reference.view_type,
                                    ) -> None:
                                        gallery_dialog.close()
                                        loading_dialog.open()
                                        try:
                                            await _regenerate_visual_reference_from_ui(
                                                project_id,
                                                target_kind,
                                                target_id,
                                                view_type,
                                            )
                                        finally:
                                            loading_dialog.close()

                                    ui.button(
                                        "Gerar novamente",
                                        icon="refresh",
                                        on_click=regenerate_gallery_reference,
                                    ).props("flat dense no-caps").classes("text-[#d8dbd8]")
            else:
                ui.label("Nenhuma imagem gerada para este ativo.").classes(
                    "text-sm text-[#8d938e]"
                )
            with ui.row().classes("w-full justify-end mt-3"):
                ui.button("Fechar", on_click=gallery_dialog.close).props("flat no-caps")
        preview_target = ui.element("div").classes(
            "visual-placeholder p-0 flex items-stretch cursor-pointer "
            f"{hero_aspect_class}"
        )
        if hero_reference is not None:
            preview_target.on("click", image_preview_dialog.open)
        with preview_target:
            if hero_reference is not None:
                _reference, _asset, hero_url = hero_reference
                ui.image(hero_url).classes("w-full h-full object-contain bg-black").props(
                    "fit=contain"
                )
            else:
                with ui.element("div").classes("w-full h-full p-5 flex items-end"):
                    ui.icon(icon).classes("text-6xl text-[#eefa83]")
        if show_character_reference_sheet and character_reference_sheet is not None:
            _reference, _asset, reference_sheet_url = character_reference_sheet
            reference_sheet_target = ui.element("div").classes(
                "relative h-28 border-t border-[#292d29] bg-black cursor-pointer"
            )
            reference_sheet_target.on("click", reference_sheet_preview_dialog.open)
            with reference_sheet_target:
                ui.image(reference_sheet_url).classes(
                    "w-full h-full object-contain bg-black"
                ).props("fit=contain")
                ui.label("Múltiplas vistas").classes(
                    "absolute left-3 bottom-3 rounded-full bg-black/70 px-3 py-1 "
                    "text-[11px] font-semibold uppercase text-white"
                )
        with ui.column().classes("p-4 gap-2"):
            ui.label(title).classes("brand-type text-xl font-bold")
            ui.label(subtitle).classes("text-xs acid uppercase tracking-wide")
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label(
                    f"Referência obrigatória: {required_generated}/{required_expected}"
                ).classes("text-xs text-[#c6cbc6]")
                if target_kind == "character":
                    sheet_status = (
                        "múltiplas vistas pronta"
                        if CHARACTER_REFERENCE_SHEET_VIEW in existing_views
                        else "múltiplas vistas opcional"
                    )
                    ui.badge(sheet_status).classes("bg-[#20251f] text-[#c9cec9]")
            ui.linear_progress(
                value=_progress_ratio(required_generated, required_expected)
            ).classes("w-full").props("instant-feedback rounded")
            ui.label(detail).classes("text-sm text-[#999f9a] line-clamp-2")
            with ui.dialog().props(BLOCKING_DIALOG_PROPS) as prompt_dialog, ui.card().classes(
                "entity-card rounded-2xl p-6 w-[min(760px,92vw)] max-h-[82vh]"
            ):
                ui.label("Aprovar prompts de imagem").classes("brand-type text-2xl font-bold")
                ui.label(
                    "Confira os prompts antes de criar as imagens deste ativo."
                ).classes("text-sm text-[#8d938e]")
                with ui.scroll_area().classes("w-full max-h-[52vh] pr-2"):
                    with ui.column().classes("w-full gap-3"):
                        for view_type, prompt in prompt_previews:
                            with ui.element("div").classes(
                                "border border-[#343934] rounded-xl p-4"
                            ):
                                ui.label(view_type).classes("text-xs acid uppercase")
                                ui.label(prompt).classes(
                                    "text-sm text-[#d8dbd8] whitespace-pre-wrap"
                                )
                        if not prompt_previews:
                            ui.label("Todas as vistas deste ativo já foram criadas.").classes(
                                "text-sm text-[#8d938e]"
                            )

                async def confirm_visual_prompts(
                    views: list[str] = requested_views,
                ) -> None:
                    prompt_dialog.close()
                    loading_dialog.open()
                    try:
                        await _approve_visual_target_from_ui(
                            project_id,
                            target_kind,
                            target_id,
                            views,
                        )
                    finally:
                        loading_dialog.close()

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancelar", on_click=prompt_dialog.close).props("flat no-caps")
                    confirm_button = ui.button(
                        "Aprovar e gerar",
                        icon="check_circle",
                        on_click=confirm_visual_prompts,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    if not prompt_previews:
                        confirm_button.props("disable")
            with (
                ui.dialog().props(BLOCKING_DIALOG_PROPS) as optional_sheet_dialog,
                ui.card().classes("entity-card rounded-2xl p-6 w-[min(760px,92vw)] max-h-[82vh]"),
            ):
                ui.label("Gerar múltiplas vistas").classes("brand-type text-2xl font-bold")
                with ui.scroll_area().classes("w-full max-h-[52vh] pr-2"):
                    with ui.column().classes("w-full gap-3"):
                        for view_type, prompt in optional_sheet_prompt_previews:
                            with ui.element("div").classes(
                                "border border-[#343934] rounded-xl p-4"
                            ):
                                ui.label(view_type).classes("text-xs acid uppercase")
                                ui.label(prompt).classes(
                                    "text-sm text-[#d8dbd8] whitespace-pre-wrap"
                                )
                        if not optional_sheet_prompt_previews:
                            ui.label("A folha de múltiplas vistas já foi criada.").classes(
                                "text-sm text-[#8d938e]"
                            )

                async def confirm_optional_sheet(
                    views: list[str] = optional_sheet_views,
                ) -> None:
                    optional_sheet_dialog.close()
                    loading_dialog.open()
                    try:
                        await _approve_visual_target_from_ui(
                            project_id,
                            target_kind,
                            target_id,
                            views,
                        )
                    finally:
                        loading_dialog.close()

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancelar", on_click=optional_sheet_dialog.close).props(
                        "flat no-caps"
                    )
                    optional_button = ui.button(
                        "Gerar imagem",
                        icon="view_carousel",
                        on_click=confirm_optional_sheet,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    if not optional_sheet_prompt_previews:
                        optional_button.props("disable")
            with ui.dialog().props(BLOCKING_DIALOG_PROPS) as edit_prompt_dialog, ui.card().classes(
                "entity-card rounded-2xl p-6 w-[min(760px,92vw)]"
            ):
                ui.label("Editar prompt visual").classes("brand-type text-2xl font-bold")
                prompt_input = (
                    ui.textarea("Prompt canonico", value=current_prompt)
                    .props("outlined autogrow")
                    .classes("w-full")
                )

                async def save_visual_prompt() -> None:
                    new_prompt = str(prompt_input.value or "").strip()
                    if not new_prompt:
                        ui.notify("Informe um prompt antes de salvar.", color="warning")
                        return
                    edit_prompt_dialog.close()
                    await _update_visual_prompt_from_ui(
                        project_id,
                        target_kind,
                        target_id,
                        new_prompt,
                    )

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancelar", on_click=edit_prompt_dialog.close).props("flat no-caps")
                    ui.button(
                        "Salvar",
                        icon="save",
                        on_click=save_visual_prompt,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
            with ui.row().classes("w-full pt-2 border-t border-[#292d29]"):
                approval_button = ui.button(
                    approval_label,
                    icon="check_circle",
                    on_click=prompt_dialog.open,
                ).props("flat dense no-caps").classes("text-[#d8dbd8]")
                if not prompt_previews:
                    approval_button.props("disable")
                ui.button("Editar", icon="edit", on_click=edit_prompt_dialog.open).props(
                    "flat dense no-caps"
                ).classes("text-[#d8dbd8]")
                if hero_reference is not None:
                    hero_view_type = hero_reference[0].view_type

                    async def regenerate_hero_reference(
                        view_type: str = hero_view_type,
                    ) -> None:
                        loading_dialog.open()
                        try:
                            await _regenerate_visual_reference_from_ui(
                                project_id,
                                target_kind,
                                target_id,
                                view_type,
                            )
                        finally:
                            loading_dialog.close()

                    ui.button(
                        "Gerar novamente",
                        icon="refresh",
                        on_click=regenerate_hero_reference,
                    ).props("flat dense no-caps").classes("text-[#d8dbd8]")
                if optional_sheet_prompt_previews:
                    ui.button(
                        "Múltiplas vistas",
                        icon="view_carousel",
                        on_click=optional_sheet_dialog.open,
                    ).props("flat dense no-caps").classes("text-[#d8dbd8]")


def render_assets_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: Callable[[str, str, str | None, Any | None], None],
    loading_dialog_factory: Callable[[str, str], Any],
) -> None:
    del section_title
    asset_map = {asset.id: asset for asset in summary.get("assets", [])}
    prompts_need_generation = _visual_prompts_need_generation(summary)
    batch_requests = _visual_batch_requests(summary)
    batch_prompt_dialog: Any | None = None
    if batch_requests and not prompts_need_generation:
        target_lookup: dict[tuple[str, UUID], str] = {}
        target_profiles: dict[tuple[str, UUID], dict[str, Any]] = {}
        for target_kind, items in (
            ("character", summary["characters"]),
            ("location", summary["locations"]),
            ("prop", summary["props"]),
        ):
            for item in items:
                target_lookup[(target_kind, item.id)] = str(item.name)
                target_profiles[(target_kind, item.id)] = getattr(
                    item, "canonical_profile", {}
                ) or {}
        batch_total = sum(len(view_types) for _kind, _id, view_types in batch_requests)
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as batch_loading_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(520px,92vw)]"
        ):
            with ui.column().classes("w-full items-center gap-4"):
                ui.spinner(size="lg").classes("acid")
                ui.label("Gerando imagens").classes("brand-type text-2xl font-bold")
                batch_progress_label = ui.label(f"0/{batch_total} imagem(ns) processada(s)")
                batch_progress_label.classes("text-sm text-[#d8dbd8]")
                batch_progress_bar = ui.linear_progress(value=0).classes("w-full")
                batch_progress_bar.props("instant-feedback rounded")
                batch_progress_detail = ui.label(
                    "A IA está criando as imagens aprovadas da Biblioteca Visual."
                ).classes("text-xs text-[#8d938e] text-center")
        with ui.dialog().props(BLOCKING_DIALOG_PROPS) as batch_prompt_dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(820px,92vw)] max-h-[82vh]"
        ):
            ui.label("Aprovar prompts de imagem").classes("brand-type text-2xl font-bold")
            ui.label(
                "Confira os prompts pendentes antes de gerar as imagens da Biblioteca Visual."
            ).classes("text-sm text-[#8d938e]")
            with ui.scroll_area().classes("w-full max-h-[52vh] pr-2"):
                with ui.column().classes("w-full gap-3"):
                    for target_kind, target_id, view_types in batch_requests:
                        title = target_lookup.get((target_kind, target_id), target_kind)
                        profile = target_profiles.get((target_kind, target_id), {})
                        with ui.element("div").classes("border border-[#343934] rounded-xl p-4"):
                            ui.label(title).classes("text-sm font-semibold")
                            ui.label(", ".join(view_types)).classes("text-xs acid")
                            for view_type in view_types[:2]:
                                ui.label(visual_reference_prompt(profile, view_type)).classes(
                                    "text-xs text-[#aeb4af] whitespace-pre-wrap mt-2 line-clamp-3"
                                )

            async def confirm_batch_prompts() -> None:
                batch_prompt_dialog.close()
                batch_loading_dialog.open()

                def update_batch_progress(completed: int, total: int, detail: str) -> None:
                    safe_total = max(total, 1)
                    batch_progress_label.set_text(
                        f"{completed}/{total} imagem(ns) processada(s)"
                    )
                    batch_progress_bar.set_value(_progress_ratio(completed, safe_total))
                    batch_progress_detail.set_text(detail)

                try:
                    await _approve_all_visual_targets_from_ui(
                        project_id,
                        progress_callback=update_batch_progress,
                    )
                finally:
                    batch_loading_dialog.close()

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Cancelar", on_click=batch_prompt_dialog.close).props("flat no-caps")
                ui.button(
                    "Aprovar e gerar imagens",
                    icon="check_circle",
                    on_click=confirm_batch_prompts,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
    with ui.row().classes("w-full items-start justify-between gap-3 mb-1"):
        with ui.column().classes("gap-0"):
            ui.label("Biblioteca visual").classes("brand-type text-2xl font-bold leading-tight")
            ui.label("Personagens, locais e objetos canônicos do seu universo.").classes(
                "text-sm text-[#8e948f]"
            )
        if prompts_need_generation:
            prompt_loading_dialog = loading_dialog_factory(
                "Gerando prompts visuais",
                "A IA está criando prompts para personagens, locais e objetos.",
            )

            async def generate_all_visual_prompts() -> None:
                prompt_loading_dialog.open()
                try:
                    await _generate_all_visual_prompts_from_ui(project_id)
                finally:
                    prompt_loading_dialog.close()

            ui.button(
                "Gerar todos os prompts",
                icon="auto_awesome",
                on_click=generate_all_visual_prompts,
            ).props("unelevated no-caps").classes("acid-bg rounded-xl shrink-0")
        elif batch_prompt_dialog is not None:
            pending_count = sum(len(view_types) for _kind, _id, view_types in batch_requests)
            ui.button(
                f"Aprovar prompts pendentes ({pending_count})",
                icon="check_circle",
                on_click=batch_prompt_dialog.open,
            ).props("unelevated no-caps").classes("acid-bg rounded-xl shrink-0")
    if not prompts_need_generation:
        _render_visual_progress_summary(summary)
    active_tab = _read_visual_library_active_tab(project_id)
    with ui.tabs(value=cast(Any, active_tab)).classes("text-[#8d938e] mt-1") as tabs:
        people = ui.tab("characters", "Personagens")
        places = ui.tab("locations", "Locais")
        props = ui.tab("props", "Objetos")
    tabs.on_value_change(
        lambda event: _store_visual_library_active_tab(
            project_id, str(event.value or VISUAL_LIBRARY_TAB_DEFAULT)
        )
    )
    with ui.tab_panels(tabs, value=cast(Any, active_tab)).classes(
        "w-full bg-transparent p-0 mt-1"
    ):
        for tab, items, icon, target_kind in [
            (people, summary["characters"], "person", "character"),
            (places, summary["locations"], "location_on", "location"),
            (props, summary["props"], "category", "prop"),
        ]:
            with ui.tab_panel(tab).classes("px-0 py-1"):
                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
                    for item in items:
                        subtitle = (
                            getattr(item, "role", "Local")
                            if target_kind == "character"
                            else ("Objeto narrativo" if target_kind == "prop" else "Cenário")
                        )
                        profile = getattr(item, "canonical_profile", {}) or {}
                        detail = _visual_card_detail(
                            target_kind,
                            profile,
                            getattr(item, "description", None)
                            or getattr(item, "narrative_importance", None)
                            or "",
                        )
                        _entity_card(
                            project_id,
                            target_kind,
                            item.id,
                            profile,
                            _visual_reference_views_for(summary, target_kind, item.id),
                            _visual_references_for(summary, target_kind, item.id),
                            asset_map,
                            icon,
                            item.name,
                            subtitle,
                            detail,
                            loading_dialog_factory,
                        )
                    if not items:
                        with ui.element("div").classes("entity-card rounded-2xl p-8"):
                            ui.icon(icon).classes("text-4xl acid")
                            ui.label("Nada criado ainda").classes("text-lg font-semibold")
                            ui.label(
                                "O Diretor IA pode criar está coleção a partir do roteiro."
                            ).classes("text-sm text-[#888e89]")

