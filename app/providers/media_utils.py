import base64
import logging
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def resolve_ffmpeg_path(configured_path: object = None) -> str | None:
    configured = str(configured_path or "").strip().strip('"')
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
        discovered = shutil.which(configured)
        if discovered:
            return discovered
    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:
        pass
    else:
        try:
            imageio_ffmpeg_path = Path(get_ffmpeg_exe())
        except Exception:
            logger.debug("imageio_ffmpeg did not resolve an ffmpeg executable", exc_info=True)
        else:
            if imageio_ffmpeg_path.is_file():
                return str(imageio_ffmpeg_path)
    for candidate in (
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


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
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg",
        ".webm": "video/webm",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
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


def image_signature_matches(content: bytes, extension: str) -> bool:
    normalized = str(extension or "").strip().lower()
    if normalized == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if normalized == ".webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def pdf_signature_matches(content: bytes) -> bool:
    return content.startswith(b"%PDF-")


def docx_signature_matches(content: bytes) -> bool:
    return content.startswith(b"PK\x03\x04")


def extension_from_media_type(media_type: str) -> str:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    explicit_extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/mpeg": ".mpeg",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "audio/aac": ".aac",
        "audio/flac": ".flac",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
    }
    if normalized in explicit_extensions:
        return explicit_extensions[normalized]
    if normalized == "image/svg+xml":
        return ".svg"
    extension = mimetypes.guess_extension(normalized)
    return extension or ".bin"


def data_url_parts(uri: str) -> tuple[str, str] | None:
    data_url = local_uri_to_data_url(uri)
    if not data_url.startswith("data:") or ";base64," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0]
    if not media_type or not encoded:
        return None
    return media_type, encoded
