# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from nicegui import ui

from app.config.preferences import save_preferences
from app.config.provider_policy import normalize_provider_name, validate_model_name
from app.config.runtime_preferences import load_runtime_preferences
from app.config.settings import (
    get_settings,
    normalize_omniroute_api_key,
    normalize_openrouter_api_key,
)
from app.storytelling.idea_lab import load_generated_ideas, load_saved_ideas

BodyStyle = Callable[[], None]
ProjectCardsLoader = Callable[[], Awaitable[list[Any]]]
SettingsTabKey = Callable[[str | None], str]
AvatarSaver = Callable[[str, bytes], Any]
AsyncAction = Callable[[], Awaitable[None]]


def register_settings_page(
    *,
    body_style: BodyStyle,
    settings_tab_key: SettingsTabKey,
    project_cards: ProjectCardsLoader,
    home_sidebar: Callable[[str], None],
    theme_toggle: Callable[[], Any],
    user_avatar: Callable[..., Any],
    save_avatar_file: AvatarSaver,
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
        project_count = len(await project_cards())
        home_sidebar("settings")
        with ui.column().classes("w-full min-h-screen pl-0 md:pl-24"):
            with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-8 gap-7"):
                with ui.row().classes("w-full items-start justify-between gap-3 flex-nowrap"):
                    with ui.column().classes("gap-1 min-w-0 flex-1"):
                        ui.label("Configurações").classes(
                            "brand-type text-2xl md:text-4xl font-bold"
                        )
                        ui.label("Gerencie seu perfil e os modelos usados pelo estúdio.").classes(
                            "text-xs md:text-base text-[#8f9590]"
                        )
                    with ui.element("div").classes("shrink-0 ml-auto"):
                        theme_toggle()

                with (
                    ui.tabs()
                    .classes("text-[#989e99]")
                    .props("no-caps active-color=primary indicator-color=primary") as settings_tabs
                ):
                    profile_tab = ui.tab("Perfil", icon="person")
                    ai_tab = ui.tab("Inteligência artificial", icon="auto_awesome")
                    data_tab = ui.tab("Dados", icon="delete_sweep")
                initial_settings_tab = {"profile": profile_tab, "ai": ai_tab, "data": data_tab}[
                    active_settings_tab
                ]
                with ui.tab_panels(settings_tabs, value=initial_settings_tab).classes(
                    "w-full bg-transparent p-0"
                ):
                    with ui.tab_panel(profile_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Dados do usuário").classes("text-xl font-semibold")
                            ui.label("Informações exibidas no seu espaço de trabalho.").classes(
                                "text-sm text-[#858b86] mb-4"
                            )

                            @ui.refreshable
                            def avatar_preview() -> None:
                                with ui.row().classes("items-center gap-4 mb-5"):
                                    photo_avatar = user_avatar(size="80px", navigate=False)
                                    photo_avatar.on(
                                        "click",
                                        lambda: ui.run_javascript(
                                            "document.querySelector('#avatar-upload input[type=file]').click()"
                                        ),
                                    ).tooltip("Clique para alterar a foto")
                                    with ui.column().classes("gap-1"):
                                        ui.label("Foto do perfil").classes("font-semibold")
                                        ui.label("JPG, PNG ou WebP · máximo de 5 MB").classes(
                                            "text-xs text-[#7f8580]"
                                        )
                                        ui.label("Clique na foto para alterar").classes(
                                            "text-xs acid"
                                        )

                            avatar_preview()

                            async def upload_avatar(event: Any) -> None:
                                suffix = Path(event.file.name).suffix.lower()
                                if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                                    ui.notify("Formato de imagem não permitido.", color="negative")
                                    return
                                content = await event.file.read()
                                target = await asyncio.to_thread(
                                    save_avatar_file, event.file.name, content
                                )
                                save_preferences({"USER_AVATAR_PATH": target.as_posix()})
                                avatar_preview.refresh()
                                ui.notify("Foto do perfil atualizada.", color="positive")

                            ui.upload(
                                label="Escolher foto",
                                on_upload=upload_avatar,
                                on_rejected=lambda: ui.notify(
                                    "A imagem deve ter no máximo 5 MB.", color="warning"
                                ),
                                auto_upload=True,
                                max_file_size=5_000_000,
                            ).props("id=avatar-upload accept=.jpg,.jpeg,.png,.webp").classes(
                                "hidden"
                            )

                            display_name = (
                                ui.input("Nome", value=current.user_display_name)
                                .props("outlined")
                                .classes("w-full")
                            )
                            email = (
                                ui.input("E-mail", value=current.user_email)
                                .props("outlined type=email")
                                .classes("w-full mt-3")
                            )

                            def save_profile() -> None:
                                save_preferences(
                                    {
                                        "USER_DISPLAY_NAME": display_name.value or "",
                                        "USER_EMAIL": email.value or "",
                                    }
                                )
                                ui.notify("Perfil salvo.", color="positive")

                            ui.button("Salvar perfil", icon="save", on_click=save_profile).props(
                                "unelevated no-caps"
                            ).classes("acid-bg rounded-xl mt-5")
                    with ui.tab_panel(ai_tab).classes("px-0"):
                        with ui.element("div").classes("entity-card rounded-2xl p-6"):
                            ui.label("Provedores de IA").classes("text-xl font-semibold")
                            ui.label(
                                "Conecte sua conta e escolha modelos diferentes para cada mídia."
                            ).classes("text-sm text-[#858b86] mb-4")
                            saved_preferences = load_runtime_preferences()
                            saved_api_key = saved_preferences.get(
                                "openrouter_api_key", ""
                            ).strip()
                            saved_omniroute_api_key = saved_preferences.get(
                                "omniroute_api_key", ""
                            ).strip()
                            saved_api_key_invalid = bool(
                                saved_api_key
                                and normalize_openrouter_api_key(saved_api_key) is None
                            )
                            saved_omniroute_api_key_invalid = bool(
                                saved_omniroute_api_key
                                and normalize_omniroute_api_key(saved_omniroute_api_key) is None
                            )
                            if current.openrouter_api_key:
                                ui.label("Fallback OpenRouter configurado.").classes(
                                    "text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-200 border border-emerald-800"
                                )
                            elif saved_api_key_invalid:
                                ui.label(
                                    "A chave OpenRouter salva é inválida. Cole uma chave iniciada por sk-or-."
                                ).classes(
                                    "text-xs px-2 py-1 rounded-md bg-red-950 text-red-200 border border-red-800"
                                )
                            else:
                                ui.label(
                                    "Sem chave OpenRouter válida: o rollback manual para OpenRouter ficará indisponível."
                                ).classes(
                                    "text-xs px-2 py-1 rounded-md bg-amber-950 text-amber-200 border border-amber-800"
                                )
                            if current.omniroute_api_key:
                                ui.label("Chave OmniRoute configurada para o fluxo principal.").classes(
                                    "text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-200 border border-emerald-800 mt-2"
                                )
                            elif saved_omniroute_api_key_invalid:
                                ui.label("A chave OmniRoute salva é inválida.").classes(
                                    "text-xs px-2 py-1 rounded-md bg-red-950 text-red-200 border border-red-800 mt-2"
                                )
                            else:
                                ui.label(
                                    "OmniRoute é o provider padrão; configure a chave para executar gerações reais."
                                ).classes(
                                    "text-xs px-2 py-1 rounded-md bg-slate-900 text-slate-300 border border-slate-800 mt-2"
                                )
                            ai_provider = (
                                ui.select(
                                    ["omniroute", "openrouter"],
                                    label="Provider principal",
                                    value=current.ai_provider,
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-4")
                            )
                            api_key = (
                                ui.input(
                                    "Chave OpenRouter",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.openrouter_api_key
                                        else "sk-or-v1-..."
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full")
                            )
                            omniroute_api_key = (
                                ui.input(
                                    "Chave OmniRoute",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.omniroute_api_key
                                        else "omr-... ou chave do gateway configurado"
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            text_model = (
                                ui.input(
                                    "Modelo de texto OpenRouter",
                                    value=current.openrouter_default_model,
                                    placeholder="deepseek/deepseek-v4-flash",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            image_model = (
                                ui.input(
                                    "Modelo de imagem OpenRouter",
                                    value=current.openrouter_image_model,
                                    placeholder="sourceful/riverflow-v2-fast",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            video_model = (
                                ui.input(
                                    "Modelo de vídeo OpenRouter",
                                    value=current.openrouter_video_model,
                                    placeholder="bytedance/seedance-2.0-fast",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            omniroute_text_model = (
                                ui.input(
                                    "Modelo de texto OmniRoute",
                                    value=current.omniroute_default_model,
                                    placeholder="deepseek/deepseek-v4-flash",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            omniroute_image_model = (
                                ui.input(
                                    "Modelo de imagem OmniRoute",
                                    value=current.omniroute_image_model,
                                    placeholder="sourceful/riverflow-v2-fast",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            omniroute_video_model = (
                                ui.input(
                                    "Modelo de vídeo OmniRoute",
                                    value=current.omniroute_video_model,
                                    placeholder="bytedance/seedance-2.0-fast",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )

                            def save_ai() -> None:
                                typed_api_key = str(api_key.value or "").strip()
                                typed_omniroute_api_key = str(
                                    omniroute_api_key.value or ""
                                ).strip()
                                try:
                                    values = {
                                        "AI_PROVIDER": normalize_provider_name(
                                            ai_provider.value,
                                            "Provider principal",
                                        ),
                                        "OPENROUTER_DEFAULT_MODEL": validate_model_name(
                                            text_model.value,
                                            "Modelo de texto",
                                            provider="openrouter",
                                        ),
                                        "OPENROUTER_IMAGE_MODEL": validate_model_name(
                                            image_model.value,
                                            "Modelo de imagem",
                                            provider="openrouter",
                                        ),
                                        "OPENROUTER_VIDEO_MODEL": validate_model_name(
                                            video_model.value,
                                            "Modelo de vídeo",
                                            provider="openrouter",
                                        ),
                                        "OMNIROUTE_DEFAULT_MODEL": validate_model_name(
                                            omniroute_text_model.value,
                                            "Modelo de texto OmniRoute",
                                            provider="omniroute",
                                        ),
                                        "OMNIROUTE_IMAGE_MODEL": validate_model_name(
                                            omniroute_image_model.value,
                                            "Modelo de imagem OmniRoute",
                                            provider="omniroute",
                                        ),
                                        "OMNIROUTE_VIDEO_MODEL": validate_model_name(
                                            omniroute_video_model.value,
                                            "Modelo de vídeo OmniRoute",
                                            provider="omniroute",
                                        ),
                                    }
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
                                if typed_api_key:
                                    normalized_key = normalize_openrouter_api_key(typed_api_key)
                                    if normalized_key is None:
                                        ui.notify(
                                            "Chave OpenRouter inválida. Ela deve começar com sk-or-.",
                                            color="negative",
                                        )
                                        return
                                    values["OPENROUTER_API_KEY"] = normalized_key
                                elif saved_api_key_invalid:
                                    values["OPENROUTER_API_KEY"] = ""
                                if typed_omniroute_api_key:
                                    normalized_omniroute_key = normalize_omniroute_api_key(
                                        typed_omniroute_api_key
                                    )
                                    if normalized_omniroute_key is None:
                                        ui.notify("Chave OmniRoute inválida.", color="negative")
                                        return
                                    values["OMNIROUTE_API_KEY"] = normalized_omniroute_key
                                elif saved_omniroute_api_key_invalid:
                                    values["OMNIROUTE_API_KEY"] = ""
                                save_preferences(values)
                                ui.notify("Configurações de IA salvas.", color="positive")

                            with ui.row().classes("mt-5 gap-3"):
                                ui.button(
                                    "Salvar configurações", icon="save", on_click=save_ai
                                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
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

                            with ui.dialog() as ideas_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Apagar todas as ideias?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso remove ideias salvas, ideias geradas e registros "
                                    "de ideias no banco. Projetos serão mantidos, mas "
                                    "conteúdos derivados das ideias serão removidos."
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

                            with ui.dialog() as projects_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
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

                            with ui.dialog() as purge_dialog, ui.card().classes(
                                "entity-card rounded-2xl p-6 min-w-96"
                            ):
                                ui.label("Limpar banco da aplicação?").classes(
                                    "text-xl font-semibold"
                                )
                                ui.label(
                                    "Isso apaga definitivamente projetos, roteiros, cenas, "
                                    "storyboards, assets, execuções de prompt e ideias do "
                                    "laboratório. Usuários e configurações globais serão mantidos."
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
                                            f"{saved_idea_count} salva(s) e "
                                            f"{generated_idea_count} gerada(s)."
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

                                with ui.element("div").classes("hidden"):
                                    with ui.column().classes("gap-1"):
                                        ui.label("Projetos e ideias").classes("font-semibold")
                                        ui.label(
                                            f"Remove fisicamente {project_count} projeto(s), "
                                            f"{saved_idea_count} ideia(s) salva(s) e "
                                            f"{generated_idea_count} ideia(s) gerada(s)."
                                        ).classes("text-sm text-[#858b86]")
                                    ui.button(
                                        "Apagar definitivamente",
                                        icon="delete_forever",
                                        on_click=purge_dialog.open,
                                    ).props("outline no-caps").classes(
                                        "text-red-300 border-red-900 rounded-xl"
                                    )

