from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.dubbing.service as dubbing_service
from app.dubbing.service import (
    _language,
    _map_provider_status,
    dubbing_configuration_status,
    start_dubbing_job,
)
from app.finalization.models import Export
from app.projects.models import Project
from app.providers.dubbing.types import (
    DubbingDownloadResult,
    DubbingStatusResult,
    DubbingSubmitRequest,
    DubbingSubmitResult,
)


class _FakeDubbingProvider:
    provider_name = "elevenlabs"

    def __init__(self) -> None:
        self.request: DubbingSubmitRequest | None = None

    def submit(self, request: DubbingSubmitRequest) -> DubbingSubmitResult:
        self.request = request
        return DubbingSubmitResult(
            external_job_id="dub-123",
            expected_duration_seconds=9,
            metadata={"ok": True},
        )

    def status(self, external_job_id: str) -> DubbingStatusResult:
        return DubbingStatusResult(
            external_job_id=external_job_id,
            status="processing",
            target_languages=["en"],
        )

    def download(self, external_job_id: str, language_code: str) -> DubbingDownloadResult:
        _ = external_job_id, language_code
        return DubbingDownloadResult(content=b"", content_type="video/mp4")


class _FakeSession:
    def __init__(self, project: Project, export: Export) -> None:
        self.project = project
        self.export = export
        self.added: list[Any] = []
        self.flushed = False
        self.committed = False
        self.refreshed: list[Any] = []

    async def get(self, model: type[Any], key: object) -> Any:
        if model is Project and key == self.project.id:
            return self.project
        if model is Export and key == self.export.id:
            return self.export
        return None

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, value: Any) -> None:
        self.refreshed.append(value)


def test_dubbing_configuration_status_reports_elevenlabs() -> None:
    ready, message, details = dubbing_configuration_status(
        type(
            "SettingsLike",
            (),
            {
                "dubbing_provider": "elevenlabs",
                "dubbing_source_lang": "pt",
                "dubbing_target_lang": "en",
                "elevenlabs_api_key": "secret",
            },
        )()
    )

    assert ready is True
    assert "ElevenLabs" in message
    assert details == {"provider": "elevenlabs", "source": "pt", "target": "en"}


def test_dubbing_status_and_language_helpers() -> None:
    assert _map_provider_status("dubbed") == "SUCCEEDED"
    assert _map_provider_status("failed") == "FAILED"
    assert _map_provider_status("preparing") == "PROCESSING"
    assert _language("PT-br") == "pt-br"
    with pytest.raises(ValueError, match="inválido"):
        _language("pt_123")


@pytest.mark.asyncio
async def test_start_dubbing_job_submits_export_and_records_cost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    export_id = uuid4()
    artifact_id = uuid4()
    asset_id = uuid4()
    export_file = tmp_path / "storage" / "exports" / "final.mp4"
    export_file.parent.mkdir(parents=True)
    export_file.write_bytes(b"video")
    project = Project(id=project_id, title="Projeto")
    export = Export(
        id=export_id,
        project_id=project_id,
        artifact_id=artifact_id,
        timeline_id=uuid4(),
        asset_id=asset_id,
        status="RENDERED",
        profile={},
        duration_seconds=120,
        output_uri=export_file.as_posix(),
    )
    session = _FakeSession(project, export)
    provider = _FakeDubbingProvider()

    monkeypatch.setattr(
        dubbing_service,
        "get_settings",
        lambda: type(
            "SettingsLike",
            (),
            {
                "local_storage_path": tmp_path / "storage",
                "dubbing_source_lang": "pt",
                "dubbing_target_lang": "en",
            },
        )(),
    )
    monkeypatch.setattr(dubbing_service, "resolve_storage_path", lambda _uri: export_file)

    job = await start_dubbing_job(
        cast(AsyncSession, session),
        project_id,
        export_id,
        provider=provider,
    )

    assert job is not None
    assert provider.request is not None
    assert provider.request.file_path == export_file
    assert provider.request.target_language == "en"
    assert job.external_job_id == "dub-123"
    assert job.status == "PROCESSING"
    assert job.cost_estimate == Decimal("0.660000")
    assert session.flushed is True
    assert session.committed is True
