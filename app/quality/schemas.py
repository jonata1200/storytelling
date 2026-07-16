from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContinuityStateRead(BaseModel):
    id: UUID
    project_id: UUID
    shot_id: UUID | None
    source_artifact_id: UUID
    previous_state_id: UUID | None
    scene_number: int | None
    shot_number: int | None
    state: dict
    accepted: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinuityIssueRead(BaseModel):
    id: UUID
    project_id: UUID
    continuity_state_id: UUID | None
    source_artifact_id: UUID | None
    issue_code: str
    severity: str
    message: str
    expected: dict
    actual: dict
    accepted: bool
    accepted_reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinuityBuildRead(BaseModel):
    states: list[ContinuityStateRead]
    issues: list[ContinuityIssueRead]


class AcceptContinuityIssueRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class QualityCheckRead(BaseModel):
    id: UUID
    project_id: UUID
    check_type: str
    status: str
    score: int
    summary: str
    metrics: dict
    started_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SecurityScanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class SecurityScanRead(BaseModel):
    prompt_injection_detected: bool
    secret_detected: bool
    findings: list[str]
    redacted_preview: str


class ObservabilitySummaryRead(BaseModel):
    project_id: UUID
    project_status: str
    generation_jobs: dict[str, int]
    quality_checks: int
    open_continuity_issues: int
    stale_artifacts: int
    latest_quality_score: int | None
    cost_total_usd: str
