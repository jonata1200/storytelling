import hashlib
from datetime import UTC, datetime

from app.visual_bible.models import VisualReference


def reference_fingerprint(reference: VisualReference) -> str:
    material = ":".join(
        [str(reference.id), str(reference.asset_id), reference.prompt, reference.view_type]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def mark_ingredient_synced(
    reference: VisualReference,
    *,
    ingredient_id: str,
    ingredient_type: str,
) -> bool:
    """Persiste sincronização idempotente ligada à versão exata da referência."""
    if reference.status != "approved":
        raise ValueError("Somente referências aprovadas podem virar ingredients")
    normalized_id = ingredient_id.strip()
    normalized_type = ingredient_type.strip()
    if not normalized_id or not normalized_type:
        raise ValueError("ingredient_id e ingredient_type são obrigatórios")
    fingerprint = reference_fingerprint(reference)
    metadata = dict(reference.metadata_json or {})
    current = dict(metadata.get("vibes") or {})
    if (
        current.get("ingredient_id") == normalized_id
        and current.get("ingredient_type") == normalized_type
        and current.get("reference_fingerprint") == fingerprint
        and current.get("sync_status") == "synced"
    ):
        return False
    history = list(current.get("history") or [])
    if current.get("ingredient_id") and current.get("ingredient_id") != normalized_id:
        history.append(
            {
                "ingredient_id": current["ingredient_id"],
                "ingredient_type": current.get("ingredient_type"),
                "reference_fingerprint": current.get("reference_fingerprint"),
                "replaced_at": datetime.now(UTC).isoformat(),
            }
        )
    metadata["vibes"] = {
        "ingredient_id": normalized_id,
        "ingredient_type": normalized_type,
        "reference_fingerprint": fingerprint,
        "synced_at": datetime.now(UTC).isoformat(),
        "sync_status": "synced",
        "history": history,
    }
    reference.metadata_json = metadata
    return True
