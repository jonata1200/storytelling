from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OperationalEventCreate(BaseModel):
    project_id: UUID
    artifact_id: UUID | None = None
    job_id: UUID | None = None
    event_type: str = Field(min_length=1, max_length=120)
    status: str = Field(default="info", min_length=1, max_length=40)
    actor: str | None = Field(default=None, max_length=120)
    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=180)
    operation: str | None = Field(default=None, max_length=120)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    actual_cost: Decimal | None = Field(default=None, ge=0)
    message: str = Field(default="", max_length=2000)
    details: dict = Field(default_factory=dict)


class OperationalEventRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID | None
    job_id: UUID | None
    event_type: str
    status: str
    actor: str | None
    provider: str | None
    model: str | None
    operation: str | None
    correlation_id: str | None
    estimated_cost: Decimal | None
    actual_cost: Decimal | None
    message: str
    details: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperationalBreakdownRead(BaseModel):
    key: str
    count: int = 0


class ProjectOperationalSummaryRead(BaseModel):
    project_id: UUID
    total_events: int
    failures: int
    by_status: list[OperationalBreakdownRead]
    by_event_type: list[OperationalBreakdownRead]
    latest_events: list[OperationalEventRead]


class PromptExecutionRead(BaseModel):
    id: UUID
    artifact_id: UUID | None
    task: str
    provider: str
    model: str
    duration_ms: int | None
    estimated_cost: Decimal
    status: str = "succeeded"
    created_at: datetime


class PromptExecutionTaskMetricsRead(BaseModel):
    task: str
    count: int
    average_duration_ms: int | None
    max_duration_ms: int | None
    estimated_cost: Decimal
    latest_at: datetime | None


class JobExecutionRead(BaseModel):
    id: UUID
    job_type: str
    step: str | None
    status: str
    progress: int
    attempts: int
    max_attempts: int
    provider: str
    model: str
    external_job_id: str | None
    estimated_cost: Decimal
    error: str | None
    request_payload_summary: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ProjectExecutionSummaryRead(BaseModel):
    project_id: UUID
    prompt_executions: list[PromptExecutionRead]
    prompt_metrics: list[PromptExecutionTaskMetricsRead]
    recent_jobs: list[JobExecutionRead]


class ReadinessComponentRead(BaseModel):
    name: str
    status: str
    message: str
    details: dict = Field(default_factory=dict)


class ReadinessDashboardRead(BaseModel):
    status: str
    components: list[ReadinessComponentRead]
