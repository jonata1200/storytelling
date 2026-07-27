from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling import reference_upload
from app.storytelling.reference_upload import (
    ReferenceUploadError,
    persist_reference_upload,
    prepare_reference_upload,
)


def test_prepare_reference_upload_accepts_image_category() -> None:
    prepared = prepare_reference_upload("hero.png", b"image-bytes", "character")

    assert prepared["filename"] == "hero.png"
    assert prepared["category"] == "character"
    assert prepared["category_label"] == "Personagem"
    assert prepared["content_type"] == "image/png"
    assert len(prepared["sha256"]) == 64


def test_prepare_reference_upload_defaults_to_auto_reference() -> None:
    prepared = prepare_reference_upload("moodboard.jpg", b"image-bytes")

    assert prepared["filename"] == "moodboard.jpg"
    assert prepared["category"] == "auto"
    assert prepared["category_label"] == "Referencia visual"
    assert prepared["content_type"] == "image/jpeg"


def test_prepare_reference_upload_rejects_non_image() -> None:
    with pytest.raises(ReferenceUploadError, match="JPG, PNG ou WebP"):
        prepare_reference_upload("roteiro.pdf", b"not-image", "prop")


class _FakeAssetSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid4()


def _path_is_file(path_value: str) -> bool:
    return Path(path_value).is_file()


@pytest.mark.asyncio
async def test_persist_reference_upload_writes_asset_inside_project_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reference_upload,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    session = _FakeAssetSession()
    project_id = uuid4()
    artifact_id = uuid4()
    prepared = prepare_reference_upload("portal.webp", b"image-bytes", "location")

    asset = await persist_reference_upload(
        cast(AsyncSession, session),
        project_id,
        artifact_id,
        prepared,
    )

    assert _path_is_file(asset.storage_uri)
    assert str(project_id) in asset.storage_uri
    assert asset.artifact_id == artifact_id
    assert asset.metadata_json["reference_category"] == "location"
    assert asset.metadata_json["original_filename"] == "portal.webp"


@pytest.mark.asyncio
async def test_persist_reference_upload_accepts_auto_reference_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reference_upload,
        "get_settings",
        lambda: SimpleNamespace(local_storage_path=tmp_path),
    )
    session = _FakeAssetSession()
    project_id = uuid4()
    prepared = prepare_reference_upload("referencia.png", b"image-bytes")

    asset = await persist_reference_upload(
        cast(AsyncSession, session),
        project_id,
        None,
        prepared,
    )

    assert _path_is_file(asset.storage_uri)
    assert asset.name == "Referencia visual"
    assert asset.metadata_json["reference_category"] == "auto"
    assert asset.metadata_json["reference_category_label"] == "Referencia visual"
