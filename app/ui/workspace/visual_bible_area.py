from typing import Any, cast
from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.visual_bible.image_generation import (
    generate_visual_reference,
    set_visual_reference_status,
)
from app.visual_bible.reference_planning import TargetKind, plan_visual_references


def render_visual_bible_area(project_id: UUID, summary: dict[str, Any]) -> None:
    characters = list(summary.get("characters") or [])
    locations = list(summary.get("locations") or [])
    references = list(summary.get("visual_refs") or [])
    assets = {asset.id: asset for asset in summary.get("assets") or []}

    with ui.row().classes("w-full items-center justify-between gap-3"):
        with ui.column().classes("gap-1"):
            ui.label("Visual Bible").classes("text-3xl font-bold")
            ui.label("Personagens, locais e referências canônicas versionadas.").classes(
                "text-sm text-slate-400"
            )
        ui.badge(f"{len(references)} referências").classes("bg-slate-800")

    if not characters and not locations:
        ui.label("Gere os perfis visuais a partir do roteiro antes de criar imagens.").classes(
            "text-amber-200"
        )
        return

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
                _target_card(project_id, target_kind, target, target_refs, assets)


def _target_card(
    project_id: UUID,
    target_kind: str,
    target: Any,
    references: list[Any],
    assets: dict[UUID, Any],
) -> None:
    with ui.card().classes("w-full border border-slate-800 bg-slate-950"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label(str(target.name)).classes("text-lg font-semibold")
                ui.label(str(getattr(target, "role", "") or target_kind)).classes(
                    "text-xs text-slate-400"
                )

            async def generate_all() -> None:
                ui.notify("Gerando referências visuais...", color="info")
                try:
                    plan = plan_visual_references(
                        cast(TargetKind, target_kind),
                        target.id,
                        dict(target.canonical_profile or {}),
                    )
                    async with AsyncSessionLocal() as session:
                        for item in plan.items:
                            await generate_visual_reference(
                                session,
                                project_id,
                                target_kind,
                                target.id,
                                item.view_type,
                                prompt_override=item.prompt,
                            )
                    ui.notify("Referências geradas.", color="positive")
                    ui.navigate.reload()
                except Exception as exc:
                    ui.notify(f"Não foi possível gerar referências: {exc}", color="negative")

            ui.button("Gerar referências", icon="auto_awesome", on_click=generate_all).props(
                "unelevated no-caps"
            )

        with ui.element("div").classes("grid grid-cols-2 md:grid-cols-3 gap-3 w-full"):
            for reference in references:
                asset = assets.get(reference.asset_id)
                with ui.card().classes("p-2 gap-2 bg-slate-900"):
                    if asset is not None:
                        image_url = f"/api/v1/assets/{asset.id}/content"
                        ui.image(image_url).classes(
                            "w-full aspect-[9/16] object-cover rounded cursor-pointer"
                        ).on("click", lambda url=image_url: _open_image_dialog(url))
                    ui.label(reference.view_type).classes("text-sm font-medium")
                    ui.label(reference.status).classes("text-xs text-slate-400")
                    if reference.is_canonical:
                        ui.badge("Canônica").classes("bg-emerald-800")
                    with ui.row().classes("gap-1"):

                        async def approve(ref_id: UUID = reference.id) -> None:
                            async with AsyncSessionLocal() as session:
                                await set_visual_reference_status(
                                    session, project_id, ref_id, "approved", canonical=True
                                )
                            ui.navigate.reload()

                        async def reject(ref_id: UUID = reference.id) -> None:
                            async with AsyncSessionLocal() as session:
                                await set_visual_reference_status(
                                    session, project_id, ref_id, "rejected"
                                )
                            ui.navigate.reload()

                        async def regenerate(ref: Any = reference) -> None:
                            async with AsyncSessionLocal() as session:
                                await generate_visual_reference(
                                    session,
                                    project_id,
                                    ref.target_kind,
                                    ref.target_id,
                                    ref.view_type,
                                    prompt_override=ref.prompt,
                                )
                            ui.navigate.reload()

                        ui.button(icon="check", on_click=approve).props("flat round dense").tooltip(
                            "Aprovar como canônica"
                        )
                        ui.button(icon="refresh", on_click=regenerate).props(
                            "flat round dense"
                        ).tooltip("Regenerar")
                        ui.button(icon="close", on_click=reject).props("flat round dense").tooltip(
                            "Rejeitar"
                        )


def _open_image_dialog(url: str) -> None:
    with ui.dialog() as dialog, ui.card().classes("max-w-4xl bg-black"):
        ui.image(url).classes("max-h-[85vh] max-w-full object-contain")
        ui.button("Fechar", on_click=dialog.close).props("flat no-caps")
    dialog.open()
