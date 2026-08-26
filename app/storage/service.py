import asyncio
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.config.settings import get_settings
from app.core.enums import AssetKind
from app.storage.schemas import (
    StorageCleanupRead,
    StorageFileRead,
    StorageProjectUsageRead,
    StorageReconciliationRead,
    StorageUsageRead,
)

REMOTE_STORAGE_PREFIXES = ("http://", "https://", "data:")

# Artefatos intermediários do bridge de browser (INC-09): checkpoints
# job-state.json e MP4s parciais não são assets no banco e um job pode ainda
# estar em andamento usando-os. O diretório dedicado fica fora do escopo da
# varredura de órfãos e, como segunda camada, o nome de checkpoint nunca é
# candidato a exclusão.
BRIDGE_JOB_DIR_NAME = "bridge_jobs"
BRIDGE_JOB_CHECKPOINT_FILENAME = "job-state.json"


def _is_bridge_job_artifact(relative_parts: tuple[str, ...], filename: str) -> bool:
    return BRIDGE_JOB_DIR_NAME in {part.lower() for part in relative_parts} or (
        filename.lower() == BRIDGE_JOB_CHECKPOINT_FILENAME
    )


def resolve_local_asset_path(storage_uri: str | None, root: Path | None = None) -> Path | None:
    """Centralized storage-path resolution — single implementation used by all modules.

    Resolves a storage_uri to a Path under the storage root, rejecting path traversal.
    Returns None if the URI is remote, invalid, or outside the root.
    """
    if not storage_uri or storage_uri.startswith(REMOTE_STORAGE_PREFIXES):
        return None
    return resolve_storage_path(storage_uri, root)


@dataclass(frozen=True)
class LocalStorageFile:
    path: Path
    size_bytes: int
    modified_at: datetime | None = None


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


def apply_asset_storage_metadata(
    asset: Asset,
    root: Path | None = None,
    checked_at: datetime | None = None,
) -> bool:
    checked = checked_at or datetime.now(UTC)
    path = resolve_storage_path(asset.storage_uri, root)
    previous = (asset.size_bytes, asset.missing_at, asset.storage_checked_at)
    asset.storage_checked_at = checked
    if path is None:
        asset.missing_at = None
        asset.size_bytes = None
    elif path.is_file():
        asset.size_bytes = path.stat().st_size
        asset.missing_at = None
    else:
        asset.size_bytes = None
        asset.missing_at = checked
    return previous != (asset.size_bytes, asset.missing_at, asset.storage_checked_at)


def validate_file_size(path: Path, max_bytes: int, label: str) -> None:
    if max_bytes is None:
        return
    if max_bytes <= 0:
        raise ValueError(f"{label}: limite de tamanho invalido ({max_bytes} bytes)")
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
            stat = resolved.stat()
        except (OSError, RuntimeError, ValueError):
            continue
        # Checkpoints do bridge nunca entram no inventário (INC-09): são a
        # fonte de retomada dos jobs pendentes, não assets governados.
        if _is_bridge_job_artifact(resolved.parent.relative_to(resolved_root).parts, path.name):
            continue
        files.append(
            LocalStorageFile(
                path=resolved,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            )
        )
    return files


async def iter_local_storage_files_async(root: Path | None = None) -> list[LocalStorageFile]:
    """Async wrapper that offloads sync filesystem I/O to a thread."""
    return await asyncio.to_thread(iter_local_storage_files, root)


def orphan_storage_files(
    referenced_paths: Iterable[Path],
    root: Path | None = None,
) -> list[LocalStorageFile]:
    resolved_root = (root or storage_root()).resolve()
    referenced = {path.resolve(strict=False) for path in referenced_paths}
    return [item for item in iter_local_storage_files(resolved_root) if item.path not in referenced]


async def orphan_storage_files_async(
    referenced_paths: Iterable[Path],
    root: Path | None = None,
) -> list[LocalStorageFile]:
    """Async wrapper that offloads sync filesystem I/O to a thread."""
    return await asyncio.to_thread(orphan_storage_files, list(referenced_paths), root)


def _project_scan_dirs(root: Path, project_id: UUID) -> list[Path]:
    """Diretórios do projeto no layout local: root/<tipo>/<project_id>."""
    if not root.is_dir():
        return []
    project_name = str(project_id)
    project_dirs: list[Path] = []
    direct_project_dir = (root / project_name).resolve()
    if direct_project_dir.is_dir():
        project_dirs.append(direct_project_dir)
    for kind_dir in root.iterdir():
        project_dir = (kind_dir / project_name).resolve()
        if kind_dir.is_dir() and project_dir.is_dir() and project_dir not in project_dirs:
            project_dirs.append(project_dir)
    return project_dirs


