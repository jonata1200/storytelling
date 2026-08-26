from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TargetKind = Literal["character", "location", "prop"]

CHARACTER_META_INSTRUCTION = (
    "Mostre o personagem em pé, de corpo inteiro, com mãos e calçados visíveis, "
    "de maneira que o fundo da imagem seja um cinza claro, seu enquadramento deve ser "
    "vertical 9:16. Não inclua textos, letras, legendas, logotipos ou marcas-d'água "
    "na imagem."
)


class PlannedVisualReference(BaseModel):
    view_type: str
    prompt: str
    reference_role: str
    priority: int = Field(ge=1, le=100)


class VisualReferencePlan(BaseModel):
    target_kind: TargetKind
    target_id: UUID
    items: list[PlannedVisualReference]


CHARACTER_CANONICAL_VIEW = (
    "full_body",
    CHARACTER_META_INSTRUCTION,
    100,
)
LOCATION_BASE_VIEWS = (
    (
        "establishing",
        (
            "Mostre o ambiente inteiro em plano geral, com arquitetura, materiais, "
            "iluminação e objetos principais bem visíveis, sem pessoas"
        ),
        100,
    ),
)
VISUAL_REFERENCE_VIEW_COUNTS = {
    "characters": 1,
    "locations": len(LOCATION_BASE_VIEWS),
}


def plan_visual_references(
    target_kind: TargetKind,
    target_id: UUID,
    canonical_profile: dict,
    *,
    shot_payloads: list[dict] | None = None,
) -> VisualReferencePlan:
    _ = shot_payloads
    canonical_prompt = str(canonical_profile.get("canonical_prompt") or "").strip()
    if not canonical_prompt:
        raise ValueError("Perfil canônico sem canonical_prompt")

    views: list[tuple[str, str, int]]
    if target_kind == "character":
        views = [CHARACTER_CANONICAL_VIEW]
    elif target_kind == "location":
        views = list(LOCATION_BASE_VIEWS)
    else:
        importance = str(canonical_profile.get("importance") or "").casefold()
        if importance not in {"alta", "high", "critical", "principal"}:
            return VisualReferencePlan(target_kind=target_kind, target_id=target_id, items=[])
        views = [("canonical", "vista canônica isolada do objeto", 90)]

    items: list[PlannedVisualReference] = []
    for view_type, instruction, priority in views:
        items.append(
            PlannedVisualReference(
                view_type=view_type,
                prompt=f"{canonical_prompt} {instruction}".strip(),
                reference_role=f"{target_kind}_{view_type}",
                priority=priority,
            )
        )
    return VisualReferencePlan(target_kind=target_kind, target_id=target_id, items=items)
