# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from nicegui import ui

from app.config.preferences import save_preferences
from app.config.provider_policy import (
    SUPPORTED_TEXT_PROVIDERS,
    effective_provider_for_channel,
    is_ollama_cloud_base_url,
    provider_display_name,
    validate_model_name,
)
from app.config.settings import (
    GROQ_TEXT_MODELS,
    NVIDIA_NIM_TEXT_MODELS,
    OLLAMA_TEXT_MODELS,
    get_settings,
)
from app.providers.veo_free.session import (
    clear_session as clear_veo_free_session,
)
from app.providers.veo_free.session import (
    save_cookie_bundle as save_veo_free_cookie_bundle,
)
from app.providers.veo_free.session import (
    validate_session as validate_veo_free_session,
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
                            current_text_provider = effective_provider_for_channel(
                                current, "text"
                            )
                            if current_text_provider not in SUPPORTED_TEXT_PROVIDERS:
                                current_text_provider = "ollama"
                            provider_options = {
                                provider: provider_display_name(provider)
                                for provider in SUPPORTED_TEXT_PROVIDERS
                            }

                            def model_options(
                                options: tuple[str, ...],
                                current_model: str,
                            ) -> list[str]:
                                selectable = list(options)
                                if current_model and current_model not in selectable:
                                    selectable.append(current_model)
                                return selectable

                            text_provider = (
                                ui.select(
                                    provider_options,
                                    label="Provider de texto",
                                    value=current_text_provider,
                                )
                                .props("outlined stack-label options-dense")
                                .classes("w-full mt-3")
                            )
                            text_provider_fallbacks = (
                                ui.input(
                                    "Fallbacks de texto",
                                    value=current.text_provider_fallbacks,
                                    placeholder="nvidia_nim,ollama",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            ollama_base_url = (
                                ui.input(
                                    "URL base Ollama",
                                    value=current.ollama_base_url,
                                    placeholder="https://ollama.com ou http://localhost:11434/v1",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            ollama_api_key = (
                                ui.input(
                                    "Chave Ollama",
                                    value=current.ollama_api_key or "",
                                    placeholder="Obrigatoria no Cloud; use ollama no modo local",
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            ollama_text_model = (
                                ui.select(
                                    model_options(OLLAMA_TEXT_MODELS, current.ollama_default_model),
                                    label="Modelo de texto Ollama",
                                    value=current.ollama_default_model,
                                )
                                .props("outlined stack-label options-dense")
                                .classes("w-full mt-3")
                            )
                            groq_api_key = (
                                ui.input(
                                    "Chave Groq",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.groq_api_key
                                        else "gsk_..."
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            groq_base_url = (
                                ui.input(
                                    "URL base Groq",
                                    value=current.groq_base_url,
                                    placeholder="https://api.groq.com/openai/v1",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            groq_text_model = (
                                ui.select(
                                    model_options(GROQ_TEXT_MODELS, current.groq_default_model),
                                    label="Modelo de texto Groq",
                                    value=current.groq_default_model,
                                )
                                .props("outlined stack-label options-dense")
                                .classes("w-full mt-3")
                            )
                            nvidia_nim_api_key = (
                                ui.input(
                                    "Chave NVIDIA NIM",
                                    placeholder=(
                                        "Chave configurada — digite apenas para substituir"
                                        if current.nvidia_nim_api_key
                                        else "nvapi-..."
                                    ),
                                    password=True,
                                    password_toggle_button=True,
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            nvidia_nim_base_url = (
                                ui.input(
                                    "URL base NVIDIA NIM",
                                    value=current.nvidia_nim_base_url,
                                    placeholder="https://integrate.api.nvidia.com/v1",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            nvidia_nim_text_model = (
                                ui.select(
                                    model_options(
                                        NVIDIA_NIM_TEXT_MODELS,
                                        current.nvidia_nim_default_model,
                                    ),
                                    label="Modelo de texto NVIDIA NIM",
                                    value=current.nvidia_nim_default_model,
                                )
                                .props("outlined stack-label options-dense")
                                .classes("w-full mt-3")
                            )
                            veo_image_model = (
                                ui.input(
                                    "Modelo de imagem Veo AI Free",
                                    value=current.veo_ai_free_image_model,
                                    placeholder="veo-ai-free/image",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            veo_video_model = (
                                ui.input(
                                    "Modelo de vídeo Veo AI Free",
                                    value=current.veo_ai_free_video_model,
                                    placeholder="veo-ai-free/video",
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )
                            veo_validation = validate_veo_free_session(
                                current.veo_ai_free_session_path
                            )
                            veo_enabled = ui.checkbox(
                                "Veo AI Free experimental",
                                value=current.veo_ai_free_enabled,
                            ).classes("mt-4")
                            ui.label(veo_validation.message).classes(
                                "text-xs px-2 py-1 rounded-md bg-slate-900 text-slate-300 border border-slate-800"
                            )
                            veo_cookie_bundle = (
                                ui.textarea(
                                    "Bundle JSON de cookies Veo AI Free",
                                    placeholder='{"cookies":[{"name":"...","value":"...","domain":"..."}]}',
                                )
                                .props("outlined stack-label")
                                .classes("w-full mt-3")
                            )

                            def save_veo_session() -> None:
                                payload = str(veo_cookie_bundle.value or "").strip()
                                if not payload:
                                    ui.notify("Cole um bundle JSON de cookies.", color="warning")
                                    return
                                try:
                                    validation = save_veo_free_cookie_bundle(
                                        payload,
                                        current.veo_ai_free_session_path,
                                    )
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
                                ui.notify(validation.message, color="positive")
                                veo_cookie_bundle.value = ""

                            def clear_veo_session() -> None:
                                clear_veo_free_session(current.veo_ai_free_session_path)
                                ui.notify("Sessão Veo AI Free removida.", color="positive")

                            def save_ai() -> None:
                                typed_groq_api_key = str(groq_api_key.value or "").strip()
                                typed_nvidia_nim_api_key = str(
                                    nvidia_nim_api_key.value or ""
                                ).strip()
                                try:
                                    selected_text_provider = str(
                                        text_provider.value or ""
                                    ).strip().casefold()
                                    if selected_text_provider not in SUPPORTED_TEXT_PROVIDERS:
                                        raise ValueError("Provider de texto invalido.")
                                    selected_ollama_base_url = str(
                                        ollama_base_url.value or ""
                                    ).strip()
                                    selected_ollama_api_key = str(
                                        ollama_api_key.value or ""
                                    ).strip()
                                    if (
                                        selected_text_provider == "ollama"
                                        and is_ollama_cloud_base_url(selected_ollama_base_url)
                                        and not selected_ollama_api_key
                                    ):
                                        raise ValueError(
                                            "Informe a Chave Ollama para usar Ollama Cloud."
                                        )
                                    values = {
                                        "AI_PROVIDER": "ollama",
                                        "TEXT_PROVIDER": selected_text_provider,
                                        "IMAGE_PROVIDER": "veo_ai_free",
                                        "VIDEO_PROVIDER": "veo_ai_free",
                                        "TEXT_PROVIDER_FALLBACKS": str(
                                            text_provider_fallbacks.value or ""
                                        ).strip(),
                                        "OLLAMA_BASE_URL": selected_ollama_base_url,
                                        "OLLAMA_API_KEY": selected_ollama_api_key
                                        or "ollama",
                                        "OLLAMA_DEFAULT_MODEL": validate_model_name(
                                            ollama_text_model.value,
                                            "Modelo de texto Ollama",
                                            provider="ollama",
                                        ),
                                        "GROQ_BASE_URL": str(groq_base_url.value or "").strip(),
                                        "GROQ_DEFAULT_MODEL": validate_model_name(
                                            groq_text_model.value,
                                            "Modelo de texto Groq",
                                            provider="groq",
                                        ),
                                        "NVIDIA_NIM_BASE_URL": str(
                                            nvidia_nim_base_url.value or ""
                                        ).strip(),
                                        "NVIDIA_NIM_DEFAULT_MODEL": validate_model_name(
                                            nvidia_nim_text_model.value,
                                            "Modelo de texto NVIDIA NIM",
                                            provider="nvidia_nim",
                                        ),
                                        "VEO_AI_FREE_IMAGE_MODEL": validate_model_name(
                                            veo_image_model.value,
                                            "Modelo de imagem Veo AI Free",
                                            provider="veo_ai_free",
                                        ),
                                        "VEO_AI_FREE_VIDEO_MODEL": validate_model_name(
                                            veo_video_model.value,
                                            "Modelo de vídeo Veo AI Free",
                                            provider="veo_ai_free",
                                        ),
                                        "VEO_AI_FREE_ENABLED": (
                                            "true" if veo_enabled.value else "false"
                                        ),
                                    }
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
                                if typed_groq_api_key:
                                    values["GROQ_API_KEY"] = typed_groq_api_key
                                if typed_nvidia_nim_api_key:
                                    values["NVIDIA_NIM_API_KEY"] = typed_nvidia_nim_api_key
                                save_preferences(values)
                                ui.notify("Configurações de IA salvas.", color="positive")

                            with ui.row().classes("mt-5 gap-3"):
                                ui.button(
                                    "Salvar configurações", icon="save", on_click=save_ai
                                ).props("unelevated no-caps").classes("acid-bg rounded-xl")
                                ui.button(
                                    "Salvar sessão Veo",
                                    icon="vpn_key",
                                    on_click=save_veo_session,
                                ).props("outline no-caps").classes("rounded-xl")
                                ui.button(
                                    "Apagar sessão Veo",
                                    icon="delete",
                                    on_click=clear_veo_session,
                                ).props("outline no-caps").classes(
                                    "text-red-300 border-red-900 rounded-xl"
                                )
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

