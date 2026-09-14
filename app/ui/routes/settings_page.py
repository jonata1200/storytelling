# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from nicegui import ui

from app.config.preferences import save_preferences
from app.config.settings import OLLAMA_CLOUD_TEXT_MODELS, get_settings
from app.database.session import AsyncSessionLocal
from app.observability.service import provider_channel_health
from app.providers.browser_bridge import (
    _any_project_chrome_in_use,
    close_browser,
    launch_authorization_console,
    resume_after_user_browser_close,
)
from app.storytelling.idea_lab import load_generated_ideas, load_saved_ideas

BodyStyle = Callable[[], None]
ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
SettingsTabKey = Callable[[str | None], str]
AsyncAction = Callable[[], Awaitable[None]]


def register_settings_page(
    *,
    body_style: BodyStyle,
    settings_tab_key: SettingsTabKey,
    project_cards: ProjectCardsLoader,
    home_sidebar: Callable[[str], None],
    theme_toggle: Callable[[], Any],
    purge_application_data_from_ui: AsyncAction,
    purge_all_ideas_from_ui: AsyncAction,
    purge_all_projects_from_ui: AsyncAction,
) -> None:
    @ui.page("/settings", response_timeout=15)
    async def settings_page(request: Request) -> None:
        body_style()
        current = get_settings()
        active_settings_tab = settings_tab_key(request.query_params.get("tab"))
        saved_idea_count = len(load_saved_ideas())
        generated_idea_count = len(load_generated_ideas())
        lab_idea_count = saved_idea_count + generated_idea_count
        project_count = len(await project_cards())
        home_sidebar("settings")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-start justify-between gap-3 flex-nowrap"):
                    with ui.column().classes("gap-1 min-w-0 flex-1"):
                        ui.label("Configurações").classes(
                            "brand-type text-2xl md:text-4xl font-bold"
                        )
                        ui.label("Gerencie os modelos usados pelo estúdio.").classes(
                            "text-xs md:text-base text-[#8f9590]"
                        )
                    with ui.element("div").classes("shrink-0 ml-auto"):
                        theme_toggle()

                with (
                    ui.tabs()
                    .classes("text-[#989e99]")
                    .props("no-caps active-color=primary indicator-color=primary") as settings_tabs
                ):
                    ai_tab = ui.tab("Inteligência artificial", icon="auto_awesome")
                    data_tab = ui.tab("Dados", icon="delete_sweep")
                initial_settings_tab = {"ai": ai_tab, "data": data_tab}[active_settings_tab]
                with ui.tab_panels(settings_tabs, value=initial_settings_tab).classes(
                    "w-full bg-transparent p-0"
                ):
                    with ui.tab_panel(ai_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6 w-full"):
                            with ui.column().classes("w-full gap-1"):
                                ui.label("Provedores de IA").classes("text-xl font-semibold")
                                ui.label(
                                    "Organize as chaves e os modelos usados pelo fluxo de produção."
                                ).classes("text-sm text-[#858b86]")

                            def provider_header(icon: str, title: str, provider: str) -> None:
                                with ui.row().classes(
                                    "w-full items-center justify-between gap-3 flex-nowrap"
                                ):
                                    with ui.row().classes("items-center gap-2 min-w-0 flex-1"):
                                        ui.icon(icon).classes("text-lg acid")
                                        ui.label(title).classes("font-semibold truncate")
                                    ui.label(provider).classes(
                                        "text-xs uppercase tracking-wide text-[#8f9590] shrink-0"
                                    )

                            provider_card_classes = (
                                "border border-[#2d332e] rounded-lg p-4 "
                                "flex flex-col gap-3 min-w-0 w-full"
                            )

                            with ui.element("div").classes(
                                "grid grid-cols-1 lg:grid-cols-2 gap-4 mt-5 w-full"
                            ):
                                with ui.element("div").classes(provider_card_classes):
                                    provider_header("edit_note", "Texto e QA", "Ollama Cloud")
                                    ollama_base_url = (
                                        ui.input(
                                            "URL base Ollama Cloud",
                                            value=current.ollama_cloud_base_url,
                                            placeholder="https://ollama.com/api",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    ollama_api_key = (
                                        ui.input(
                                            "Chave Ollama Cloud",
                                            placeholder=(
                                                "Chave configurada; digite para substituir"
                                                if current.ollama_cloud_api_key
                                                else "OLLAMA_API_KEY"
                                            ),
                                            password=True,
                                            password_toggle_button=True,
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    ollama_default_model = (
                                        ui.select(
                                            list(OLLAMA_CLOUD_TEXT_MODELS),
                                            label="Modelo de texto",
                                            value=current.ollama_cloud_default_model,
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )

                                with ui.element("div").classes(provider_card_classes):
                                    provider_header("image", "Imagem", "Meta Muse Image")
                                    ui.label(
                                        "Conexão por browser autorizado e perfil dedicado."
                                    ).classes("text-xs text-slate-400")
                                    meta_image_model = (
                                        ui.input(
                                            "Modelo de imagem",
                                            value=current.meta_image_model,
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    meta_browser_automation_enabled = ui.switch(
                                        "Habilitar automação de imagens",
                                        value=current.meta_browser_automation_enabled,
                                    ).props("color=primary")
                                    ui.label(
                                        "Ative somente depois de instalar e autorizar o backend "
                                        "de browser no perfil dedicado."
                                    ).classes("text-xs text-amber-300")
                                    ui.input(
                                        "Perfil de browser",
                                        value=str(current.meta_browser_profile_path),
                                    ).props("outlined stack-label disable").classes("w-full")

                                    async def authorize_meta() -> None:
                                        try:
                                            # Um clique em "Autorizar Meta" é uma ação
                                            # explícita do usuário: limpa o estado de
                                            # "navegador fechado manualmente" do perfil.
                                            await resume_after_user_browser_close(
                                                current.meta_browser_profile_path
                                            )
                                        except Exception:
                                            pass  # Bridge offline: o flag, se houver, é limpo pelo console.
                                        try:
                                            started = launch_authorization_console(
                                                current.meta_browser_profile_path
                                            )
                                            ui.notify(
                                                (
                                                    "Janela de autorização aberta. Conclua o login nela."
                                                    if started
                                                    else "A janela de autorização já está aberta."
                                                ),
                                                color="info",
                                            )
                                        except Exception as exc:
                                            ui.notify(f"Falha ao autorizar Meta: {exc}", color="negative")

                                    ui.button(
                                        "Autorizar Meta", icon="login", on_click=authorize_meta
                                    ).props("outline no-caps")

                            ui.separator().classes("my-5")

                            with ui.element("div").classes(
                                "border border-[#2d332e] rounded-lg p-4 flex flex-col gap-2"
                            ):
                                ui.label("Navegador de automação").classes("font-semibold")
                                ui.label(
                                    "Se uma geração falhar e o navegador continuar "
                                    "abrindo sozinho, feche-o aqui. A automação não reabre "
                                    "o navegador até você autorizar novamente."
                                ).classes("text-xs text-slate-400")

                                async def close_browsers() -> None:
                                    try:
                                        await close_browser(current.meta_browser_profile_path)
                                        ui.notify(
                                            "Navegador fechado. A automação não reabrirá "
                                            "o navegador até você autorizar novamente.",
                                            color="positive",
                                        )
                                    except Exception as exc:
                                        ui.notify(
                                            f"Não foi possível fechar o navegador: {exc}",
                                            color="negative",
                                        )

                                ui.button(
                                    "Fechar navegador",
                                    icon="close",
                                    on_click=close_browsers,
                                ).props("outline no-caps").classes("text-red-300 border-red-900")

                            ui.separator().classes("my-5")

                            def save_ai() -> None:
                                typed_ollama_api_key = str(ollama_api_key.value or "").strip()
                                try:
                                    values = {
                                        "TEXT_PROVIDER": "ollama_cloud",
                                        "IMAGE_PROVIDER": "meta",
                                        "OLLAMA_CLOUD_INTEGRATION_MODE": "api",
                                        "OLLAMA_CLOUD_BASE_URL": str(
                                            ollama_base_url.value or ""
                                        ).strip(),
                                        "OLLAMA_CLOUD_DEFAULT_MODEL": str(
                                            ollama_default_model.value or ""
                                        ).strip(),
                                        "META_IMAGE_INTEGRATION_MODE": "browser",
                                        "META_IMAGE_MODEL": str(
                                            meta_image_model.value or ""
                                        ).strip(),
                                        "META_BROWSER_AUTOMATION_ENABLED": (
                                            "true"
                                            if meta_browser_automation_enabled.value
                                            else "false"
                                        ),
                                    }
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
                                if typed_ollama_api_key:
                                    values["OLLAMA_CLOUD_API_KEY"] = typed_ollama_api_key
                                save_preferences(values)
                                ui.notify("Configurações de IA salvas.", color="positive")

                            with ui.row().classes("w-full mt-5 justify-end gap-3"):
                                ui.button(
                                    "Salvar configurações", icon="save", on_click=save_ai
                                ).props("unelevated no-caps").classes(
                                    "acid-bg rounded-xl w-full sm:w-auto"
                                )

                            # ARQ-03: telemetria recente por canal de automação —
                            # responde "últimas gerações: quantas falharam e por
                            # quê" sem abrir o banco manualmente.
                            ui.separator().classes("my-5")
                            with ui.column().classes("w-full gap-2"):
                                ui.label("Saúde das gerações (últimas tentativas)").classes(
                                    "text-lg font-semibold"
                                )
                                channel_health_labels: dict[str, ui.label] = {}
                                try:
                                    async with AsyncSessionLocal() as session:
                                        health_rows = await provider_channel_health(
                                            session, limit=10
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    ui.label(
                                        f"Telemetria indisponível agora: {exc}"
                                    ).classes("text-xs text-[#858b86]")
                                    health_rows = []
                                display_names = {
                                    "meta": "Meta AI (imagens)",
                                }
                                for row in health_rows:
                                    name = display_names.get(row.provider, row.provider)
                                    if row.recent_total == 0:
                                        message = "Sem gerações registradas ainda."
                                        color = "text-[#858b86]"
                                    elif row.recent_failures == 0:
                                        message = (
                                            f"{row.recent_total} tentativa(s) recentes, "
                                            "nenhuma falha."
                                        )
                                        color = "text-[#858b86]"
                                    else:
                                        message = (
                                            f"{row.recent_failures} falha(s) em "
                                            f"{row.recent_total} tentativa(s) recentes."
                                            + (
                                                f" {row.recent_session_failures} delas parecem "
                                                "sessão expirada — use o botão Autorizar acima."
                                                if row.recent_session_failures
                                                else ""
                                            )
                                            + f" Última: {row.latest_message or ''}"
                                        )
                                        color = (
                                            "text-red-300"
                                            if row.recent_failures
                                            else "text-[#858b86]"
                                        )
                                    with ui.row().classes(
                                        "w-full items-start justify-between gap-3"
                                    ):
                                        ui.label(name).classes("text-sm font-semibold")
                                        label = ui.label(message).classes(f"text-xs {color}")
                                        channel_health_labels[row.provider] = label
                    with ui.tab_panel(data_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Gerenciamento de dados").classes("text-xl font-semibold")
                            ui.label(
                                "Ações destrutivas para limpar ideias e projetos do estúdio."
                            ).classes("text-sm text-[#858b86] mb-4")

                            async def confirm_purge_ideas() -> None:
                                ideas_dialog.close()
                                await purge_all_ideas_from_ui()

                            async def confirm_purge_projects() -> None:
                                projects_dialog.close()
                                await purge_all_projects_from_ui()

                            with (
                                ui.dialog() as ideas_dialog,
                                ui.card().classes("entity-card rounded-2xl p-6 min-w-96"),
                            ):
                                ui.label("Apagar todas as ideias?").classes("text-xl font-semibold")
                                ui.label(
                                    "Isso remove as ideias do laboratório e os registros internos "
                                    "de ideias no banco. Projetos serão mantidos, mas roteiros, "
                                    "mídias e outros conteúdos derivados dessas ideias serão removidos."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=ideas_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar ideias",
                                        icon="delete",
                                        on_click=confirm_purge_ideas,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with (
                                ui.dialog() as projects_dialog,
                                ui.card().classes("entity-card rounded-2xl p-6 min-w-96"),
                            ):
                                ui.label("Apagar todos os projetos?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove todos os projetos da lista principal. "
                                    "Ideias salvas na página de ideias não serão apagadas."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=projects_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Apagar projetos",
                                        icon="delete_forever",
                                        on_click=confirm_purge_projects,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-600 text-white rounded-xl"
                                    )

                            with (
                                ui.dialog() as purge_dialog,
                                ui.card().classes("entity-card rounded-2xl p-6 min-w-96"),
                            ):
                                ui.label("Limpar banco da aplicação?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso apaga definitivamente projetos, roteiros, cenas, "
                                    "storyboards, assets, execuções de prompt e ideias. "
                                    "Configurações globais serão mantidas."
                                ).classes("text-sm text-[#858b86]")
                                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                                    ui.button("Cancelar", on_click=purge_dialog.close).props(
                                        "flat no-caps"
                                    )
                                    ui.button(
                                        "Limpar definitivamente",
                                        icon="delete_forever",
                                        on_click=purge_application_data_from_ui,
                                    ).props("unelevated no-caps").classes(
                                        "bg-red-700 text-white rounded-xl"
                                    )

                            with ui.column().classes("w-full gap-3"):
                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Ideias").classes("font-semibold")
                                        ui.label(
                                            f"{lab_idea_count} ideia(s) no laboratório."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todas as ideias",
                                        icon="delete_sweep",
                                        on_click=ideas_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos").classes("font-semibold")
                                        ui.label(
                                            f"{project_count} projeto(s) ativo(s) no estúdio."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar todos os projetos",
                                        icon="delete_forever",
                                        on_click=projects_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col "
                                    "md:flex-row md:items-center md:justify-between gap-3"
                                ):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos e ideias").classes("font-semibold")
                                        ui.label(
                                            f"Remove fisicamente {project_count} projeto(s), "
                                            f"{lab_idea_count} ideia(s) do laboratório e os "
                                            "registros internos relacionados."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar definitivamente",
                                        icon="delete_forever",
                                        on_click=purge_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )
