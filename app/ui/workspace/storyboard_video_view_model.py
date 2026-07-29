from dataclasses import dataclass
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
    return StoryboardVideoViewModel(
        sorted_frames=sorted_frames,
        pending_frames=pending_frames,
        clip_frame_ids=clip_frame_ids,
        video_prompt_by_frame_id=video_prompt_by_frame_id,
        frame_by_id=frame_by_id,
        generated_count=len(summary["clips"]),
        total_frames=len(sorted_frames),
        total_duration=total_duration,
    )
