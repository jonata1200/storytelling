from app.storytelling.models import Briefing, StoryIdea


def _canonical_character_name(value: object, fallback: str = "Protagonista") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    name = text.split(",", 1)[0].split(";", 1)[0].split("(", 1)[0].strip()
    return name or fallback


def _compact_named_items(items: object, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(items, list):
        return []
    compacted: list[dict] = []
    for item in items[:8]:
        if isinstance(item, dict):
            compacted.append(
                {
                    key: item[key]
                    for key in keys
                    if key in item and item[key] not in (None, "", [], {})
                }
            )
        elif str(item).strip():
            compacted.append({"name": str(item).strip()})
    return compacted


def _story_bible_script_contract(story_bible_payload: dict) -> dict:
    return {
        "title": story_bible_payload.get("title"),
        "logline": story_bible_payload.get("logline"),
        "theme": story_bible_payload.get("theme"),
        "genre": story_bible_payload.get("genre"),
        "tone": story_bible_payload.get("tone"),
        "target_emotion": story_bible_payload.get("target_emotion"),
        "story_engine": story_bible_payload.get("story_engine"),
        "characters": _compact_named_items(
            story_bible_payload.get("characters"),
            ("id", "name", "role", "desire", "fear", "secret", "arc", "base_outfit"),
        ),
        "locations": _compact_named_items(
            story_bible_payload.get("locations"),
            ("id", "name", "description", "layout", "lighting", "props_in_scene"),
        ),
        "props": _compact_named_items(
            story_bible_payload.get("props"),
            ("id", "name", "owner", "narrative_importance", "first_appearance"),
        ),
        "narrative_rules": story_bible_payload.get("narrative_rules"),
        "continuity_rules": story_bible_payload.get("continuity_rules"),
        "forbidden_elements": story_bible_payload.get("forbidden_elements"),
        "visual_style": story_bible_payload.get("visual_style"),
        "audio_style": story_bible_payload.get("audio_style"),
    }


def _story_bible_visual_contract(story_bible_payload: dict) -> dict:
    return {
        "visual_style": story_bible_payload.get("visual_style"),
        "characters": _compact_named_items(
            story_bible_payload.get("characters"),
            (
                "id",
                "name",
                "role",
                "apparent_age",
                "gender",
                "height_cm",
                "body_type",
                "face_shape",
                "skin_tone",
                "eyes",
                "hair",
                "base_outfit",
                "palette",
            ),
        ),
        "locations": _compact_named_items(
            story_bible_payload.get("locations"),
            (
                "id",
                "name",
                "description",
                "layout",
                "materials",
                "palette",
                "lighting",
                "spatial_rules",
                "forbidden_elements",
            ),
        ),
        "props": _compact_named_items(
            story_bible_payload.get("props"),
            (
                "id",
                "name",
                "dimensions",
                "material",
                "color",
                "state",
                "owner",
                "visual_rules",
            ),
        ),
        "continuity_rules": story_bible_payload.get("continuity_rules"),
    }


def _idea_script_contract(idea: StoryIdea, briefing: Briefing) -> dict:
    payload = idea.payload or {}
    protagonist_name = _canonical_character_name(idea.protagonist)
    return {
        "title": idea.title,
        "logline": payload.get("premise") or idea.premise,
        "theme": payload.get("theme") or briefing.theme,
        "genre": payload.get("genre") or briefing.genre,
        "tone": payload.get("tone") or "cinematográfico e emocional",
        "target_emotion": payload.get("primary_emotion") or briefing.primary_emotion,
        "audience": briefing.audience,
        "story_engine": {
            "dramatic_question": payload.get("dramatic_question")
            or payload.get("conflict")
            or "Qual escolha emocional define a historia?",
            "central_conflict": payload.get("conflict") or idea.premise,
            "emotional_promise": payload.get("payoff") or idea.hook,
            "inciting_incident": payload.get("hook") or idea.hook,
            "midpoint_turn": payload.get("twist") or payload.get("obstacles"),
            "climax": payload.get("climax"),
            "ending_image": payload.get("resolution") or payload.get("payoff"),
        },
        "characters": [
            {
                "name": protagonist_name,
                "role": "protagonista",
                "description": idea.protagonist,
                "desire": payload.get("protagonist_desire") or payload.get("stakes"),
                "fear": payload.get("fear") or payload.get("obstacles"),
                "arc": payload.get("emotional_need") or payload.get("resolution"),
            }
        ],
        "dialogue_rules": [
            "linhas de fala devem usar somente nomes de personagens, nunca nomes de locais",
            "sluglines descrevem locais; blocos de dialogo identificam pessoas",
            f"usar {protagonist_name.upper()} como cue de dialogo da protagonista",
        ],
        "locations": payload.get("locations") or payload.get("locais") or [],
        "props": payload.get("props") or payload.get("objetos") or [],
        "narrative_rules": [
            "gancho visual imediato",
            "microviradas ao longo das cenas",
            "cada cena deve ter desejo, obstaculo e mudanca emocional observavel",
            "dialogos devem revelar subtexto e escolha, nao explicar a trama",
            "payoff emocional claro",
        ],
        "continuity_rules": [
            "manter continuidade de personagens, locais e objetos extraidos do roteiro"
        ],
        "forbidden_elements": briefing.constraints,
        "visual_style": briefing.visual_style,
        "audio_style": {"description": "audio discreto a servico da emocao"},
    }


def expected_script_scene_count(target_duration_seconds: int) -> int:
    target_minutes = max(1, target_duration_seconds / 60)
    return max(5, min(24, int(round(target_minutes * 0.8))))
