import base64
import mimetypes
from pathlib import Path

from app.config.settings import get_settings


def _resolved_storage_root() -> Path:
    return get_settings().local_storage_path.resolve()


def local_uri_to_data_url(uri: str) -> str:
    path = Path(uri)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return uri
    try:
        resolved.relative_to(_resolved_storage_root())
    except ValueError:
        return uri
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def extension_from_media_type(media_type: str) -> str:
    if media_type == "image/svg+xml":
        return ".svg"
    extension = mimetypes.guess_extension(media_type)
    return extension or ".bin"
