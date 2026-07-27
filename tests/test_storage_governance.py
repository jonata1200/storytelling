from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage import service as storage_service


def _settings(root: Path, max_generated_asset_bytes: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        local_storage_path=root,
        max_generated_asset_bytes=max_generated_asset_bytes,
    )


def test_resolve_storage_path_rejects_paths_outside_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))

    assert storage_service.resolve_storage_path(outside.as_posix()) is None


def test_orphan_storage_files_finds_unreferenced_local_files(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    referenced = storage_root / "asset.txt"
    orphan = storage_root / "orphan.txt"
    referenced.write_text("asset", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")

    files = storage_service.orphan_storage_files([referenced], storage_root)

    assert [item.path for item in files] == [orphan.resolve()]
    assert files[0].size_bytes == 6


class _FakeAssetSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def execute(self, statement: Any) -> Any:
        return SimpleNamespace(scalars=lambda: self.rows)


@pytest.mark.asyncio
async def test_cleanup_orphan_storage_files_supports_dry_run_and_effective_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    referenced = storage_root / "asset.txt"
    orphan = storage_root / "orphan.txt"
    referenced.write_text("asset", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")
    monkeypatch.setattr(storage_service, "get_settings", lambda: _settings(storage_root))
    session = _FakeAssetSession(
        [SimpleNamespace(storage_uri=referenced.as_posix(), project_id="project", kind="IMAGE")]
    )

    dry_run = await storage_service.cleanup_orphan_storage_files(
        cast(AsyncSession, session),
        dry_run=True,
    )
    deleted = await storage_service.cleanup_orphan_storage_files(
        cast(AsyncSession, session),
        dry_run=False,
    )

    assert dry_run.candidate_count == 1
    assert dry_run.deleted_count == 0
    assert deleted.deleted_count == 1
    assert not orphan.exists()
    assert referenced.exists()


def test_validate_asset_uri_size_raises_for_large_local_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    asset = storage_root / "large.bin"
    asset.write_bytes(b"12345")
    monkeypatch.setattr(
        storage_service,
        "get_settings",
        lambda: _settings(storage_root, max_generated_asset_bytes=4),
    )

    with pytest.raises(ValueError, match="excede o limite"):
        storage_service.validate_asset_uri_size(asset.as_posix())
