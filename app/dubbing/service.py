import asyncio
import hashlib
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import ArtifactStatus, ArtifactType, AssetKind, CostEntryType
from app.costs.models import CostEntry
from app.costs.service import cost_audit_metadata, estimate_operation_cost
from app.dubbing.models import DubbingJob
from app.finalization.models import Export
from app.finalization.service import _add_dependency, _create_artifact
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.projects.repository import ProjectRepository
from app.providers.dubbing.elevenlabs import ElevenLabsDubbingProvider
from app.providers.dubbing.types import (
    DubbingProvider,
    DubbingStatusResult,
    DubbingSubmitRequest,
    DubbingSubmitResult,
)
from app.storage.service import apply_asset_storage_metadata, resolve_storage_path

DUBBING_PROVIDER_MODEL = "dubbing-v1"
RUNNING_PROVIDER_STATUSES = {
    "preparing",
    "queued",
    "processing",
    "dubbing",
    "transcribing",
    "translating",
    "rendering",
    "in_progress",
}
SUCCEEDED_PROVIDER_STATUSES = {"dubbed", "done", "completed", "complete", "succeeded"}
FAILED_PROVIDER_STATUSES = {"failed", "error"}


def dubbing_provider_from_settings() -> DubbingProvider:
    settings = get_settings()
    provider = str(settings.dubbing_provider or "").strip().lower()
    if provider == "elevenlabs":
        return ElevenLabsDubbingProvider()
    raise ValueError(f"Provider de dublagem não suportado: {provider}")


def dubbing_configuration_status(
    settings: object | None = None,
) -> tuple[bool, str, dict[str, str]]:
    app_settings = settings or get_settings()
    provider = str(getattr(app_settings, "dubbing_provider", "") or "").strip().lower()
    source = str(getattr(app_settings, "dubbing_source_lang", "") or "").strip()
    target = str(getattr(app_settings, "dubbing_target_lang", "") or "").strip()
    api_key = str(getattr(app_settings, "elevenlabs_api_key", "") or "").strip()
    ready = provider == "elevenlabs" and bool(api_key and target)
    message = (
        "ElevenLabs Dubbing configurado"
        if ready
        else "ELEVENLABS_API_KEY, DUBBING_PROVIDER e DUBBING_TARGET_LANG são necessários"
    )
    return ready, message, {
        "provider": provider or "elevenlabs",
        "source": source,
        "target": target,
    }


async def start_dubbing_job(
    session: AsyncSession,
    project_id: UUID,
    export_id: UUID,
    *,
    source_language: str | None = None,
    target_language: str | None = None,
    provider: DubbingProvider | None = None,
) -> DubbingJob | None:
    project = await ProjectRepository(session).get_project(project_id)
    export = await session.get(Export, export_id)
    if project is None or export is None or export.project_id != project_id:
        return None

    settings = get_settings()
    source = _language(source_language or settings.dubbing_source_lang, allow_empty=True)
    target = _language(target_language or settings.dubbing_target_lang)
    if target is None:
        raise ValueError("Idioma de dublagem não configurado")
    export_path = _export_path(export.output_uri)
    provider_client = provider or dubbing_provider_from_settings()
    estimate = estimate_operation_cost(
        "dubbing",
        Decimal(max(1, export.duration_seconds)) / Decimal("60"),
        provider=getattr(provider_client, "provider_name", "elevenlabs"),
        model=DUBBING_PROVIDER_MODEL,
    )
    job = DubbingJob(
        project_id=project_id,
        export_id=export.id,
        provider=getattr(provider_client, "provider_name", "elevenlabs"),
        model=DUBBING_PROVIDER_MODEL,
        status="PENDING",
        progress=0,
        source_language=source,
        target_language=target,
        cost_estimate=estimate.estimated,
        metadata_json={"export_uri": export.output_uri},
    )
    session.add(job)
    await session.flush()
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=project_id,
            artifact_id=export.artifact_id,
            event_type="dubbing",
            status="running",
            provider=job.provider,
            model=job.model,
            operation="dubbing_submit",
            estimated_cost=estimate.estimated,
            message="Dublagem enviada ao provider",
            details={"target_language": target, "source_language": source},
        ),
    )
    submit_result = await _submit(provider_client, export_path, export, source, target)
    job.external_job_id = submit_result.external_job_id
    job.status = "PROCESSING"
    job.progress = 10
    job.metadata_json = {
        **dict(job.metadata_json or {}),
        "submit": submit_result.metadata,
        "expected_duration_seconds": submit_result.expected_duration_seconds,
    }
    session.add(
        CostEntry(
            project_id=project_id,
            artifact_id=export.artifact_id,
            entry_type=CostEntryType.ESTIMATE,
            provider=job.provider,
            model=job.model,
            operation="dubbing",
            quantity=estimate.quantity,
            unit=estimate.unit,
            unit_cost=estimate.unit_cost,
            total_cost=estimate.estimated,
            currency=estimate.currency,
            metadata_json=cost_audit_metadata(
                estimated_cost=estimate.estimated,
                final_budget_cost=estimate.estimated,
                stage="dubbing",
            ),
        )
    )
    await session.commit()
    await session.refresh(job)
    return job


