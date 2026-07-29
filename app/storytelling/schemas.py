from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BriefingCreate(BaseModel):
    theme: str = Field(min_length=1, max_length=220)
    audience: str = Field(min_length=1, max_length=220)
    genre: str = Field(min_length=1, max_length=120)
    primary_emotion: str = Field(min_length=1, max_length=120)
    emotional_intensity: int = Field(ge=1, le=10)
    ending_type: str = Field(min_length=1, max_length=120)
    language: str = Field(default="pt-BR", min_length=2, max_length=16)
    country_context: str = Field(default="Brasil", min_length=1, max_length=120)
    desired_duration_minutes: Decimal = Field(ge=Decimal("5.0"), le=Decimal("25.0"))
    has_narrator: bool = True
    visual_style: str = Field(min_length=1, max_length=220)
    content_objective: str = Field(min_length=1, max_length=220)
    call_to_action: str | None = Field(default=None, max_length=220)
    constraints: list[str] = Field(default_factory=list)


class BriefingRead(BriefingCreate):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StoryIdeaRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    title: str
    hook: str
    premise: str
    protagonist: str
    retention_potential: int
    cliche_risk: int
    production_complexity: int
    payload: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StoryIdeaSearchRead(BaseModel):
    items: list[StoryIdeaRead]
    total: int
    limit: int
    offset: int


class GenerateScriptRequest(BaseModel):
    story_idea_id: UUID


class ScriptRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    story_idea_id: UUID
    title: str
    language: str
    target_duration_seconds: int
    word_count: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GenerateScenesRequest(BaseModel):
    script_id: UUID


class ShotRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    scene_id: UUID
    shot_number: int
    duration_seconds: int
    narration_text: str
    dialogue_text: str
    action: str
    emotion: str
    visual_composition: str
    camera_movement: str
    generation_type: str
    payload: dict

    model_config = ConfigDict(from_attributes=True)


class SceneRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_id: UUID
    script_id: UUID
    scene_number: int
    title: str
    summary: str
    duration_seconds: int
    payload: dict
    shots: list[ShotRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
