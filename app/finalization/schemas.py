from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GenerateNarrationRequest(BaseModel):
    audio_track_id: UUID
    voice_profile_id: str = "narrator_default"


class SubtitleRequest(BaseModel):
    audio_track_id: UUID
    language: str = "pt-BR"


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


class SubtitleTrackRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    audio_track_id: UUID
    asset_id: UUID
    language: str
    format: str
    content: str
    safe_area: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
