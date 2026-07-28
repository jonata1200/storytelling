from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.config.settings import get_settings
from app.storage.schemas import (
    StorageCleanupRead,
    StorageFileRead,
    StorageProjectUsageRead,
    StorageUsageRead,
)

REMOTE_STORAGE_PREFIXES = ("http://", "https://", "data:")


@dataclass(frozen=True)
class LocalStorageFile:
    path: Path
    size_bytes: int


def storage_root() -> Path:
    return get_settings().local_storage_path.resolve()


def resolve_storage_path(storage_uri: str | None, root: Path | None = None) -> Path | None:
    if not storage_uri or storage_uri.startswith(REMOTE_STORAGE_PREFIXES):
        return None
    resolved_root = (root or storage_root()).resolve()
    candidate = Path(storage_uri)
    candidates: list[Path]
    if candidate.is_absolute():
        candidates = [candidate.resolve(strict=False)]
    else:
        candidates = []
        if candidate.parts and candidate.parts[0] == resolved_root.name:
            candidates.append((resolved_root.parent / candidate).resolve(strict=False))
            candidates.append(resolved_root.joinpath(*candidate.parts[1:]).resolve(strict=False))
        candidates.extend(
            [(resolved_root / candidate).resolve(strict=False), candidate.resolve(strict=False)]
        )
    for path in candidates:
        try:
            path.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            continue
        return path
    return None


def file_size_for_uri(storage_uri: str | None, root: Path | None = None) -> int | None:
    path = resolve_storage_path(storage_uri, root)
    if path is None or not path.is_file():
        return None
    return path.stat().st_size


def validate_file_size(path: Path, max_bytes: int, label: str) -> None:
    if max_bytes <= 0:
        return
    size_bytes = path.stat().st_size
    if size_bytes > max_bytes:
        raise ValueError(f"{label} excede o limite de {max_bytes} bytes")


def validate_asset_uri_size(
    storage_uri: str | None,
    max_bytes: int | None = None,
    label: str = "Asset",
) -> None:
    path = resolve_storage_path(storage_uri)
    if path is None or not path.is_file():
        return
    validate_file_size(path, max_bytes or get_settings().max_generated_asset_bytes, label)


def iter_local_storage_files(root: Path | None = None) -> list[LocalStorageFile]:
    resolved_root = (root or storage_root()).resolve()
    if not resolved_root.exists():
        return []
    files: list[LocalStorageFile] = []
    for path in resolved_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            continue
        files.append(LocalStorageFile(path=resolved, size_bytes=resolved.stat().st_size))
    return files


def orphan_storage_files(
    referenced_paths: Iterable[Path],
    root: Path | None = None,
) -> list[LocalStorageFile]:
    resolved_root = (root or storage_root()).resolve()
    referenced = {path.resolve(strict=False) for path in referenced_paths}
    return [
        item for item in iter_local_storage_files(resolved_root) if item.path not in referenced
    ]


async def _asset_rows(session: AsyncSession, project_id: UUID | None = None) -> list[Asset]:
    statement = select(Asset)
    if project_id is not None:
        statement = statement.where(Asset.project_id == project_id)
    result = await session.execute(statement)
    return list(result.scalars())


def _referenced_paths(assets: Iterable[Asset], root: Path) -> list[Path]:
    paths: list[Path] = []
    for asset in assets:
        path = resolve_storage_path(asset.storage_uri, root)
        if path is not None:
            paths.append(path)
    return paths


async def storage_usage_summary(
    session: AsyncSession,
    project_id: UUID | None = None,
) -> StorageUsageRead:
    root = storage_root()
    assets = await _asset_rows(session, project_id)
    by_project: dict[UUID, StorageProjectUsageRead] = {}
    for asset in assets:
        usage = by_project.setdefault(
            asset.project_id,
            StorageProjectUsageRead(project_id=asset.project_id),
        )
        usage.asset_count += 1
        kind = str(asset.kind.value if hasattr(asset.kind, "value") else asset.kind)
        usage.by_kind[kind] = usage.by_kind.get(kind, 0) + 1
        file_size = file_size_for_uri(asset.storage_uri, root)
        if file_size is None:
            if resolve_storage_path(asset.storage_uri, root) is not None:
                usage.missing_file_count += 1
            continue
        usage.local_file_count += 1
        usage.total_bytes += file_size

    orphan_files = orphan_storage_files(_referenced_paths(assets, root), root)
    projects = sorted(by_project.values(), key=lambda item: str(item.project_id))
    return StorageUsageRead(
        storage_root=root,
        project_count=len(projects),
        asset_count=sum(item.asset_count for item in projects),
        local_file_count=sum(item.local_file_count for item in projects),
        missing_file_count=sum(item.missing_file_count for item in projects),
        total_bytes=sum(item.total_bytes for item in projects),
        orphan_file_count=len(orphan_files),
        orphan_total_bytes=sum(item.size_bytes for item in orphan_files),
        projects=projects,
    )


async def list_orphan_storage_files(session: AsyncSession) -> list[StorageFileRead]:
    root = storage_root()
    assets = await _asset_rows(session)
    return [
        StorageFileRead(path=item.path.as_posix(), size_bytes=item.size_bytes)
        for item in orphan_storage_files(_referenced_paths(assets, root), root)
    ]


async def cleanup_orphan_storage_files(
    session: AsyncSession,
    dry_run: bool = True,
) -> StorageCleanupRead:
    root = storage_root()
    candidates = await list_orphan_storage_files(session)
    deleted_count = 0
    deleted_total_bytes = 0
    skipped_count = 0
    if not dry_run:
        for item in candidates:
            if not _delete_orphan_candidate(item, root):
                skipped_count += 1
                continue
            deleted_count += 1
            deleted_total_bytes += item.size_bytes
    return StorageCleanupRead(
        dry_run=dry_run,
        candidate_count=len(candidates),
        candidate_total_bytes=sum(item.size_bytes for item in candidates),
        deleted_count=deleted_count,
        deleted_total_bytes=deleted_total_bytes,
        skipped_count=skipped_count,
        files=candidates,
    )


async def project_asset_storage_uris(session: AsyncSession, project_id: UUID) -> list[str]:
    result = await session.execute(select(Asset.storage_uri).where(Asset.project_id == project_id))
    return [str(row[0] or "") for row in result.all()]


def delete_local_storage_files(storage_uris: Iterable[str]) -> int:
    deleted_count = 0
    for storage_uri in storage_uris:
        path = resolve_storage_path(storage_uri)
        if path is None or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted_count += 1
    return deleted_count


def _delete_orphan_candidate(item: StorageFileRead, root: Path) -> bool:
    path = Path(item.path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
