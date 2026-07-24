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
    _regenerate_visual_reference_from_ui,
    _update_visual_prompt_from_ui,
    _visual_batch_requests,
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
    visual_reference_prompt,
)

VISUAL_LIBRARY_TAB_DEFAULT = "characters"
VISUAL_LIBRARY_TAB_KEYS = {"characters", "locations", "props"}


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
) -> None:
    if not existing_views:
        requested_views = [initial_view_for(target_kind)]
        approval_label = "Aprovar prompt"
    else:
        requested_views = [
            view for view in default_views_for(target_kind) if view not in existing_views
        ]
        approval_label = "Aprovar vistas"
    prompt_previews = [
        (view_type, visual_reference_prompt(profile, view_type))
        for view_type in requested_views
    ]
    current_prompt = str(profile.get("canonical_prompt") or title).strip()
    reference_assets = [
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

    with ui.element("div").classes("entity-card rounded-2xl overflow-hidden"):
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
                                    "w-full aspect-[9/16] object-contain bg-black"
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
                                        await _regenerate_visual_reference_from_ui(
                                            project_id,
                                            target_kind,
                                            target_id,
                                            view_type,
                                        )

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
        with ui.element("div").classes(
            "visual-placeholder h-44 p-0 flex items-stretch cursor-pointer"
        ).on("click", gallery_dialog.open):
            if hero_reference is not None:
                _reference, _asset, hero_url = hero_reference
                ui.image(hero_url).classes("w-full h-full object-cover").props("fit=cover")
            else:
                with ui.element("div").classes("w-full h-full p-5 flex items-end"):
                    ui.icon(icon).classes("text-6xl text-[#eefa83]")
        with ui.column().classes("p-4 gap-2"):
            ui.label(title).classes("brand-type text-xl font-bold")
            ui.label(subtitle).classes("text-xs acid uppercase tracking-wide")
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
                    await _approve_visual_target_from_ui(
                        project_id,
                        target_kind,
                        target_id,
                        views,
                    )

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Cancelar", on_click=prompt_dialog.close).props("flat no-caps")
                    confirm_button = ui.button(
                        "Aprovar e gerar",
                        icon="check_circle",
                        on_click=confirm_visual_prompts,
                    ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                    if not prompt_previews:
                        confirm_button.props("disable")
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
                        await _regenerate_visual_reference_from_ui(
                            project_id,
                            target_kind,
                            target_id,
                            view_type,
                        )

                    ui.button(
                        "Gerar novamente",
                        icon="refresh",
                        on_click=regenerate_hero_reference,
                    ).props("flat dense no-caps").classes("text-[#d8dbd8]")


def render_assets_area(
    project_id: UUID,
    summary: dict[str, Any],
    *,
    section_title: Callable[[str, str, str | None, Any | None], None],
    loading_dialog_factory: Callable[[str, str], Any],
) -> None:
    asset_map = {asset.id: asset for asset in summary.get("assets", [])}
    section_title(
        "Biblioteca visual",
        "Personagens, locais e objetos canônicos do seu universo.",
        None,
        None,
    )
    batch_requests = _visual_batch_requests(summary)
    if batch_requests:
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
        batch_loading_dialog = loading_dialog_factory(
            "Gerando imagens",
            "A IA está criando as imagens aprovadas da Biblioteca Visual.",
        )
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
                try:
                    await _approve_all_visual_targets_from_ui(project_id)
                finally:
                    batch_loading_dialog.close()

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Cancelar", on_click=batch_prompt_dialog.close).props("flat no-caps")
                ui.button(
                    "Aprovar e gerar imagens",
                    icon="check_circle",
                    on_click=confirm_batch_prompts,
                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
        with ui.row().classes("w-full justify-end mb-3"):
            pending_count = sum(len(view_types) for _kind, _id, view_types in batch_requests)
            ui.button(
                f"Aprovar prompts pendentes ({pending_count})",
                icon="check_circle",
                on_click=lambda: batch_prompt_dialog.open(),
            ).props("unelevated no-caps").classes("acid-bg rounded-xl")
    active_tab = _read_visual_library_active_tab(project_id)
    with ui.tabs(value=cast(Any, active_tab)).classes("text-[#8d938e]") as tabs:
        people = ui.tab("characters", "Personagens")
        places = ui.tab("locations", "Locais")
        props = ui.tab("props", "Objetos")
    tabs.on_value_change(
        lambda event: _store_visual_library_active_tab(
            project_id, str(event.value or VISUAL_LIBRARY_TAB_DEFAULT)
        )
    )
    with ui.tab_panels(tabs, value=cast(Any, active_tab)).classes("w-full bg-transparent p-0"):
        for tab, items, icon, target_kind in [
            (people, summary["characters"], "person", "character"),
            (places, summary["locations"], "location_on", "location"),
            (props, summary["props"], "category", "prop"),
        ]:
            with ui.tab_panel(tab).classes("px-0"):
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
                        )
                    if not items:
                        with ui.element("div").classes("entity-card rounded-2xl p-8"):
                            ui.icon(icon).classes("text-4xl acid")
                            ui.label("Nada criado ainda").classes("text-lg font-semibold")
                            ui.label(
                                "O Diretor IA pode criar esta coleção a partir do roteiro."
                            ).classes("text-sm text-[#888e89]")

