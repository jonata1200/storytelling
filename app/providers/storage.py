from pathlib import Path
from uuid import UUID

from app.config.settings import get_settings


def generated_output_dir(
    kind: str,
    project_id: UUID,
    storage_root: Path | None = None,
) -> Path:
    directory_by_kind = {
        "image": "generated_images",
        "video": "generated_videos",
    }
    directory = directory_by_kind.get(kind)
    if directory is None:
        raise ValueError(f"Tipo de output gerado não suportado: {kind}")
    root = storage_root if storage_root is not None else get_settings().local_storage_path
    return root / directory / str(project_id)