def _count_local_files(path: Path) -> int:
    if path.is_file():
        return 1
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def _normalize_kind(kind: AssetKind | str | None) -> AssetKind | None:
    if kind is None or kind == "":
        return None
    if isinstance(kind, AssetKind):
        return kind
    normalized = str(kind).strip().lower()
    for candidate in AssetKind:
        if normalized in {candidate.name.lower(), candidate.value.lower()}:
            return candidate
    raise ValueError(f"Tipo de asset desconhecido: {kind}")


async def _asset_rows(
    session: AsyncSession,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
) -> list[Asset]:
    statement = select(Asset)
    normalized_kind = _normalize_kind(kind)
    if project_id is not None:
        statement = statement.where(Asset.project_id == project_id)
    if normalized_kind is not None:
        statement = statement.where(Asset.kind == normalized_kind)
    result = await session.execute(statement)
    return list(result.scalars())


def _referenced_paths(assets: Iterable[Asset], root: Path) -> list[Path]:
    paths: list[Path] = []
    for asset in assets:
        path = resolve_storage_path(asset.storage_uri, root)
        if path is not None:
            paths.append(path)
    return paths


def _storage_file_read(item: LocalStorageFile, root: Path) -> StorageFileRead:
    try:
        relative = item.path.relative_to(root)
    except ValueError:
        relative = item.path
    return StorageFileRead(
        path=relative.as_posix(),
        size_bytes=item.size_bytes,
        modified_at=item.modified_at,
    )


def _kind_matches_path(item: LocalStorageFile, kind: AssetKind | None, root: Path) -> bool:
    if kind is None:
        return True
    try:
        parts = {part.lower() for part in item.path.relative_to(root).parts}
    except ValueError:
        parts = {part.lower() for part in item.path.parts}
    suffix = item.path.suffix.lower()
    if kind == AssetKind.IMAGE:
        return suffix in {".jpg", ".jpeg", ".png", ".webp"} or any(
            "visual" in part or "storyboard" in part or "reference" in part for part in parts
        )
    if kind == AssetKind.VIDEO:
        return suffix in {".mp4", ".mov", ".webm"} or any("video" in part for part in parts)
    if kind == AssetKind.AUDIO:
        return suffix in {".wav", ".mp3", ".m4a", ".aac"} or any(
            "dialogue" in part or "audio" in part or "speech" in part for part in parts
        )
    if kind == AssetKind.DOCUMENT:
        return suffix in {".json", ".txt", ".srt", ".pdf"} or any(
            "animatic" in part or "export" in part for part in parts
        )
    return True


def _orphan_matches_filters(
    item: LocalStorageFile,
    *,
    root: Path,
    project_id: UUID | None,
    kind: AssetKind | None,
    older_than_days: int | None,
) -> bool:
    if project_id is not None:
        try:
            parts = set(item.path.relative_to(root).parts)
        except ValueError:
            parts = set(item.path.parts)
        if str(project_id) not in parts:
            return False
    if not _kind_matches_path(item, kind, root):
        return False
    if older_than_days is not None:
        if item.modified_at is None:
            return False
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        if item.modified_at > cutoff:
            return False
    return True


