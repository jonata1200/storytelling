from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TargetKind = Literal["character", "location", "prop"]


class PlannedVisualReference(BaseModel):
    view_type: str
    prompt: str
    reference_role: str
    priority: int = Field(ge=1, le=100)


class VisualReferencePlan(BaseModel):
    target_kind: TargetKind
    target_id: UUID
    items: list[PlannedVisualReference]


CHARACTER_PRIMARY_VIEWS = (
    ("front", "vista frontal, expressão neutra", 100),
    ("three_quarter", "vista em três quartos", 95),
    ("profile", "vista de perfil", 80),
    ("full_body", "corpo inteiro, postura natural", 90),
    ("neutral_expression", "retrato de expressão neutra", 85),
)
CHARACTER_SECONDARY_VIEWS = CHARACTER_PRIMARY_VIEWS[:3]
LOCATION_BASE_VIEWS = (
    ("establishing", "plano geral de estabelecimento", 100),
    ("main_angle", "ângulo principal usado na narrativa", 90),
)


def plan_visual_references(
    target_kind: TargetKind,
    target_id: UUID,
    canonical_profile: dict,
    *,
    shot_payloads: list[dict] | None = None,
) -> VisualReferencePlan:
    shots = shot_payloads or []
    canonical_prompt = str(canonical_profile.get("canonical_prompt") or "").strip()
    if not canonical_prompt:
        raise ValueError("Perfil canônico sem canonical_prompt")

    views: list[tuple[str, str, int]]
    if target_kind == "character":
        role = str(canonical_profile.get("role") or "").casefold()
        importance = str(canonical_profile.get("importance") or "").casefold()
        primary = "protagon" in role or importance in {"main", "primary", "alta", "high"}
        views = list(CHARACTER_PRIMARY_VIEWS if primary else CHARACTER_SECONDARY_VIEWS)
        outfit = str(canonical_profile.get("base_outfit") or "").strip()
        if primary and outfit:
            views.append(("story_outfit", f"figurino narrativo: {outfit}", 75))
    elif target_kind == "location":
        views = list(LOCATION_BASE_VIEWS)
        shot_text = " ".join(str(item) for item in shots).casefold()
        if any(term in shot_text for term in ("reverse", "reverso", "contracampo")):
            views.append(("reverse_angle", "ângulo reverso para continuidade espacial", 75))
        lighting = str(canonical_profile.get("lighting") or "").strip()
        if lighting and shots:
            views.append(("story_lighting", f"variação de iluminação: {lighting}", 70))
    else:
        importance = str(canonical_profile.get("importance") or "").casefold()
        if importance not in {"alta", "high", "critical", "principal"}:
            return VisualReferencePlan(target_kind=target_kind, target_id=target_id, items=[])
        views = [("canonical", "vista canônica isolada do objeto", 90)]

    items = [
        PlannedVisualReference(
            view_type=view_type,
            prompt=(
                f"{canonical_prompt} {instruction}. Referência visual canônica, sem texto, "
                "sem marca d'água, fundo simples, continuidade rigorosa."
            ),
            reference_role=f"{target_kind}_{view_type}",
            priority=priority,
        )
        for view_type, instruction, priority in views
    ]
    return VisualReferencePlan(target_kind=target_kind, target_id=target_id, items=items)
