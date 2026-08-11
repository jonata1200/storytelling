from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ClipReviewDecision, GenerationJobStatus, GenerationJobType


class GenerateVideoClipsRequest(BaseModel):
    storyboard_frame_ids: list[UUID] | None = None
    variants_per_frame: int = Field(default=1, ge=1, le=4)
    provider: Literal["auto", "google_ai"] = "auto"
    model: str | None = None
    include_canonical_references: bool = False


class VideoCostEstimateRequest(BaseModel):
    clip_count: int = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    unit_cost_per_second: Decimal = Field(default=Decimal("0.000000"), ge=0)


class VideoCostEstimateRead(BaseModel):
    estimated: Decimal
    minimum: Decimal
    maximum: Decimal


class GenerationJobRead(BaseModel):
    id: UUID
    project_id: UUID
    source_artifact_id: UUID | None
    result_artifact_id: UUID | None
    external_job_id: str | None
    job_type: GenerationJobType
    status: GenerationJobStatus
    progress: int
    attempts: int
    max_attempts: int
    provider: str
    model: str
    idempotency_key: str
    cost_estimate: Decimal
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoClipRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    storyboard_frame_id: UUID
    asset_id: UUID
    generation_job_id: UUID
    provider: str
    model: str
    duration_seconds: int
    variant_index: int
    selected: bool
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoGenerationBatchRead(BaseModel):
    jobs: list[GenerationJobRead]
    clips: list[VideoClipRead]


class ClipReviewCreate(BaseModel):
    decision: ClipReviewDecision
    notes: str | None = None
    selected: bool = False


class ClipReviewRead(BaseModel):
    id: UUID
    video_clip_id: UUID
    decision: ClipReviewDecision
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinuousVideoPlanCreate(BaseModel):
    mode: str = "continuous_fast"
    target_duration_seconds: int = Field(default=0, ge=0)
    segment_duration_seconds: int = Field(default=7, ge=1)
    segment_count: int = Field(default=0, ge=0)
    status: str = "draft"
    metadata_json: dict = Field(default_factory=dict)


class ContinuousVideoPlanRead(BaseModel):
    id: UUID
    project_id: UUID
    mode: str
    target_duration_seconds: int
    segment_duration_seconds: int
    segment_count: int
    status: str
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinuousVideoSegmentCreate(BaseModel):
    segment_number: int = Field(ge=1)
    title: str = ""
    prompt: str
    duration_seconds: int = Field(default=7, ge=1)
    provider: str = "google_ai"
    model: str = "veo-3.1-fast-generate-preview"
    source_segment_id: UUID | None = None
    source_video_asset_id: UUID | None = None
    request_fingerprint: str | None = None
    idempotency_key: str | None = None
    cost_estimate: Decimal = Field(default=Decimal("0.000000"), ge=0)
    metadata_json: dict = Field(default_factory=dict)


class ContinuousVideoSegmentRead(BaseModel):
    id: UUID
    project_id: UUID
    segment_number: int
    title: str
    prompt: str
    duration_seconds: int
    status: GenerationJobStatus
    provider: str
    model: str
    generation_job_id: UUID | None
    asset_id: UUID | None
    source_segment_id: UUID | None
    source_video_asset_id: UUID | None
    external_operation_id: str | None
    request_fingerprint: str
    idempotency_key: str
    cost_estimate: Decimal
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinuousVideoPlanSegmentsRequest(BaseModel):
    segment_duration_seconds: int = Field(default=7, ge=1, le=12)
    provider: str = "google_ai"
    model: str = "veo-3.1-fast-generate-preview"
    replace_existing: bool = False


class ContinuousVideoSegmentPromptUpdate(BaseModel):
    prompt: str = Field(min_length=20)
    title: str | None = None


class ContinuousVideoPlanningRead(BaseModel):
    plan: ContinuousVideoPlanRead
    segments: list[ContinuousVideoSegmentRead]
    validation_errors: dict[int, list[str]] = Field(default_factory=dict)