async def refresh_dubbing_job(
    session: AsyncSession,
    project_id: UUID,
    job_id: UUID,
    *,
    provider: DubbingProvider | None = None,
    download_when_ready: bool = True,
) -> DubbingJob | None:
    job = await session.get(DubbingJob, job_id)
    if job is None or job.project_id != project_id:
        return None
    if not job.external_job_id:
        return job
    if job.status == "SUCCEEDED" and job.result_asset_id is not None:
        return job

    provider_client = provider or dubbing_provider_from_settings()
    status = await _status(provider_client, job.external_job_id)
    mapped_status = _map_provider_status(status.status)
    job.status = mapped_status
    job.progress = _progress_for_status(mapped_status)
    job.error = status.error
    job.source_language = status.source_language or job.source_language
    job.metadata_json = {
        **dict(job.metadata_json or {}),
        "status": status.metadata,
        "provider_status": status.status,
    }
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=project_id,
            event_type="dubbing",
            status="failed" if mapped_status == "FAILED" else "running",
            provider=job.provider,
            model=job.model,
            operation="dubbing_poll",
            message=status.error or f"Dublagem em estado {status.status}",
            details={"external_job_id": job.external_job_id, "status": status.status},
        ),
    )
    if mapped_status == "SUCCEEDED" and download_when_ready:
        await _download_result(session, job, provider_client)
    await session.commit()
    await session.refresh(job)
    return job


async def list_dubbing_jobs(
    session: AsyncSession,
    project_id: UUID,
    export_id: UUID | None = None,
) -> list[DubbingJob]:
    statement = select(DubbingJob).where(DubbingJob.project_id == project_id)
    if export_id is not None:
        statement = statement.where(DubbingJob.export_id == export_id)
    result = await session.execute(statement.order_by(DubbingJob.created_at.desc()))
    return list(result.scalars())


async def _submit(
    provider: DubbingProvider,
    export_path: Path,
    export: Export,
    source_language: str | None,
    target_language: str,
) -> DubbingSubmitResult:
    return await asyncio.to_thread(
        provider.submit,
        DubbingSubmitRequest(
            file_path=export_path,
            name=f"storytelling-export-{export.id}",
            source_language=source_language,
            target_language=target_language,
        ),
    )


async def _status(provider: DubbingProvider, external_job_id: str) -> DubbingStatusResult:
    return await asyncio.to_thread(provider.status, external_job_id)


async def _download_result(
    session: AsyncSession,
    job: DubbingJob,
    provider: DubbingProvider,
) -> None:
    export = await session.get(Export, job.export_id)
    if export is None:
        raise ValueError("Export original da dublagem não encontrado")
    download = await asyncio.to_thread(
        provider.download,
        str(job.external_job_id),
        job.target_language,
    )
    settings = get_settings()
    output_dir = settings.local_storage_path / "dubbing" / str(job.project_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    from app.providers.media_utils import extension_from_media_type

    extension = extension_from_media_type(download.content_type)
    file_path = output_dir / f"dub_{job.target_language}_{job.id.hex[:8]}{extension}"
    file_path.write_bytes(download.content)
    digest = hashlib.sha256(download.content).hexdigest()
    artifact = await _create_artifact(
        session,
        job.project_id,
        ArtifactType.EXPORT,
        f"Dublagem {job.target_language}",
        {
            "export_id": str(export.id),
            "dubbing_job_id": str(job.id),
            "target_language": job.target_language,
            "source_language": job.source_language,
            "provider": job.provider,
            "external_job_id": job.external_job_id,
        },
        ArtifactStatus.READY_FOR_REVIEW,
    )
    await _add_dependency(session, export.artifact_id, artifact.id)
    kind = AssetKind.VIDEO if download.content_type.startswith("video/") else AssetKind.AUDIO
    asset = Asset(
        project_id=job.project_id,
        artifact_id=artifact.id,
        kind=kind,
        name=f"Dublagem {job.target_language}",
        storage_uri=file_path.as_posix(),
        content_type=download.content_type,
        sha256=digest,
        metadata_json={
            "provider": job.provider,
            "model": job.model,
            "source_language": job.source_language,
            "target_language": job.target_language,
            "external_job_id": job.external_job_id,
            **download.metadata,
        },
    )
    apply_asset_storage_metadata(asset)
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
    job.result_artifact_id = artifact.id
    job.result_asset_id = asset.id
    job.result_uri = asset.storage_uri
    job.progress = 100
    job.metadata_json = {
        **dict(job.metadata_json or {}),
        "download": download.metadata,
        "result_content_type": download.content_type,
    }
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=job.project_id,
            artifact_id=artifact.id,
            event_type="dubbing",
            status="succeeded",
            provider=job.provider,
            model=job.model,
            operation="dubbing_download",
            estimated_cost=job.cost_estimate,
            message="Dublagem baixada e registrada como asset",
            details={
                "asset_id": str(asset.id),
                "export_id": str(export.id),
                "target_language": job.target_language,
            },
        ),
    )


def _language(value: str | None, *, allow_empty: bool = False) -> str | None:
    language = str(value or "").strip().lower()
    if not language and allow_empty:
        return None
    if not language:
        raise ValueError("Idioma de dublagem não configurado")
    if len(language) > 16 or not language.replace("-", "").isalpha():
        raise ValueError(f"Idioma de dublagem inválido: {language}")
    return language


def _export_path(output_uri: str) -> Path:
    path = resolve_storage_path(output_uri)
    if path is None or not path.is_file():
        raise ValueError("Arquivo de export local não encontrado para dublagem")
    return path


def _map_provider_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in SUCCEEDED_PROVIDER_STATUSES:
        return "SUCCEEDED"
    if normalized in FAILED_PROVIDER_STATUSES:
        return "FAILED"
    if normalized in RUNNING_PROVIDER_STATUSES:
        return "PROCESSING"
    return "PROCESSING"


def _progress_for_status(status: str) -> int:
    if status == "SUCCEEDED":
        return 100
    if status == "FAILED":
        return 100
    return 50