async def storage_usage_summary(
    session: AsyncSession,
    project_id: UUID | None = None,
    *,
    include_orphans: bool = False,
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
        if asset.size_bytes is not None:
            usage.local_file_count += 1
            usage.total_bytes += int(asset.size_bytes)
        elif asset.missing_at is not None:
            usage.missing_file_count += 1

    orphan_files: list[LocalStorageFile] = []
    if include_orphans:
        all_assets = await _asset_rows(session)
        orphan_files = await orphan_storage_files_async(_referenced_paths(all_assets, root), root)
    projects = sorted(by_project.values(), key=lambda item: str(item.project_id))
    return StorageUsageRead(
        storage_backend="local",
        project_count=len(projects),
        asset_count=sum(item.asset_count for item in projects),
        local_file_count=sum(item.local_file_count for item in projects),
        missing_file_count=sum(item.missing_file_count for item in projects),
        total_bytes=sum(item.total_bytes for item in projects),
        orphan_file_count=len(orphan_files),
        orphan_total_bytes=sum(item.size_bytes for item in orphan_files),
        projects=projects,
    )


async def reconcile_local_storage(
    session: AsyncSession,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
) -> StorageReconciliationRead:
    root = storage_root()
    normalized_kind = _normalize_kind(kind)
    assets = await _asset_rows(session, project_id, normalized_kind)
    summary = StorageReconciliationRead(
        project_id=project_id,
        kind=normalized_kind.value if normalized_kind is not None else None,
    )
    checked_at = datetime.now(UTC)
    for asset in assets:
        was_missing = asset.missing_at is not None
        changed = apply_asset_storage_metadata(asset, root, checked_at)
        summary.scanned_assets += 1
        if asset.size_bytes is not None:
            summary.local_file_count += 1
            summary.total_bytes += int(asset.size_bytes)
            if was_missing:
                summary.recovered_file_count += 1
        elif asset.missing_at is not None:
            summary.missing_file_count += 1
        if changed:
            summary.updated_asset_count += 1
    await session.flush()
    await session.commit()
    return summary


async def list_orphan_storage_files(
    session: AsyncSession,
    *,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
    older_than_days: int | None = None,
) -> list[StorageFileRead]:
    root = storage_root()
    all_assets = await _asset_rows(session)
    normalized_kind = _normalize_kind(kind)
    referenced_paths = _referenced_paths(all_assets, root)
    if project_id is not None:
        candidates: list[LocalStorageFile] = []
        for project_dir in _project_scan_dirs(root, project_id):
            candidates.extend(await orphan_storage_files_async(referenced_paths, project_dir))
    else:
        candidates = await orphan_storage_files_async(referenced_paths, root)
    return [
        _storage_file_read(item, root)
        for item in candidates
        if _orphan_matches_filters(
            item,
            root=root,
            project_id=project_id,
            kind=normalized_kind,
            older_than_days=older_than_days,
        )
    ]


async def cleanup_orphan_storage_files(
    session: AsyncSession,
    dry_run: bool = True,
    *,
    confirm: bool = False,
    project_id: UUID | None = None,
    kind: AssetKind | str | None = None,
    older_than_days: int | None = None,
) -> StorageCleanupRead:
    root = storage_root()
    candidates = await list_orphan_storage_files(
        session,
        project_id=project_id,
        kind=kind,
        older_than_days=older_than_days,
    )
    if not dry_run and not confirm:
        raise ValueError("Cleanup destrutivo exige confirmacao explicita.")
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


def delete_project_storage_dirs(project_ids: Iterable[UUID]) -> int:
    root = storage_root()
    deleted_count = 0
    for project_id in project_ids:
        for project_dir in _project_scan_dirs(root, project_id):
            try:
                project_dir.relative_to(root)
            except ValueError:
                continue
            file_count = _count_local_files(project_dir)
            try:
                shutil.rmtree(project_dir)
            except OSError:
                continue
            deleted_count += file_count
    return deleted_count


def delete_bridge_job_dirs(job_ids: Iterable[str]) -> int:
    """Remove diretórios de job do bridge de vídeo pelos jobIds do provider.

    Os intermediários do bridge (`storage/bridge_jobs/video/<jobId>`) ficam fora
    do layout `root/<tipo>/<project_id>` e não são alcançados por
    ``delete_project_storage_dirs``. O ``jobId`` do bridge é o UUID gravado em
    ``generation_jobs.external_job_id`` / ``continuous_video_segments``
    (``external_operation_id`` e ``metadata_json.video_job_id``). Ao apagar um
    projeto, esses diretórios devem ser removidos na hora em vez de esperar a
    retenção de 7 dias do ``prune_finished_bridge_jobs``.
    """
    root = storage_root()
    bridge_root = root / BRIDGE_JOB_DIR_NAME / "video"
    if not bridge_root.is_dir():
        return 0
    deleted_count = 0
    for job_id in job_ids:
        job_id = str(job_id or "").strip()
        if not job_id:
            continue
        job_dir = (bridge_root / job_id).resolve()
        try:
            job_dir.relative_to(bridge_root.resolve())
        except ValueError:
            continue
        if not job_dir.is_dir():
            continue
        file_count = _count_local_files(job_dir)
        try:
            shutil.rmtree(job_dir)
        except OSError:
            continue
        deleted_count += file_count
    return deleted_count


def _delete_orphan_candidate(item: StorageFileRead, root: Path) -> bool:
    candidate = Path(item.path)
    if not candidate.is_absolute():
        candidate = root / candidate
    path = candidate.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    _prune_empty_parent_dirs(path, root)
    return True


def _prune_empty_parent_dirs(path: Path, root: Path) -> None:
    parent = path.parent
    while parent != root:
        try:
            parent.relative_to(root)
        except ValueError:
            return
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent
