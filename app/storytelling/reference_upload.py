import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import AssetKind

REFERENCE_CATEGORIES = {
    "auto": "Referencia visual",
    "character": "Personagem",
    "location": "Local",
    "prop": "Objeto",
}
IMAGE_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


class ReferenceUploadError(ValueError):
    pass


def prepare_reference_upload(
    filename: str,
    content: bytes,
    category: str | None = None,
) -> dict[str, Any]:
    normalized_category = normalize_reference_category(category)
    extension = _image_extension(filename)
    if extension not in IMAGE_EXTENSIONS:
        raise ReferenceUploadError("Envie imagens JPG, PNG ou WebP.")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise ReferenceUploadError("A imagem deve ter no maximo 10 MB.")
    if not content:
        raise ReferenceUploadError("A imagem enviada esta vazia.")
    return {
        "filename": Path(filename).name,
        "category": normalized_category,
        "category_label": REFERENCE_CATEGORIES[normalized_category],
        "content_type": IMAGE_EXTENSIONS[extension],
        "extension": extension,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content": content,
    }


def normalize_reference_category(category: str | None) -> str:
    normalized = str(category or "").strip().lower()
    if not normalized:
        return "auto"
    if normalized not in REFERENCE_CATEGORIES:
        raise ReferenceUploadError("A categoria da imagem de referencia e invalida.")
    return normalized


def reference_asset_name(category: str) -> str:
    label = REFERENCE_CATEGORIES[category]
    if category == "auto":
        return label
    return f"Referencia de {label}"


async def persist_reference_uploads(
    session: AsyncSession,
    project_id: UUID,
    artifact_id: UUID | None,
    uploads: list[dict[str, Any]],
) -> list[Asset]:
    assets: list[Asset] = []
    for upload in uploads:
        asset = await persist_reference_upload(session, project_id, artifact_id, upload)
        assets.append(asset)
    return assets


async def persist_reference_upload(
    session: AsyncSession,
    project_id: UUID,
    artifact_id: UUID | None,
    upload: dict[str, Any],
) -> Asset:
    category = normalize_reference_category(str(upload.get("category") or ""))
    extension = str(upload.get("extension") or _image_extension(str(upload.get("filename") or "")))
    if extension not in IMAGE_EXTENSIONS:
        raise ReferenceUploadError("Imagem de referencia sem extensao valida.")
    content = upload.get("content")
    if not isinstance(content, bytes) or not content:
        raise ReferenceUploadError("Imagem de referencia sem conteudo.")
    settings = get_settings()
    target_dir = settings.local_storage_path / "uploaded_references" / str(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{category}_{uuid4().hex[:10]}{extension}"
    target = target_dir / filename
    target.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    asset = Asset(
        project_id=project_id,
        artifact_id=artifact_id,
        kind=AssetKind.IMAGE,
        name=reference_asset_name(category),
        storage_uri=target.as_posix(),
        content_type=IMAGE_EXTENSIONS[extension],
        sha256=sha256,
        metadata_json={
            "source": "dashboard_upload",
            "reference_category": category,
            "reference_category_label": REFERENCE_CATEGORIES[category],
            "original_filename": str(upload.get("filename") or ""),
        },
    )
    session.add(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            metadata_json=asset.metadata_json,
        )
    )
    return asset


def _image_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return ".jpg" if suffix == ".jpeg" else suffix
