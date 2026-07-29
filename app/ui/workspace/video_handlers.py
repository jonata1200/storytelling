from uuid import UUID

from nicegui import ui

from app.database.session import AsyncSessionLocal
from app.production.service import get_or_create_production_settings
from app.ui.shared.page_config import friendly_ai_error, show_ai_error_popup
from app.video_generation.planning import _store_video_prompt_override


async def save_video_prompt_from_ui(
    project_id: UUID,
    frame_id: UUID,
    prompt: str,
    *,
    reload_page: bool = True,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            production_settings = await get_or_create_production_settings(session, project_id)
            production_settings.metadata_json = _store_video_prompt_override(
                production_settings.metadata_json or {},
                frame_id,
                prompt,
            )
            await session.commit()
        if reload_page:
            ui.notify("Prompt de video atualizado.", color="positive")
            ui.navigate.reload()
    except Exception as exc:
        show_ai_error_popup(friendly_ai_error(exc), details=str(exc))
