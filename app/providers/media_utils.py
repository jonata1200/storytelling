import base64
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config.settings import get_settings


def _resolved_storage_root() -> Path:
    return get_settings().local_storage_path.resolve()


def _is_windows_drive_path(uri: str) -> bool:
    return len(uri) >= 2 and uri[0].isalpha() and uri[1] == ":"


def _without_root_marker(parts: tuple[str, ...]) -> tuple[str, ...]:
    if parts and parts[0] in {"/", "\\"}:
        return parts[1:]
    return parts


def _candidate_paths(uri: str, storage_root: Path) -> list[Path]:
    raw_path = uri
    if not _is_windows_drive_path(uri):
        parsed = urlparse(uri)
        if parsed.scheme in {"http", "https"}:
            if parsed.scheme == "https":
                return []
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return []
            raw_path = unquote(parsed.path)
        elif parsed.scheme == "file":
            raw_path = unquote(parsed.path)
            if _is_windows_drive_path(raw_path.removeprefix("/")):
                raw_path = raw_path.removeprefix("/")
        elif parsed.scheme:
            return []

    path = Path(raw_path)
    candidates: list[Path] = []
    relative_parts = _without_root_marker(path.parts)
    if path.is_absolute():
        parts = path.parts
        if len(parts) >= 2 and parts[1] == storage_root.name:
            candidates.append(storage_root.joinpath(*parts[2:]))
        candidates.append(path)
    else:
        if relative_parts and relative_parts[0] == storage_root.name:
            relative_path = Path(*relative_parts)
            candidates.append(storage_root.parent / relative_path)
            candidates.append(storage_root.joinpath(*relative_parts[1:]))
        candidates.append(path)
    return candidates


def _media_type_for_path(path: Path) -> str:
    explicit_media_types = {
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    return (
        explicit_media_types.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def local_uri_to_data_url(uri: str) -> str:
    if uri.startswith("data:"):
        return uri
    storage_root = _resolved_storage_root()
    resolved: Path | None = None
    for candidate in _candidate_paths(uri, storage_root):
        try:
            candidate_resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            candidate_resolved.relative_to(storage_root)
        except ValueError:
            continue
        resolved = candidate_resolved
        break
    if resolved is None:
        return uri
    media_type = _media_type_for_path(resolved)
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def extension_from_media_type(media_type: str) -> str:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    explicit_extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if normalized in explicit_extensions:
        return explicit_extensions[normalized]
    if normalized == "image/svg+xml":
        return ".svg"
    extension = mimetypes.guess_extension(normalized)
    return extension or ".bin"
