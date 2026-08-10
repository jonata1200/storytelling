import hashlib
import mimetypes
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.config.settings import get_settings
from app.providers.image.types import ImageResult
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


def _storyboard_orphan_image_result(
    output_dir: Path,
    shot_id: UUID,
    frame_number: int,
    *,
    provider_name: str,
    image_model: str,
    prompt: str,
) -> ImageResult | None:
    prefix = f"{shot_id}_storyboard_{frame_number:03d}_"
    candidates = [path for path in output_dir.glob(f"{prefix}*") if path.is_file()]
    if not candidates:
        return None
    file_path = max(candidates, key=lambda path: path.stat().st_mtime)
    image_bytes = file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return ImageResult(
        file_path=file_path,
        storage_uri=file_path.as_posix(),
        sha256=hashlib.sha256(image_bytes).hexdigest(),
        content_type=content_type,
        provider=provider_name,
        model=image_model,
        prompt=prompt,
        estimated_cost="0.000000",
    )
