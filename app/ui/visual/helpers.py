from pathlib import Path
from urllib.parse import quote

from app.config.settings import get_settings
from app.storage.service import resolve_local_asset_path


def asset_url(storage_uri: str, storage_root: Path | None = None) -> str:
    if not storage_uri:
        return ""
    storage_root = (storage_root or get_settings().local_storage_path).resolve()
    path = resolve_local_asset_path(storage_uri, storage_root)
    if path is None:
        return ""
    try:
        relative = path.relative_to(storage_root)
    except ValueError:
        return ""
    return "/storage/" + "/".join(quote(part) for part in relative.parts)


def clean_profile_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def visual_card_detail(target_kind: str, profile: dict, fallback: str = "") -> str:
    explicit = clean_profile_text(
        profile.get("description")
        or profile.get("summary")
        or profile.get("visual_description")
        or profile.get("mood")
    )
    if explicit:
        return explicit

    if target_kind == "character":
        parts = [
            clean_profile_text(profile.get("gender")),
            clean_profile_text(profile.get("apparent_age")),
            clean_profile_text(profile.get("eyes")),
            clean_profile_text(profile.get("hair")),
            clean_profile_text(profile.get("base_outfit")),
        ]
        text = ", ".join(part for part in parts if part)
        return text or fallback or "Perfil textual pronto para uso nos prompts."

    if target_kind == "location":
        parts = [
            clean_profile_text(profile.get("lighting")),
            clean_profile_text(profile.get("materials")),
            clean_profile_text(profile.get("layout")),
        ]
        text = ", ".join(part for part in parts if part)
        return text or fallback or "Cenario pronto para revisar e gerar referências."

    parts = [
        clean_profile_text(profile.get("narrative_importance")),
        clean_profile_text(profile.get("material")),
        clean_profile_text(profile.get("color")),
        clean_profile_text(profile.get("state")),
    ]
    text = ", ".join(part for part in parts if part)
    return text or fallback or "Objeto pronto para revisar e gerar referências."
