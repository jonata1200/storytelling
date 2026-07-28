import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storytelling.models import Scene, Shot
from app.visual_bible.models import Character, Location, Prop, VisualReference


def _prompt_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compact_prompt_value(value: object, max_length: int = 140) -> str:
    if isinstance(value, list):
        text = ", ".join(_compact_prompt_value(item, max_length) for item in value)
    elif isinstance(value, dict):
        text = "; ".join(
            f"{key}: {_compact_prompt_value(item, max_length)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    else:
        text = str(value or "").strip()
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def _visual_context_items(items: list[Character] | list[Location] | list[Prop]) -> list[dict]:
    compacted: list[dict] = []
    for item in items[:8]:
        profile = item.canonical_profile or {}
        compacted.append(
            {
                "id": str(item.id),
                "name": item.name,
                "role": getattr(item, "role", ""),
                "description": getattr(item, "description", ""),
                "narrative_importance": getattr(item, "narrative_importance", ""),
                "profile": {
                    key: _compact_prompt_value(profile.get(key))
                    for key in (
                        "hair",
                        "base_outfit",
                        "palette",
                        "lighting",
                        "layout",
                        "material",
                        "color",
                    )
                    if profile.get(key) not in (None, "", [], {})
                },
            }
        )
    return compacted


async def _storyboard_visual_context(session: AsyncSession, project_id: UUID) -> dict:
    character_rows = await session.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    )
    location_rows = await session.execute(
        select(Location).where(Location.project_id == project_id).order_by(Location.created_at)
    )
    prop_rows = await session.execute(
        select(Prop).where(Prop.project_id == project_id).order_by(Prop.created_at)
    )
    reference_rows = await session.execute(
        select(VisualReference).where(VisualReference.project_id == project_id)
    )
    reference_views: dict[str, list[str]] = {}
    for reference in reference_rows.scalars():
        key = f"{reference.target_kind}:{reference.target_id}"
        reference_views.setdefault(key, []).append(reference.view_type)

    context = {
        "characters": _visual_context_items(list(character_rows.scalars())),
        "locations": _visual_context_items(list(location_rows.scalars())),
        "props": _visual_context_items(list(prop_rows.scalars())),
        "reference_views": reference_views,
    }
    return context


def _storyboard_visual_context_text(visual_context: dict | None) -> str:
    if not visual_context:
        return ""
    sections: list[str] = []
    for label, key in (
        ("Personagens", "characters"),
        ("Locais", "locations"),
        ("Objetos", "props"),
    ):
        items = visual_context.get(key)
        if not isinstance(items, list) or not items:
            continue
        descriptions = []
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            raw_profile = item.get("profile")
            profile: dict = raw_profile if isinstance(raw_profile, dict) else {}
            details = ", ".join(
                str(value) for value in profile.values() if str(value or "").strip()
            )
            name = str(item.get("name") or "").strip()
            role = str(
                item.get("role")
                or item.get("description")
                or item.get("narrative_importance")
                or ""
            ).strip()
            descriptions.append(f"- {'; '.join(part for part in (name, role, details) if part)}")
        if descriptions:
            sections.append(f"{label}:\n" + "\n".join(descriptions))
    if not sections:
        return ""
    return "\n\nBiblioteca visual canonica - autoridade de continuidade:\n" + "\n\n".join(sections)


def _storyboard_prompt(shot: Shot, scene: Scene, visual_context: dict | None = None) -> str:
    visual_context_text = _storyboard_visual_context_text(visual_context)
    return (
        "Storyboard frame cinematográfico para video vertical 9:16.\n"
        f"Cena {scene.scene_number}, plano {shot.shot_number}.\n\n"
        f"Acao principal do plano: {shot.action}.\n"
        f"Emocao dominante: {shot.emotion}.\n"
        f"Composicao planejada: {shot.visual_composition}.\n"
        f"Movimento de camera previsto: {shot.camera_movement}.\n\n"
        "Crie um único quadro de storyboard que funcione como primeiro frame util "
        "para image-to-video. O quadro deve mostrar o instante inicial mais claro "
        "e filmavel da acao, com sujeito principal legivel, silhueta reconhecivel, "
        "ambiente coerente, profundidade espacial e direcao de movimento compreensivel.\n\n"
        "Regras visuais obrigatorias:\n"
        "- formato vertical 9:16\n"
        "- composicao cinematografica, clara e sem poluicao visual\n"
        "- continuidade rigorosa de rosto, idade, figurino, objetos, paleta, luz e ambiente\n"
        "- nenhum texto, legenda, marca d'agua, baloes, UI ou anotacao dentro da imagem\n"
        "- não criar montagem, colagem, split screen ou multiplas cenas no mesmo quadro\n"
        "- não adicionar personagens, objetos ou locais que não estejam no plano\n"
        "- não mudar o gênero visual definido pelos ativos canonicos\n"
        "- deixar espaco visual suficiente para movimento curto de camera ou personagem"
        f"{visual_context_text}"
    )


