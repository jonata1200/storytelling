from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerateStoryboardsRequest(BaseModel):
    script_id: UUID
    scene_number: int | None = Field(default=None, ge=1)


class StoryboardFrameRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    shot_id: UUID
    asset_id: UUID
    frame_number: int
    duration_seconds: int
    prompt: str
    narration_text: str
    dialogue_text: str
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GenerateAnimaticRequest(BaseModel):
    script_id: UUID


class AudioTrackRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    name: str
    track_type: str
    duration_seconds: int
    transcript: str
    alignment: dict

    model_config = ConfigDict(from_attributes=True)


class AnimaticRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    audio_track_id: UUID | None
    name: str
    duration_seconds: int
    manifest: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TimelineItemRead(BaseModel):
    id: UUID
    timeline_id: UUID
    project_id: UUID
    source_artifact_id: UUID
    source_asset_id: UUID | None
    layer: str
    start_ms: int
    end_ms: int
    order_index: int
    properties: dict

    model_config = ConfigDict(from_attributes=True)


class TimelineRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    animatic_id: UUID | None
    name: str
    duration_seconds: int
    profile: dict
    items: list[TimelineItemRead] = []

    model_config = ConfigDict(from_attributes=True)


class AnimaticBundleRead(BaseModel):
    audio_track: AudioTrackRead
    animatic: AnimaticRead
    timeline: TimelineRead
