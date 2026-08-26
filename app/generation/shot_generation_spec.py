from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ShotGenerationSpec(BaseModel):
    """Provider-neutral description of everything required to generate one shot."""

    shot_id: UUID
    scene_id: UUID
    scene_title: str = Field(min_length=1)
    scene_summary: str = Field(min_length=1)
    scene_context: str = ""
    continuity_state: str = ""
    duration_seconds: float = Field(gt=0)
    characters: list[str] = Field(default_factory=list)
    location: str | None = None
    props: list[str] = Field(default_factory=list)
    action: str = Field(min_length=1)
    emotion: str = Field(min_length=1)
    camera: str = ""
    lighting: str = ""
    visual_composition: str = Field(min_length=1)
    camera_movement: str = ""
    character_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    continuity: dict[str, Any] = Field(default_factory=dict)
    visual_references: list[str] = Field(default_factory=list)
    ingredient_ids: list[str] = Field(default_factory=list)
    previous_frame_reference: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_camera_movement(self) -> "ShotGenerationSpec":
        movement = (self.camera_movement or self.camera).strip()
        # Vazio é permitido: o compilador omite a linha de câmera quando não
        # há direção real (inventar "movimento curto e realista" para 100% dos
        # shots virava ruído no prompt de vídeo).
        self.camera_movement = movement
        self.camera = self.camera.strip() or movement
        return self

    @property
    def continuity_break(self) -> bool:
        return bool(self.continuity.get("continuity_break"))
