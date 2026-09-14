from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.video_generation.storyboard_export import (
    slugify_file_part,
    storyboard_zip_entry_name,
    storyboard_zip_filename,
)


def test_slugify_removes_accents_and_spaces() -> None:
    assert slugify_file_part("A Viagem de João!") == "a-viagem-de-joao"
    assert slugify_file_part("  Cidade & Magia  ") == "cidade-magia"


def test_slugify_collapses_separators_and_caps_length() -> None:
    assert slugify_file_part("///---///") == ""
    assert slugify_file_part("A!!B??C") == "a-b-c"
    long_title = "X" * 300
    assert len(slugify_file_part(long_title)) == 80


def test_slugify_empty_returns_empty_string() -> None:
    assert slugify_file_part(None) == ""
    assert slugify_file_part("") == ""


def test_zip_filename_uses_project_slug() -> None:
    assert storyboard_zip_filename("Meu Projeto") == "meu-projeto-storyboards.zip"
    assert storyboard_zip_filename("") == "storyboard-storyboards.zip"


def test_zip_entry_name_includes_project_segment_number_and_title() -> None:
    name = storyboard_zip_entry_name("A Torre", 3, "A Descida", ".webp")
    assert name == "a-torre/segmento-03-a-descida.webp"


def test_zip_entry_name_without_segment_title_keeps_number() -> None:
    assert storyboard_zip_entry_name("A Torre", 7, "", ".png") == "a-torre/segmento-07.png"


def test_zip_entry_name_defaults_suffix_to_webp() -> None:
    assert storyboard_zip_entry_name("P", 1, "t", "") == "p/segmento-01-t.webp"


@pytest.mark.asyncio
async def test_download_endpoint_names_entries_after_project_and_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import io

    from app.video_generation import router as video_router

    frame = tmp_path / "frame.webp"
    frame.write_bytes(b"fake-image-bytes")

    project = SimpleNamespace(title="A Torre de Marfim")
    segments = [
        SimpleNamespace(segment_number=1, title="A Chegada", source_frame_asset_id="a1"),
        SimpleNamespace(segment_number=2, title="", source_frame_asset_id=None),
        SimpleNamespace(segment_number=3, title="O Encontro", source_frame_asset_id="a3"),
    ]
    assets = {
        "a1": SimpleNamespace(storage_uri="storage/generated_images/x1.webp"),
        "a3": SimpleNamespace(storage_uri="storage/generated_images/x3.webp"),
    }

    class FakeRepo:
        def __init__(self, _session) -> None:
            pass

        async def get_project(self, _project_id):
            return project

    async def fake_list_segments(_session, _project_id):
        return segments

    async def fake_get(_model, asset_id):
        return assets.get(asset_id)

    monkeypatch.setattr("app.projects.repository.ProjectRepository", FakeRepo)
    monkeypatch.setattr(video_router, "list_continuous_video_segments", fake_list_segments)

    class FakeSession:
        async def get(self, _model, key):
            return await fake_get(_model, key)

    session = FakeSession()

    import app.storage.service as storage_service  # noqa: F401

    monkeypatch.setattr(
        video_router,
        "resolve_storage_path",
        lambda uri, root=None: frame if uri else None,
    )

    response = await video_router.get_continuous_video_segments_download(
        "11111111-1111-1111-1111-111111111111",  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="a-torre-de-marfim-storyboards.zip"' in response.headers[
        "content-disposition"
    ]

    with ZipFile(io.BytesIO(response.body)) as archive:
        names = archive.namelist()
    assert names == [
        "a-torre-de-marfim/segmento-01-a-chegada.webp",
        "a-torre-de-marfim/segmento-03-o-encontro.webp",
    ]


@pytest.mark.asyncio
async def test_download_endpoint_404_without_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from app.video_generation import router as video_router

    project = SimpleNamespace(title="Projeto Vazio")

    class FakeRepo:
        def __init__(self, _session) -> None:
            pass

        async def get_project(self, _project_id):
            return project

    async def fake_list_segments(_session, _project_id):
        return [SimpleNamespace(segment_number=1, title="S", source_frame_asset_id=None)]

    monkeypatch.setattr("app.projects.repository.ProjectRepository", FakeRepo)
    monkeypatch.setattr(video_router, "list_continuous_video_segments", fake_list_segments)

    with pytest.raises(HTTPException) as exc_info:
        await video_router.get_continuous_video_segments_download("pid", object())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404