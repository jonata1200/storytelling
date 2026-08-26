from pathlib import Path

import pytest

from app.config.settings import Settings
from app.providers.video import vibes_playwright
from app.providers.video.types import VideoJob
from app.providers.video.vibes_playwright import PlaywrightVibesBrowserBackend


async def test_submit_persists_checkpoint_before_generation_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, local_storage_path=tmp_path / "storage")
    checkpoint = settings.local_storage_path / "bridge_jobs/video/job-1/job-state.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")

    async def fake_bridge(action: str, payload: dict, *, timeout_seconds: float) -> dict:
        assert action == "submit-video"
        assert timeout_seconds == 180
        return {
            "jobId": "job-1",
            "pollingUrl": checkpoint.as_posix(),
            "projectUrl": "https://vibes.ai/projects/project-1",
            "status": "pending",
        }

    monkeypatch.setattr(vibes_playwright, "get_settings", lambda: settings)
    monkeypatch.setattr(vibes_playwright, "run_browser_bridge", fake_bridge)

    job = await PlaywrightVibesBrowserBackend().submit({"prompt": "Cena"})

    assert job.id == "job-1"
    assert job.status == "pending"
    assert job.polling_url == checkpoint.resolve().as_posix()
    assert job.project_url == "https://vibes.ai/projects/project-1"


async def test_poll_returns_each_available_variant_and_ignores_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, local_storage_path=tmp_path / "storage")
    job_dir = settings.local_storage_path / "bridge_jobs/video/job-1"
    job_dir.mkdir(parents=True)
    checkpoint = job_dir / "job-state.json"
    checkpoint.write_text("{}", encoding="utf-8")
    first = job_dir / "result-1.mp4"
    first.write_bytes(b"video")

    async def fake_bridge(action: str, payload: dict, *, timeout_seconds: float) -> dict:
        assert action == "poll-video"
        assert payload["statePath"] == checkpoint.resolve().as_posix()
        return {
            "status": "pending",
            "projectUrl": "https://vibes.ai/projects/project-1",
            "filePaths": [first.as_posix(), (job_dir / "missing.mp4").as_posix()],
        }

    monkeypatch.setattr(vibes_playwright, "get_settings", lambda: settings)
    monkeypatch.setattr(vibes_playwright, "run_browser_bridge", fake_bridge)
    job = VideoJob(id="job-1", polling_url=checkpoint.resolve().as_posix())

    update = await PlaywrightVibesBrowserBackend().poll(job)

    assert update.status == "pending"
    assert update.unsigned_urls == [first.resolve().as_posix()]
    assert update.project_url == "https://vibes.ai/projects/project-1"


def test_job_checkpoint_must_stay_inside_video_job_storage(tmp_path: Path) -> None:
    output_dir = tmp_path / "storage/bridge_jobs/video"
    output_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        PlaywrightVibesBrowserBackend._job_path(outside, output_dir)


def test_bridge_job_dir_is_outside_generated_assets_layout(tmp_path: Path) -> None:
    # INC-09: o layout de assets gerados (generated_images/generated_videos)
    # não pode conter os artefatos intermediários do bridge; bridge_jobs/ é um
    # diretório separado, fora do escopo da varredura de órfãos.
    settings = Settings(_env_file=None, local_storage_path=tmp_path / "storage")

    output_dir = PlaywrightVibesBrowserBackend._bridge_job_output_dir(
        settings.local_storage_path
    )

    assert output_dir == settings.local_storage_path / "bridge_jobs" / "video"
    assert "generated" not in output_dir.parts
