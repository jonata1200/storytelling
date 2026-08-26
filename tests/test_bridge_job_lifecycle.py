import json
import time
from pathlib import Path

from app.storage import bridge_job_lifecycle as lifecycle


def _job_name(prefix: str) -> str:
    hexchar = {"p": "a", "r": "b", "c": "c", "f": "d"}[prefix]
    return f"{hexchar * 8}-1111-2222-3333-444444444444"


def _make_job_dir(root: Path, prefix: str, status: str | None, age_days: float = 0) -> Path:
    job_id = _job_name(prefix)
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = job_dir / "job-state.json"
    payload = {"jobId": job_id, "status": status} if status else {"jobId": job_id}
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    stale = time.time() - age_days * 86400
    os_utime(checkpoint, stale)
    (job_dir / "result-1.mp4").write_bytes(b"video")
    return job_dir


def os_utime(path: Path, stamp: float) -> None:
    import os

    os.utime(path, (stamp, stamp))


def test_prune_removes_expired_terminal_jobs_and_keeps_pending(tmp_path: Path) -> None:
    root = tmp_path / "bridge_jobs" / "video"
    finished = _make_job_dir(root, "f", "completed", 8)
    pending = _make_job_dir(root, "p", "pending", 30)
    recent_done = _make_job_dir(root, "r", "failed", 9)
    inside_retention = _make_job_dir(root, "c", "failed", 2)

    dry = lifecycle.prune_finished_bridge_jobs(root, dry_run=True)
    # Dry run apenas lista; nada é apagado.
    assert finished.is_dir()
    assert pending.is_dir()
    assert recent_done.is_dir()
    assert inside_retention.is_dir()
    assert sorted(dry.removed_job_dirs) == sorted([finished.name, recent_done.name])

    effective = lifecycle.prune_finished_bridge_jobs(root, dry_run=False)

    assert sorted(effective.removed_job_dirs) == sorted([finished.name, recent_done.name])
    assert effective.kept_pending_jobs == 1
    assert not finished.exists()
    assert pending.is_dir()
    assert not recent_done.exists()
    # Job terminal dentro da janela de retenção (2 dias < 7) permanece.
    assert inside_retention.is_dir()
    assert effective.removed_bytes > 0


def test_prune_ignores_non_job_directories(tmp_path: Path) -> None:
    root = tmp_path / "bridge_jobs" / "video"
    stray = root / "not-a-job-dir"
    stray.mkdir(parents=True)
    (stray / "job-state.json").write_text('{"status": "completed"}', encoding="utf-8")

    report = lifecycle.prune_finished_bridge_jobs(root, dry_run=False)

    assert report.removed_job_dirs == []
    assert stray.is_dir()


def test_prune_qa_frames_removes_segment_dir(tmp_path: Path) -> None:
    video = tmp_path / "generated_videos" / "proj" / "vibes-x.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    frame_dir = video.parent / ".qa" / "seg-1"
    frame_dir.mkdir(parents=True)
    (frame_dir / "qa-01.jpg").write_bytes(b"jpeg")

    report = lifecycle.prune_qa_frame_dirs(video, "seg-1", dry_run=False)

    assert report.removed_qa_dirs == [str(frame_dir)]
    assert not frame_dir.exists()
    assert video.is_file()


def test_prune_old_diagnostics_keeps_most_recent(tmp_path: Path) -> None:
    root = tmp_path / "bridge_jobs" / "video"
    for index in range(25):
        path = root / f"job-{index}"
        path.mkdir(parents=True)
        diag = path / f"meta-timeout-{index}.png"
        diag.write_bytes(b"png")
        stamp = time.time() - (25 - index) * 60
        os_utime(diag, stamp)

    report = lifecycle.prune_old_diagnostics([root], keep_recent=20, dry_run=False)

    assert len(report.removed_diagnostics) == 5
    assert len(list(root.rglob("meta-timeout-*.png"))) == 20


def test_checkpoint_corrupto_nao_e_tratado_como_terminal(tmp_path: Path) -> None:
    root = tmp_path / "bridge_jobs" / "video"
    job_dir = root / _job_name("c")
    job_dir.mkdir(parents=True)
    checkpoint = job_dir / "job-state.json"
    checkpoint.write_text("{broken", encoding="utf-8")
    os_utime(checkpoint, time.time() - 30 * 86400)

    report = lifecycle.prune_finished_bridge_jobs(root, dry_run=False)

    assert report.removed_job_dirs == []
    assert job_dir.is_dir()