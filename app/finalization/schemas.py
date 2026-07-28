from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FinalTimelineRequest(BaseModel):
    animatic_id: UUID | None = None


class ExportRequest(BaseModel):
    timeline_id: UUID
    subtitle_track_id: UUID | None = None
    embed_subtitles: bool = True
    fps: int = 30
    bitrate: str = "8M"
    resolution: str = "1080x1920"
    video_codec: str = "h264"
    audio_codec: str = "aac"


class ExportRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    timeline_id: UUID
    subtitle_track_id: UUID | None
    asset_id: UUID
    status: str
    profile: dict
    duration_seconds: int
    output_uri: str
    render_log: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
