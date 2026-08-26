import base64
import hashlib
import logging
import mimetypes
import shutil
import subprocess
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
            # SSRF defense: never fetch HTTP/HTTPS URLs from provider references.
            # Only file:// and bare paths are allowed; fail-closed for network schemes.
            return []
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
        # Raw absolute paths are still fail-closed by the caller: only resolved
        # files under storage_root pass the relative_to(storage_root) check.
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


def local_uri_to_data_url(uri: str) -> str | None:
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
        return None
    media_type = _media_type_for_path(resolved)
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _local_storage_file_for_uri(uri: str) -> Path | None:
    storage_root = _resolved_storage_root()
    for candidate in _candidate_paths(uri, storage_root):
        try:
            candidate_resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            candidate_resolved.relative_to(storage_root)
        except ValueError:
            continue
        if candidate_resolved.is_file():
            return candidate_resolved
    return None


def optimized_local_image_reference_uri(
    uri: str,
    *,
    max_width: int = 768,
    max_bytes: int = 220_000,
) -> str | None:
    """Cria uma referencia JPEG leve para payloads de imagem, sem alterar o asset original."""
    source = _local_storage_file_for_uri(uri)
    if source is None:
        return None
    media_type = _media_type_for_path(source)
    if not media_type.startswith("image/") or media_type == "image/svg+xml":
        return None
    try:
        source_stat = source.stat()
    except OSError:
        return None
    if source_stat.st_size <= max_bytes:
        return uri
    ffmpeg_path = resolve_ffmpeg_path(getattr(get_settings(), "ffmpeg_path", ""))
    if not ffmpeg_path:
        return None
    storage_root = _resolved_storage_root()
    cache_dir = storage_root / ".cache" / "flow_references"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(
        f"{source}:{source_stat.st_mtime_ns}:{max_width}:{max_bytes}".encode()
    ).hexdigest()[:24]
    optimized = cache_dir / f"{fingerprint}.jpg"
    if optimized.is_file():
        return optimized.as_posix()
    command = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vf",
        f"scale='min({max_width},iw)':-2",
        "-frames:v",
        "1",
        "-q:v",
        "6",
        str(optimized),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Nao foi possivel otimizar referencia visual %s: %s", uri, exc)
        return None
    if not optimized.is_file():
        return None
    return optimized.as_posix()


def image_signature_matches(content: bytes, extension: str) -> bool:
    normalized = str(extension or "").strip().lower()
    if normalized == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if normalized == ".webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if normalized == ".gif":
        return content.startswith(b"GIF87a") or content.startswith(b"GIF89a")
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
    if not data_url or not data_url.startswith("data:") or ";base64," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0]
    if not media_type or not encoded:
        return None
    return media_type, encoded


def extract_last_frame_from_video(video_path: Path) -> Path:
    """Extrai o último frame de um vídeo usando ffmpeg.

    Args:
        video_path: Caminho para o arquivo de vídeo

    Returns:
        Caminho para a imagem do último frame (JPEG)

    Raises:
        RuntimeError: Se o ffmpeg falhar ou o vídeo não existir
    """
    if not video_path.exists():
        raise RuntimeError(f"Arquivo de vídeo não encontrado: {video_path}")

    # Obter caminho do ffmpeg
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg não encontrado. Instale o ffmpeg para usar esta funcionalidade.")

    # Criar arquivo temporário para o frame
    output_dir = video_path.parent
    output_path = output_dir / f"{video_path.stem}_last_frame.jpg"

    # Comando ffmpeg para extrair o último frame (-sseof -0.1 para suportar vídeos curtos)
    cmd = [
        ffmpeg_path,
        "-sseof",
        "-0.1",  # Ir para 0.1 segundo antes do fim
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-y",  # Sobrescrever se existir
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0 or not output_path.exists():
            # Fallback: extrair o último frame sem -sseof
            fallback_cmd = [
                ffmpeg_path,
                "-i",
                str(video_path),
                "-update",
                "1",
                "-q:v",
                "2",
                "-y",
                str(output_path),
            ]
            fallback_res = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=30)
            if fallback_res.returncode != 0 or not output_path.exists():
                err_msg = (result.stderr or fallback_res.stderr)[:500]
                logger.error(f"ffmpeg falhou: {err_msg}")
                raise RuntimeError(f"ffmpeg falhou ao extrair último frame: {err_msg}")

        logger.info(f"Último frame extraído: {output_path}")
        return output_path

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg excedeu tempo limite ao extrair frame") from exc


def get_video_duration(video_path: Path) -> float:
    """Obtém a duração de um vídeo em segundos usando ffprobe.

    Args:
        video_path: Caminho para o arquivo de vídeo

    Returns:
        Duração em segundos
    """
    if not video_path.exists():
        raise RuntimeError(f"Arquivo de vídeo não encontrado: {video_path}")

    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg não encontrado")

    # Usar ffprobe (normalmente está no mesmo diretório que o ffmpeg)
    ffmpeg_p = Path(ffmpeg_path)
    candidates = [
        ffmpeg_p.parent / "ffprobe.exe",
        ffmpeg_p.parent / "ffprobe",
        Path(shutil.which("ffprobe") or ""),
        Path(shutil.which("ffprobe.exe") or ""),
    ]
    ffprobe_path: Path | None = None
    for cand in candidates:
        if cand.is_file():
            ffprobe_path = cand
            break

    if ffprobe_path is None:
        raise RuntimeError("ffprobe não encontrado")

    cmd = [
        str(ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe falhou: {result.stderr[:500]}")

        duration_str = result.stdout.strip()
        if not duration_str:
            raise RuntimeError("ffprobe não retornou duração")

        return float(duration_str)

    except (ValueError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Erro ao obter duração do vídeo: {exc}") from exc
