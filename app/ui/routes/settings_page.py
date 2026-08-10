# ruff: noqa: E501

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from nicegui import ui

from app.config.preferences import save_preferences
from app.config.provider_policy import (
    validate_model_name,
)
from app.config.settings import (
    ELEVENLABS_SPEECH_MODELS,
    OLLAMA_CLOUD_TEXT_MODELS,
    get_settings,
    normalize_google_ai_image_model,
    normalize_google_ai_video_model,
    normalize_ollama_cloud_text_model,
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
                                try:
                                    target = await asyncio.to_thread(
                                        save_avatar_file, event.file.name, content
                                    )
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
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
                                "Organize as chaves e os modelos usados pelo fluxo de produção."
                            ).classes("text-sm text-[#858b86] mb-4")

                            def model_options(
                                options: tuple[str, ...],
                                current_model: str,
                            ) -> list[str]:
                                _ = current_model
                                return list(options)

                            def selected_ollama_cloud_model(current_model: str) -> str:
                                return normalize_ollama_cloud_text_model(current_model)

                            def selected_google_ai_image_model(current_model: str) -> str:
                                return normalize_google_ai_image_model(current_model)

                            def selected_google_ai_video_model(current_model: str) -> str:
                                return normalize_google_ai_video_model(current_model)

                            def provider_header(icon: str, title: str, provider: str) -> None:
                                with ui.row().classes("w-full items-center justify-between gap-3"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon(icon).classes("text-lg acid")
                                        ui.label(title).classes("font-semibold")
                                    ui.label(provider).classes(
                                        "text-xs uppercase tracking-wide text-[#8f9590]"
                                    )

                            google_ai_image_model_value = selected_google_ai_image_model(
                                current.google_ai_image_model
                            )
                            google_ai_video_model_value = selected_google_ai_video_model(
                                current.google_ai_video_model
                            )

                            with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-2 gap-4 mt-5"):
                                with ui.element("div").classes(
                                    "border border-[#2d332e] rounded-lg p-4 flex flex-col gap-3"
                                ):
                                    provider_header("edit_note", "Texto", "Ollama Cloud")
                                    ollama_cloud_base_url = (
                                        ui.input(
                                            "URL base Ollama Cloud",
                                            value=current.ollama_cloud_base_url,
                                            placeholder="https://ollama.com/api",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    ollama_cloud_api_key = (
                                        ui.input(
                                            "Chave Ollama Cloud",
                                            placeholder=(
                                                "Chave configurada; digite para substituir"
                                                if current.ollama_cloud_api_key
                                                else "ollama-..."
                                            ),
                                            password=True,
                                            password_toggle_button=True,
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    ollama_cloud_text_model = (
                                        ui.select(
                                            model_options(
                                                OLLAMA_CLOUD_TEXT_MODELS,
                                                current.ollama_cloud_default_model,
                                            ),
                                            label="Modelo de texto",
                                            value=selected_ollama_cloud_model(
                                                current.ollama_cloud_default_model
                                            ),
                                        )
                                        .props("outlined stack-label options-dense")
                                        .classes("w-full")
                                    )

                                with ui.element("div").classes(
                                    "border border-[#2d332e] rounded-lg p-4 flex flex-col gap-3"
                                ):
                                    provider_header("movie", "Imagem e vídeo", "Google AI")
                                    with ui.grid().classes(
                                        "w-full grid-cols-1 md:grid-cols-2 gap-3"
                                    ):
                                        google_ai_base_url = (
                                            ui.input(
                                                "URL base Google AI",
                                                value=current.google_ai_base_url,
                                                placeholder="https://generativelanguage.googleapis.com/v1beta",
                                            )
                                            .props("outlined stack-label")
                                            .classes("w-full")
                                        )
                                        google_ai_api_key = (
                                            ui.input(
                                                "Chave Google AI",
                                                placeholder=(
                                                    "Chave configurada; digite para substituir"
                                                    if current.google_ai_api_key
                                                    else "AIza..."
                                                ),
                                                password=True,
                                                password_toggle_button=True,
                                            )
                                            .props("outlined stack-label")
                                            .classes("w-full")
                                        )
                                    with ui.grid().classes(
                                        "w-full grid-cols-1 md:grid-cols-2 gap-3"
                                    ):
                                        (
                                            ui.input(
                                                "Modelo de imagem",
                                                value=google_ai_image_model_value,
                                            )
                                            .props("outlined stack-label readonly")
                                            .classes("w-full")
                                        )
                                        (
                                            ui.input(
                                                "Modelo de vídeo",
                                                value=google_ai_video_model_value,
                                            )
                                            .props("outlined stack-label readonly")
                                            .classes("w-full")
                                        )
                                    with ui.grid().classes(
                                        "w-full grid-cols-1 md:grid-cols-3 gap-3"
                                    ):
                                        (
                                            ui.input("Imagem 9:16", value="720 x 1280 px")
                                            .props("outlined stack-label readonly")
                                            .classes("w-full")
                                        )
                                        (
                                            ui.input("Imagem 16:9", value="1280 x 720 px")
                                            .props("outlined stack-label readonly")
                                            .classes("w-full")
                                        )
                                        (
                                            ui.input("Resolução de vídeo", value="720p")
                                            .props("outlined stack-label readonly")
                                            .classes("w-full")
                                        )

                            ui.separator().classes("my-5")
                            with ui.element("div").classes(
                                "border border-[#2d332e] rounded-lg p-4 flex flex-col gap-3"
                            ):
                                provider_header("graphic_eq", "Voz e dublagem", "ElevenLabs")
                                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 gap-3"):
                                    elevenlabs_base_url = (
                                        ui.input(
                                            "URL base ElevenLabs",
                                            value=current.elevenlabs_base_url,
                                            placeholder="https://api.elevenlabs.io/v1",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    elevenlabs_api_key = (
                                        ui.input(
                                            "Chave ElevenLabs",
                                            placeholder=(
                                                "Chave configurada; digite para substituir"
                                                if current.elevenlabs_api_key
                                                else "sk_..."
                                            ),
                                            password=True,
                                            password_toggle_button=True,
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-3 gap-3"):
                                    elevenlabs_voice_id = (
                                        ui.input(
                                            "Voice ID padrão",
                                            value=current.elevenlabs_voice_id,
                                            placeholder="JBFqnCBsd6RMkjVDRZzb",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    elevenlabs_speech_model = (
                                        ui.select(
                                            model_options(
                                                ELEVENLABS_SPEECH_MODELS,
                                                current.elevenlabs_speech_model,
                                            ),
                                            label="Modelo de voz",
                                            value=current.elevenlabs_speech_model,
                                        )
                                        .props("outlined stack-label options-dense")
                                        .classes("w-full")
                                    )
                                    elevenlabs_output_format = (
                                        ui.select(
                                            [
                                                "mp3_44100_128",
                                                "mp3_44100_192",
                                                "mp3_22050_32",
                                            ],
                                            label="Formato de áudio",
                                            value=current.elevenlabs_output_format,
                                        )
                                        .props("outlined stack-label options-dense")
                                        .classes("w-full")
                                    )
                                with ui.grid().classes("w-full grid-cols-1 md:grid-cols-2 gap-3"):
                                    dubbing_source_lang = (
                                        ui.input(
                                            "Idioma original",
                                            value=current.dubbing_source_lang,
                                            placeholder="pt",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )
                                    dubbing_target_lang = (
                                        ui.input(
                                            "Idioma da dublagem",
                                            value=current.dubbing_target_lang,
                                            placeholder="en",
                                        )
                                        .props("outlined stack-label")
                                        .classes("w-full")
                                    )

                            def save_ai() -> None:
                                typed_ollama_cloud_api_key = str(
                                    ollama_cloud_api_key.value or ""
                                ).strip()
                                try:
                                    values = {
                                        "AI_PROVIDER": "ollama_cloud",
                                        "TEXT_PROVIDER": "ollama_cloud",
                                        "IMAGE_PROVIDER": "google_ai",
                                        "VIDEO_PROVIDER": "google_ai",
                                        "SPEECH_PROVIDER": "elevenlabs",
                                        "DUBBING_PROVIDER": "elevenlabs",
                                        "TEXT_PROVIDER_FALLBACKS": "",
                                        "OLLAMA_CLOUD_BASE_URL": str(
                                            ollama_cloud_base_url.value or ""
                                        ).strip(),
                                        "OLLAMA_CLOUD_DEFAULT_MODEL": validate_model_name(
                                            ollama_cloud_text_model.value,
                                            "Modelo de texto Ollama Cloud",
                                            provider="ollama_cloud",
                                        ),
                                        "GOOGLE_AI_BASE_URL": str(
                                            google_ai_base_url.value or ""
                                        ).strip(),
                                        "GOOGLE_AI_IMAGE_MODEL": validate_model_name(
                                            google_ai_image_model_value,
                                            "Modelo de imagem Google AI",
                                            provider="google_ai",
                                        ),
                                        "GOOGLE_AI_IMAGE_SIZE": "1K",
                                        "GOOGLE_AI_VIDEO_MODEL": validate_model_name(
                                            google_ai_video_model_value,
                                            "Modelo de vídeo Google AI",
                                            provider="google_ai",
                                        ),
                                        "GOOGLE_AI_VIDEO_FAST_MODEL": validate_model_name(
                                            google_ai_video_model_value,
                                            "Modelo rápido de vídeo Google AI",
                                            provider="google_ai",
                                        ),
                                        "ELEVENLABS_BASE_URL": str(
                                            elevenlabs_base_url.value or ""
                                        ).strip(),
                                        "ELEVENLABS_VOICE_ID": str(
                                            elevenlabs_voice_id.value or ""
                                        ).strip(),
                                        "ELEVENLABS_SPEECH_MODEL": validate_model_name(
                                            elevenlabs_speech_model.value,
                                            "Modelo de voz ElevenLabs",
                                            provider="elevenlabs",
                                        ),
                                        "ELEVENLABS_OUTPUT_FORMAT": str(
                                            elevenlabs_output_format.value or "mp3_44100_128"
                                        ).strip(),
                                        "DUBBING_SOURCE_LANG": str(
                                            dubbing_source_lang.value or "pt"
                                        ).strip(),
                                        "DUBBING_TARGET_LANG": str(
                                            dubbing_target_lang.value or "en"
                                        ).strip(),
                                    }
                                except ValueError as exc:
                                    ui.notify(str(exc), color="negative")
                                    return
                                if typed_ollama_cloud_api_key:
                                    values["OLLAMA_CLOUD_API_KEY"] = typed_ollama_cloud_api_key
                                typed_google_ai_api_key = str(
                                    google_ai_api_key.value or ""
                                ).strip()
                                if typed_google_ai_api_key:
                                    values["GOOGLE_AI_API_KEY"] = typed_google_ai_api_key
                                typed_elevenlabs_api_key = str(
                                    elevenlabs_api_key.value or ""
                                ).strip()
                                if typed_elevenlabs_api_key:
                                    values["ELEVENLABS_API_KEY"] = typed_elevenlabs_api_key
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

                                with ui.element("div").classes(
                                    "border border-red-950 rounded-2xl p-4 flex flex-col "
                                    "md:flex-row md:items-center md:justify-between gap-3"
                                ):
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

