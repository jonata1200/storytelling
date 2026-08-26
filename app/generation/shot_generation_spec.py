from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ShotGenerationSpec(BaseModel):
    """Provider-neutral description of everything required to generate one shot."""

    shot_id: UUID
    scene_id: UUID
    duration_seconds: float = Field(gt=0)
    characters: list[str] = Field(default_factory=list)
    location: str | None = None
    props: list[str] = Field(default_factory=list)
    action: str = ""
    emotion: str = ""
    camera: str = ""
    lighting: str = ""
    continuity: dict[str, Any] = Field(default_factory=dict)
    visual_references: list[str] = Field(default_factory=list)
    previous_frame_reference: str | None = None
