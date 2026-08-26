from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.video_generation import finalization, finalization_router


def _segment(number: int, *, completed: bool, storage_uri: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        segment_number=number,
        generated_video_asset_id=uuid4() if completed else None,
        asset_id=None,
        review_status="done" if completed else "pending",
        metadata_json={"video_storage_uri": storage_uri} if storage_uri else {},
    )


@pytest.mark.asyncio
async def test_concatenation_rejects_partial_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segments = [
        _segment(1, completed=True),
        _segment(2, completed=True),
        _segment(3, completed=True),
        _segment(4, completed=False),
    ]

    async def list_segments(_session: object, _project_id: object) -> list[SimpleNamespace]:
        return segments

    monkeypatch.setattr(finalization, "list_continuous_video_segments", list_segments)

    with pytest.raises(RuntimeError, match="Todos os segmentos"):
        await finalization.concatenate_videos(object(), uuid4())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_concatenation_resolves_segment_uris_through_storage_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = []
    segments = []
    for number in range(1, 4):
        path = tmp_path / f"segment-{number}.mp4"
        path.write_bytes(f"video-{number}".encode())
        paths.append(path)
        segments.append(_segment(number, completed=True, storage_uri=f"relative/{path.name}"))

    async def list_segments(_session: object, _project_id: object) -> list[SimpleNamespace]:
        return segments

    resolved_uris: list[str] = []

    def resolve_uri(uri: str) -> Path:
        resolved_uris.append(uri)
        return paths[len(resolved_uris) - 1]

    captured: dict[str, object] = {}

    async def concatenate(video_paths: list[Path], _project_id: object) -> Path:
        captured["paths"] = video_paths
        return tmp_path / "final.mp4"

    expected_asset = SimpleNamespace(id=uuid4())

    async def create_asset(
        _session: object, _project_id: object, _path: Path, segment_count: int
    ) -> SimpleNamespace:
        captured["segment_count"] = segment_count
        return expected_asset

    monkeypatch.setattr(finalization, "list_continuous_video_segments", list_segments)
    monkeypatch.setattr(finalization, "resolve_storage_path", resolve_uri)
    monkeypatch.setattr(finalization, "_concatenate_with_ffmpeg", concatenate)
    monkeypatch.setattr(finalization, "_create_final_video_asset", create_asset)

    result = await finalization.concatenate_videos(object(), uuid4())  # type: ignore[arg-type]

    assert result is expected_asset
    assert resolved_uris == [f"relative/segment-{number}.mp4" for number in range(1, 4)]
    assert captured == {"paths": paths, "segment_count": 3}


def test_sha256_file_reads_large_files_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"abc" * 100)

    assert finalization._sha256_file(path, chunk_size=7) == (
        "d9f5aeb06abebb3be3f38adec9a2e3b94228d52193be923eb4e24c9b56ee0930"
    )


@pytest.mark.asyncio
async def test_finalization_endpoint_does_not_expose_internal_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_project(self, _project_id: object) -> object:
            return object()

    async def fail(_session: object, _project_id: object) -> None:
        raise ValueError("internal path C:/private/video.mp4")

    monkeypatch.setattr(finalization_router, "ProjectRepository", Repository)
    monkeypatch.setattr(finalization_router, "concatenate_videos", fail)

    with pytest.raises(HTTPException) as captured:
        await finalization_router.finalize_video(uuid4(), object())  # type: ignore[arg-type]

    assert captured.value.status_code == 500
    assert captured.value.detail == "Erro interno ao finalizar vídeo."
