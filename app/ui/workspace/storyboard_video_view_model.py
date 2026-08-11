from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class StoryboardVideoViewModel:
    sorted_frames: list[Any]
    pending_frames: list[Any]
    clip_frame_ids: set[UUID]
    video_prompt_by_frame_id: dict[UUID, dict[str, Any]]
    frame_by_id: dict[UUID, Any]
    generated_count: int
    total_frames: int
    total_duration: int
    queued_video_jobs: int
    running_video_jobs: int
    failed_video_jobs: int


def _stale_running_video_job(job: Any, *, after_minutes: int = 10) -> bool:
    raw_status = getattr(job, "status", "")
    status = str(getattr(raw_status, "value", raw_status)).lower()
    if status != "running":
        return False
    updated_at = (
        getattr(job, "updated_at", None)
        or getattr(job, "started_at", None)
        or getattr(job, "created_at", None)
    )
    if updated_at is None:
        return False
    if getattr(updated_at, "tzinfo", None) is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated_at >= timedelta(minutes=after_minutes)


def _video_job_count_status(job: Any) -> str:
    if _stale_running_video_job(job):
        return "failed"
    raw_status = getattr(job, "status", "")
    return str(getattr(raw_status, "value", raw_status)).lower()


def build_storyboard_video_view_model(summary: dict[str, Any]) -> StoryboardVideoViewModel:
    sorted_frames = sorted(summary["frames"], key=lambda frame: frame.frame_number)
    clip_frame_ids = {clip.storyboard_frame_id for clip in summary["clips"]}
    pending_frames = [frame for frame in sorted_frames if frame.id not in clip_frame_ids]
    video_prompt_previews = list(summary.get("video_prompt_previews", []))
    video_prompt_by_frame_id = {
        preview["frame_id"]: preview
        for preview in video_prompt_previews
        if preview.get("frame_id") is not None
    }
    frame_by_id = {frame.id: frame for frame in sorted_frames}
    total_duration = sum(
        int(getattr(frame, "duration_seconds", 0) or 0) for frame in sorted_frames
    )
    video_jobs = list(summary.get("video_jobs", []))
    clip_video_jobs = [
        job
        for job in video_jobs
        if isinstance(getattr(job, "request_payload", None), dict)
        and getattr(job, "request_payload", {}).get("storyboard_frame_id")
    ]
    project_step_video_jobs = [
        job
        for job in video_jobs
        if isinstance(getattr(job, "request_payload", None), dict)
        and getattr(job, "request_payload", {}).get("step") == "video"
    ]
    counted_jobs = clip_video_jobs or video_jobs
    status_counts: dict[str, int] = {}
    for job in counted_jobs:
        status = _video_job_count_status(job)
        status_counts[status] = status_counts.get(status, 0) + 1
    active_clip_jobs = status_counts.get("pending", 0) + status_counts.get("running", 0)
    if clip_video_jobs and not active_clip_jobs:
        for job in project_step_video_jobs:
            status = _video_job_count_status(job)
            if status in {"pending", "running"}:
                status_counts[status] = status_counts.get(status, 0) + 1
    return StoryboardVideoViewModel(
        sorted_frames=sorted_frames,
        pending_frames=pending_frames,
        clip_frame_ids=clip_frame_ids,
        video_prompt_by_frame_id=video_prompt_by_frame_id,
        frame_by_id=frame_by_id,
        generated_count=len(summary["clips"]),
        total_frames=len(sorted_frames),
        total_duration=total_duration,
        queued_video_jobs=status_counts.get("pending", 0),
        running_video_jobs=status_counts.get("running", 0),
        failed_video_jobs=status_counts.get("failed", 0),
    )
