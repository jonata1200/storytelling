import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.config.settings import get_settings
from app.storyboards.models import StoryboardFrame


def _service_attr(name: str, fallback: object) -> Any:
    service = sys.modules.get("app.storyboards.service")
    return getattr(service, name, fallback) if service is not None else fallback


def _local_storage_file_exists(storage_uri: str) -> bool:
    if not storage_uri:
        return False
    if storage_uri.startswith(("http://", "https://", "data:")):
        return True
    settings_factory = _service_attr("get_settings", get_settings)
    storage_root = settings_factory().local_storage_path.resolve()
    candidate = Path(storage_uri)
    candidates = [candidate] if candidate.is_absolute() else [storage_root / candidate, candidate]
    for path in candidates:
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(storage_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.is_file():
            return True
    return False


def _local_storage_file_path(storage_uri: str) -> Path | None:
    if not storage_uri or storage_uri.startswith(("http://", "https://", "data:")):
        return None
    settings_factory = _service_attr("get_settings", get_settings)
    storage_root = settings_factory().local_storage_path.resolve()
    candidate = Path(storage_uri)
    if candidate.is_absolute():
        candidates = [candidate.resolve(strict=False)]
    else:
        candidates = []
        if candidate.parts and candidate.parts[0] == storage_root.name:
            candidates.append((storage_root.parent / candidate).resolve(strict=False))
        candidates.extend(
            [(storage_root / candidate).resolve(strict=False), candidate.resolve(strict=False)]
        )
    for path in candidates:
        try:
            path.relative_to(storage_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.is_file():
            return path
    return None


def _delete_local_storage_file(storage_uri: str) -> bool:
    path = _local_storage_file_path(storage_uri)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


async def _storyboard_frame_asset_available(
    session: AsyncSession,
    frame: StoryboardFrame | None,
) -> bool:
    if frame is None or frame.asset_id is None:
        return False
    asset = await session.get(Asset, frame.asset_id)
    if asset is None:
        return False
    return _local_storage_file_exists(str(asset.storage_uri or ""))
