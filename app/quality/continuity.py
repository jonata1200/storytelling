from app.storytelling.models import Shot

OBJECT_EXIT_WORDS = ("deixa", "entrega", "perde", "guarda", "some", "desaparece")


def build_initial_shot_state(shot: Shot, story_bible_payload: dict) -> dict:
    characters = []
    for raw_character in story_bible_payload.get("characters", []):
        characters.append(
            {
                "id": raw_character.get("id") or raw_character.get("permanent_id"),
                "name": raw_character.get("name", "Personagem"),
                "outfit": raw_character.get("base_outfit", "roupa base aprovada"),
                "hair": raw_character.get("hair", "cabelo canonico"),
                "emotion": shot.emotion,
                "position": "centro do quadro",
            }
        )

    props = [
        {
            "id": raw_prop.get("id") or raw_prop.get("permanent_id"),
            "name": raw_prop.get("name", "Objeto"),
            "location": "em cena",
        }
        for raw_prop in story_bible_payload.get("props", [])
    ]
    location = (story_bible_payload.get("locations") or [{}])[0]
    return {
        "shot_id": str(shot.id),
        "scene_id": str(shot.scene_id),
        "characters": characters,
        "carried_objects": props[:1],
        "location": {
            "id": location.get("id") or location.get("permanent_id", "loc_default"),
            "name": location.get("name", "Local principal"),
        },
        "time_of_day": "continuidade narrativa",
        "weather": "não especificado",
        "lighting": "consistente com biblia visual",
        "environment_state": "sem mudancas bruscas",
        "action": shot.action,
        "emotion": shot.emotion,
        "camera_movement": shot.camera_movement,
    }


def inherit_persistent_details(previous: dict | None, current: dict) -> dict:
    if previous is None:
        return current
    previous_characters = {
        item.get("id") or item.get("name"): item for item in previous.get("characters", [])
    }
    for character in current.get("characters", []):
        key = character.get("id") or character.get("name")
        previous_character = previous_characters.get(key)
        if previous_character is None:
            continue
        character.setdefault("outfit", previous_character.get("outfit"))
        character.setdefault("hair", previous_character.get("hair"))
    return current


def compare_continuity_states(previous: dict | None, current: dict) -> list[dict]:
    if previous is None:
        return []

    issues: list[dict] = []
    previous_characters = {
        item.get("id") or item.get("name"): item for item in previous.get("characters", [])
    }
    current_characters = {
        item.get("id") or item.get("name"): item for item in current.get("characters", [])
    }

    for key, previous_character in previous_characters.items():
        current_character = current_characters.get(key)
        if current_character is None:
            issues.append(
                {
                    "issue_code": "character_missing",
                    "severity": "warning",
                    "message": (
                        "Personagem ausente sem justificativa: "
                        f"{previous_character['name']}"
                    ),
                    "expected": {"character": previous_character},
                    "actual": {"characters": current.get("characters", [])},
                }
            )
            continue
        if previous_character.get("outfit") != current_character.get("outfit"):
            issues.append(
                {
                    "issue_code": "wardrobe_mismatch",
                    "severity": "warning",
                    "message": f"Roupa mudou sem transicao: {current_character['name']}",
                    "expected": {"outfit": previous_character.get("outfit")},
                    "actual": {"outfit": current_character.get("outfit")},
                }
            )
        if previous_character.get("hair") != current_character.get("hair"):
            issues.append(
                {
                    "issue_code": "hair_mismatch",
                    "severity": "warning",
                    "message": f"Cabelo mudou sem transicao: {current_character['name']}",
                    "expected": {"hair": previous_character.get("hair")},
                    "actual": {"hair": current_character.get("hair")},
                }
            )

    previous_objects = {
        item.get("id") or item.get("name")
        for item in previous.get("carried_objects", [])
    }
    current_objects = {
        item.get("id") or item.get("name")
        for item in current.get("carried_objects", [])
    }
    missing_objects = previous_objects - current_objects
    action = str(current.get("action", "")).lower()
    if missing_objects and not any(word in action for word in OBJECT_EXIT_WORDS):
        issues.append(
            {
                "issue_code": "object_disappeared",
                "severity": "error",
                "message": "Objeto importante desapareceu sem justificativa.",
                "expected": {"objects": sorted(missing_objects)},
                "actual": {"objects": sorted(current_objects)},
            }
        )

    return issues


def check_timeline_integrity(items: list[tuple[int, int, str]]) -> list[dict]:
    if not items:
        return []
    issues: list[dict] = []
    ordered = sorted(items, key=lambda item: item[0])
    previous_end = ordered[0][1]
    for start_ms, end_ms, layer in ordered[1:]:
        if layer != "video":
            continue
        if start_ms < previous_end:
            issues.append(
                {
                    "issue_code": "timeline_overlap",
                    "severity": "error",
                    "message": "Itens de video se sobrepoem na timeline.",
                    "expected": {"start_ms": previous_end},
                    "actual": {"start_ms": start_ms, "end_ms": end_ms},
                }
            )
        if start_ms > previous_end:
            issues.append(
                {
                    "issue_code": "timeline_gap",
                    "severity": "warning",
                    "message": "Existe uma lacuna entre itens de video.",
                    "expected": {"start_ms": previous_end},
                    "actual": {"start_ms": start_ms, "end_ms": end_ms},
                }
            )
        previous_end = max(previous_end, end_ms)
    return issues