def _storyboard_frame_payload(
    scene: Scene,
    shot: Shot,
    asset_id: UUID,
    prompt: str,
) -> dict:
    return {
        "scene_number": scene.scene_number,
        "shot_number": shot.shot_number,
        "shot_id": str(shot.id),
        "asset_id": str(asset_id),
        "duration_seconds": shot.duration_seconds,
        "prompt": prompt,
        "prompt_hash": _prompt_hash(prompt),
        "frame_fingerprint": _prompt_hash(
            json.dumps(
                {
                    "shot_id": str(shot.id),
                    "duration_seconds": shot.duration_seconds,
                    "narration_text": shot.narration_text,
                    "dialogue_text": shot.dialogue_text,
                    "prompt": prompt,
                },
                sort_keys=True,
                ensure_ascii=True,
            )
        ),
    }


def _storyboard_prompt_approval_map(metadata: dict, script_id: UUID) -> dict[str, str]:
    raw_store = metadata.get("storyboard_prompt_approvals")
    store = raw_store if isinstance(raw_store, dict) else {}
    raw_script_store = store.get(str(script_id))
    script_store = raw_script_store if isinstance(raw_script_store, dict) else {}
    return {str(key): str(value) for key, value in script_store.items()}


def _storyboard_prompt_override_map(metadata: dict, script_id: UUID) -> dict[str, str]:
    raw_store = metadata.get("storyboard_prompt_overrides")
    store = raw_store if isinstance(raw_store, dict) else {}
    raw_script_store = store.get(str(script_id))
    script_store = raw_script_store if isinstance(raw_script_store, dict) else {}
    return {
        str(key): str(value)
        for key, value in script_store.items()
        if str(value or "").strip()
    }


def _storyboard_prompt_override(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
) -> str | None:
    overrides = _storyboard_prompt_override_map(metadata, script_id)
    prompt = overrides.get(str(shot_id))
    return prompt if prompt else None


def _storyboard_effective_prompt(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
    default_prompt: str,
) -> str:
    return _storyboard_prompt_override(metadata, script_id, shot_id) or default_prompt


def _storyboard_prompt_is_approved(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
    prompt_hash: str,
) -> bool:
    approvals = _storyboard_prompt_approval_map(metadata, script_id)
    return approvals.get(str(shot_id)) == prompt_hash


def _remove_storyboard_prompt_approval(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
) -> dict:
    updated = dict(metadata or {})
    raw_store = updated.get("storyboard_prompt_approvals")
    store = dict(raw_store) if isinstance(raw_store, dict) else {}
    script_key = str(script_id)
    raw_script_store = store.get(script_key)
    script_store = dict(raw_script_store) if isinstance(raw_script_store, dict) else {}
    script_store.pop(str(shot_id), None)
    if script_store:
        store[script_key] = script_store
    else:
        store.pop(script_key, None)
    updated["storyboard_prompt_approvals"] = store
    return updated


def _store_storyboard_prompt_approval(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
    prompt_hash: str,
) -> dict:
    updated = dict(metadata or {})
    raw_store = updated.get("storyboard_prompt_approvals")
    store = dict(raw_store) if isinstance(raw_store, dict) else {}
    script_key = str(script_id)
    raw_script_store = store.get(script_key)
    script_store = dict(raw_script_store) if isinstance(raw_script_store, dict) else {}
    script_store[str(shot_id)] = prompt_hash
    store[script_key] = script_store
    updated["storyboard_prompt_approvals"] = store
    return updated


def _store_storyboard_prompt_override(
    metadata: dict,
    script_id: UUID,
    shot_id: UUID,
    prompt: str,
) -> dict:
    updated = _remove_storyboard_prompt_approval(metadata, script_id, shot_id)
    raw_store = updated.get("storyboard_prompt_overrides")
    store = dict(raw_store) if isinstance(raw_store, dict) else {}
    script_key = str(script_id)
    raw_script_store = store.get(script_key)
    script_store = dict(raw_script_store) if isinstance(raw_script_store, dict) else {}
    script_store[str(shot_id)] = prompt.strip()
    store[script_key] = script_store
    updated["storyboard_prompt_overrides"] = store
    return updated
