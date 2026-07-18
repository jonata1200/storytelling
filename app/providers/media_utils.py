import base64
import mimetypes
from pathlib import Path


def local_uri_to_data_url(uri: str) -> str:
    path = Path(uri)
    if not path.exists():
        return uri
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def extension_from_media_type(media_type: str) -> str:
    if media_type == "image/svg+xml":
        return ".svg"
    extension = mimetypes.guess_extension(media_type)
    return extension or ".bin"
