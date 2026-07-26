import re
from typing import cast

from app.storytelling.models import Briefing
from app.storytelling.normalization_common import GenerationOutputError, _required_str
from app.storytelling.script_contracts import (
    _story_bible_script_contract,
    _story_bible_visual_contract,
)

STORY_BIBLE_DETAIL_PREFIXES = (
    "arc_",
    "arco_",
    "palette_",
    "paleta_",
    "personality_",
    "personalidade_",
)


def _story_bible_slug(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9áéíóúâêôãõç]+", "_", text)
    text = text.strip("_")
    return text or fallback


def _story_bible_text(value: object, fallback: str = "") -> str:
    if value in (None, "", [], {}):
        return fallback
    if isinstance(value, list):
        text = ", ".join(item_text for item in value if (item_text := _story_bible_text(item)))
        return text or fallback
    if isinstance(value, dict):
        parts = [
            f"{str(key).replace('_', ' ')}: {_story_bible_text(item)}"
            for key, item in value.items()
            if _story_bible_text(item)
        ]
        return "; ".join(parts) or fallback
    return str(value).strip() or fallback


def _story_bible_string_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [_story_bible_text(item) for item in value]
    elif value in (None, "", [], {}):
        items = []
    else:
        items = [_story_bible_text(value)]
    clean_items = [item for item in items if item]
    return clean_items or fallback


def _story_bible_profile_items(value: object) -> list[dict]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        items: list[dict] = []
        for raw_item in value:
            if isinstance(raw_item, str) and raw_item.lower().startswith(
                STORY_BIBLE_DETAIL_PREFIXES
            ):
                continue
            if isinstance(raw_item, dict):
                items.append(dict(raw_item))
            elif str(raw_item).strip():
                items.append({"name": str(raw_item).strip()})
        return items
    if isinstance(value, dict):
        if any(key in value for key in ("name", "nome", "title", "titulo", "role", "funcao")):
            return [dict(value)]
        return [
            (dict(raw_item) | {"name": str(key).replace("_", " ").title()})
            if isinstance(raw_item, dict)
            else {"name": str(key).replace("_", " ").title(), "description": raw_item}
            for key, raw_item in value.items()
        ]
    return [{"name": str(value).strip()}]


def _story_bible_outfit(value: object) -> dict:
    if isinstance(value, dict):
        return {
            "main_piece": _story_bible_text(
                value.get("main_piece")
                or value.get("peca_principal")
                or value.get("peça_principal"),
                "figurino principal definido pela historia",
            ),
            "color": _story_bible_text(value.get("color") or value.get("cor"), "cor marcante"),
            "fabric": _story_bible_text(
                value.get("fabric") or value.get("tecido"), "tecido realista"
            ),
            "texture": _story_bible_text(
                value.get("texture") or value.get("textura"), "textura visivel"
            ),
            "wear_marks": _story_bible_text(
                value.get("wear_marks") or value.get("desgaste"), "marcas coerentes de uso"
            ),
            "accessories": _story_bible_string_list(
                value.get("accessories") or value.get("acessorios") or value.get("acessórios"),
                [],
            ),
        }
    text = _story_bible_text(value, "figurino principal definido pela historia")
    return {
        "main_piece": text,
        "color": "cor marcante e exclusiva",
        "fabric": "tecido realista",
        "texture": "textura visivel",
        "wear_marks": "marcas coerentes de uso",
        "accessories": [],
    }


def _normalize_story_bible_characters(payload: dict, idea_payload: dict | None) -> list[dict]:
    raw_items = (
        payload.get("characters")
        or payload.get("personagens")
        or payload.get("cast")
        or payload.get("personas")
    )
    items = _story_bible_profile_items(raw_items)
    if not items:
        protagonist = _story_bible_text((idea_payload or {}).get("protagonist"), "Protagonista")
        items = [{"name": protagonist, "role": "protagonista"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        default_name = (
            _story_bible_text((idea_payload or {}).get("protagonist"), "") if index == 1 else ""
        ) or f"Personagem {index}"
        name = _story_bible_text(
            item.get("name") or item.get("nome") or item.get("title") or item.get("titulo"),
            default_name,
        )
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"char_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "role": _story_bible_text(item.get("role") or item.get("funcao"), "personagem"),
                "apparent_age": _story_bible_text(
                    item.get("apparent_age") or item.get("idade_aparente") or item.get("idade"),
                    "idade aparente definida",
                ),
                "gender": _story_bible_text(item.get("gender") or item.get("genero"), "pessoa"),
                "origin": _story_bible_text(item.get("origin") or item.get("origem"), "brasileira"),
                "height_cm": _story_bible_text(item.get("height_cm") or item.get("altura"), "165"),
                "body_type": _story_bible_text(
                    item.get("body_type") or item.get("tipo_fisico") or item.get("corpo"),
                    "porte fisico coerente com a historia",
                ),
                "face_shape": _story_bible_text(
                    item.get("face_shape") or item.get("formato_rosto") or item.get("rosto"),
                    "rosto memoravel",
                ),
                "skin_tone": _story_bible_text(
                    item.get("skin_tone") or item.get("tom_de_pele") or item.get("pele"),
                    "tom de pele natural",
                ),
                "eyes": _story_bible_text(
                    item.get("eyes") or item.get("olhos"), "olhos expressivos"
                ),
                "hair": _story_bible_text(
                    item.get("hair") or item.get("cabelo"), "cabelo consistente com o perfil"
                ),
                "base_outfit": _story_bible_outfit(
                    item.get("base_outfit") or item.get("figurino_base") or item.get("figurino")
                ),
                "palette": _story_bible_string_list(
                    item.get("palette") or item.get("paleta"),
                    ["cor principal", "cor secundaria", "neutro de apoio"],
                ),
                "personality": _story_bible_text(
                    item.get("personality") or item.get("personalidade"),
                    "personalidade especifica",
                ),
                "desire": _story_bible_text(
                    item.get("desire") or item.get("desejo"), "desejo claro"
                ),
                "fear": _story_bible_text(item.get("fear") or item.get("medo"), "medo interno"),
                "secret": _story_bible_text(item.get("secret") or item.get("segredo"), ""),
                "arc": _story_bible_text(
                    item.get("arc") or item.get("arco"), "arco emocional claro"
                ),
            }
        )
    return normalized


def _normalize_story_bible_locations(payload: dict) -> list[dict]:
    items = _story_bible_profile_items(
        payload.get("locations")
        or payload.get("locais")
        or payload.get("lugares")
        or payload.get("cenarios")
        or payload.get("cenários")
    )
    if not items:
        items = [{"name": "Local principal", "description": "ambiente central da historia"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        name = _story_bible_text(item.get("name") or item.get("nome"), f"Local {index}")
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"loc_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "description": _story_bible_text(
                    item.get("description") or item.get("descricao") or item.get("mood"),
                    "local importante para a historia",
                ),
                "layout": _story_bible_text(
                    item.get("layout") or item.get("planta"), "layout definido"
                ),
                "materials": _story_bible_string_list(
                    item.get("materials") or item.get("materiais"),
                    ["paredes", "piso", "objetos de cena"],
                ),
                "palette": _story_bible_string_list(
                    item.get("palette") or item.get("paleta"),
                    ["neutros", "cor de destaque", "sombra suave"],
                ),
                "lighting": _story_bible_text(
                    item.get("lighting") or item.get("iluminacao") or item.get("luz"),
                    "iluminacao cinematografica coerente",
                ),
                "props_in_scene": _story_bible_string_list(item.get("props_in_scene"), []),
                "spatial_rules": _story_bible_string_list(
                    item.get("spatial_rules"), ["manter geografia consistente"]
                ),
                "forbidden_elements": _story_bible_string_list(
                    item.get("forbidden_elements"), ["pessoas", "multidoes", "silhuetas humanas"]
                ),
            }
        )
    return normalized


def _normalize_story_bible_props(payload: dict) -> list[dict]:
    items = _story_bible_profile_items(
        payload.get("props")
        or payload.get("objetos")
        or payload.get("objects")
        or payload.get("itens")
        or payload.get("items")
    )
    if not items:
        items = [{"name": "Objeto de revelacao", "narrative_importance": "payoff narrativo"}]
    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        name = _story_bible_text(item.get("name") or item.get("nome"), f"Objeto {index}")
        normalized.append(
            {
                "id": _story_bible_text(
                    item.get("id"), f"prop_{_story_bible_slug(name, str(index))}"
                ),
                "name": name,
                "dimensions": _story_bible_text(
                    item.get("dimensions") or item.get("dimensoes") or item.get("tamanho"),
                    "escala definida",
                ),
                "material": _story_bible_text(item.get("material"), "material reconhecivel"),
                "color": _story_bible_text(item.get("color") or item.get("cor"), "cor definida"),
                "state": _story_bible_text(
                    item.get("state") or item.get("estado"), "estado definido"
                ),
                "owner": _story_bible_text(
                    item.get("owner") or item.get("dono"), "personagem ligado ao objeto"
                ),
                "narrative_importance": _story_bible_text(
                    item.get("narrative_importance") or item.get("importance"),
                    "objeto com funcao narrativa clara",
                ),
                "first_appearance": _story_bible_text(item.get("first_appearance"), "primeiro ato"),
                "visual_rules": _story_bible_string_list(
                    item.get("visual_rules"), ["aparecer isolado e reconhecivel"]
                ),
            }
        )
    return normalized


STORY_BIBLE_DEFAULT_MARKERS = {
    "",
    "desejo claro",
    "arco emocional claro",
    "figurino principal definido pela historia",
    "local importante para a historia",
    "ambiente central da historia",
    "layout definido",
    "iluminacao cinematografica coerente",
    "objeto com funcao narrativa clara",
    "Objeto de revelacao",
    "Qual escolha emocional define a historia?",
    "realismo emocional",
    "manter continuidade de figurino e objetos",
}


def _story_bible_meaningful_text(value: object) -> bool:
    text = _story_bible_text(value).strip()
    return bool(text and text not in STORY_BIBLE_DEFAULT_MARKERS)


def story_bible_quality_report(payload: dict) -> dict:
    missing_fields: list[str] = []
    risk_flags: list[str] = []
    checks: list[bool] = []

    raw_characters = payload.get("characters")
    raw_locations = payload.get("locations")
    raw_props = payload.get("props")
    raw_story_engine = payload.get("story_engine")
    raw_continuity_rules = payload.get("continuity_rules")
    characters = cast(list, raw_characters) if isinstance(raw_characters, list) else []
    locations = cast(list, raw_locations) if isinstance(raw_locations, list) else []
    props = cast(list, raw_props) if isinstance(raw_props, list) else []
    story_engine = cast(dict, raw_story_engine) if isinstance(raw_story_engine, dict) else {}
    continuity_rules = (
        cast(list, raw_continuity_rules) if isinstance(raw_continuity_rules, list) else []
    )

    character_ready = bool(characters) and any(
        isinstance(character, dict)
        and _story_bible_meaningful_text(character.get("name"))
        and _story_bible_meaningful_text(character.get("role"))
        and _story_bible_meaningful_text(character.get("desire"))
        and _story_bible_meaningful_text(character.get("arc"))
        and isinstance(character.get("base_outfit"), dict)
        and _story_bible_meaningful_text(character["base_outfit"].get("main_piece"))
        for character in characters
    )
    checks.append(character_ready)
    if not character_ready:
        missing_fields.append("characters[].name/role/desire/arc/base_outfit")

    location_ready = bool(locations) and any(
        isinstance(location, dict)
        and _story_bible_meaningful_text(location.get("name"))
        and _story_bible_meaningful_text(location.get("description"))
        and _story_bible_meaningful_text(location.get("lighting"))
        for location in locations
    )
    checks.append(location_ready)
    if not location_ready:
        missing_fields.append("locations[].name/description/lighting")

    prop_ready = bool(props) and any(
        isinstance(prop, dict)
        and _story_bible_meaningful_text(prop.get("name"))
        and _story_bible_meaningful_text(prop.get("narrative_importance"))
        for prop in props
    )
    checks.append(prop_ready)
    if not prop_ready:
        missing_fields.append("props[].name/narrative_importance")

    required_engine_keys = ("inciting_incident", "midpoint_turn", "climax", "ending_image")
    missing_engine = [
        key
        for key in required_engine_keys
        if not _story_bible_meaningful_text(story_engine.get(key))
    ]
    engine_ready = not missing_engine
    checks.append(engine_ready)
    if not engine_ready:
        missing_fields.extend(f"story_engine.{key}" for key in missing_engine)

    continuity_ready = bool(continuity_rules) and any(
        _story_bible_meaningful_text(rule) for rule in continuity_rules
    )
    checks.append(continuity_ready)
    if not continuity_ready:
        missing_fields.append("continuity_rules")

    visual_contract_ready = bool(payload.get("visual_contract"))
    checks.append(visual_contract_ready)
    if not visual_contract_ready:
        risk_flags.append("visual_contract ausente")

    script_contract_ready = bool(payload.get("script_contract"))
    checks.append(script_contract_ready)
    if not script_contract_ready:
        risk_flags.append("script_contract ausente")

    score = int(round((sum(1 for check in checks if check) / len(checks)) * 100))
    if score < 80:
        risk_flags.append("Story Bible incompleta para roteiro e producao visual")
    return {
        "completeness_score": score,
        "missing_fields": missing_fields,
        "risk_flags": risk_flags,
    }


def story_bible_validation_errors(payload: dict) -> list[str]:
    report = story_bible_quality_report(payload)
    errors = list(report["missing_fields"])
    if int(report["completeness_score"]) < 80:
        errors.append(f"completeness_score abaixo de 80 ({report['completeness_score']})")
    return errors


def validate_story_bible_payload(payload: dict, context: str) -> None:
    errors = story_bible_validation_errors(payload)
    if errors:
        raise GenerationOutputError(f"{context}: Story Bible incompleta ({'; '.join(errors)})")


def normalize_story_bible_payload(
    payload: dict,
    idea_payload: dict | None = None,
    briefing: Briefing | None = None,
) -> dict:
    title = _required_str(payload, "title", "generate_story_bible")
    logline = _required_str(payload, "logline", "generate_story_bible")
    raw_export_profile = payload.get("export_profile")
    export_profile_payload = raw_export_profile if isinstance(raw_export_profile, dict) else {}
    raw_story_engine = payload.get("story_engine")
    story_engine_payload = raw_story_engine if isinstance(raw_story_engine, dict) else {}
    normalized = {
        "title": title,
        "logline": logline,
        "theme": _story_bible_text(payload.get("theme"), getattr(briefing, "theme", "")),
        "genre": _story_bible_text(payload.get("genre"), getattr(briefing, "genre", "")),
        "tone": _story_bible_text(payload.get("tone"), "cinematografico e emocional"),
        "target_emotion": _story_bible_text(
            payload.get("target_emotion"), getattr(briefing, "primary_emotion", "")
        ),
        "audience": _story_bible_text(payload.get("audience"), getattr(briefing, "audience", "")),
        "story_engine": {
            "dramatic_question": _story_bible_text(
                story_engine_payload.get("dramatic_question") or payload.get("dramatic_question"),
                "Qual escolha emocional define a historia?",
            ),
            "central_conflict": _story_bible_text(
                story_engine_payload.get("central_conflict") or payload.get("central_conflict"),
                logline,
            ),
            "emotional_promise": _story_bible_text(
                story_engine_payload.get("emotional_promise") or payload.get("emotional_promise"),
                logline,
            ),
            "inciting_incident": _story_bible_text(
                story_engine_payload.get("inciting_incident") or payload.get("inciting_incident"),
                "",
            ),
            "midpoint_turn": _story_bible_text(
                story_engine_payload.get("midpoint_turn") or payload.get("midpoint_turn"),
                "",
            ),
            "climax": _story_bible_text(
                story_engine_payload.get("climax") or payload.get("climax"),
                "",
            ),
            "ending_image": _story_bible_text(
                story_engine_payload.get("ending_image") or payload.get("ending_image"),
                "",
            ),
        },
        "world_rules": _story_bible_string_list(payload.get("world_rules"), ["realismo emocional"]),
        "visual_style": payload.get("visual_style")
        if isinstance(payload.get("visual_style"), dict)
        else {"description": _story_bible_text(payload.get("visual_style"), "cinematico realista")},
        "narrative_rules": _story_bible_string_list(
            payload.get("narrative_rules"), ["gancho claro", "payoff emocional"]
        ),
        "forbidden_elements": _story_bible_string_list(
            payload.get("forbidden_elements"), ["exposicao longa", "reviravolta aleatoria"]
        ),
        "characters": _normalize_story_bible_characters(payload, idea_payload),
        "locations": _normalize_story_bible_locations(payload),
        "props": _normalize_story_bible_props(payload),
        "timeline": _story_bible_profile_items(payload.get("timeline")),
        "relationships": _story_bible_profile_items(payload.get("relationships")),
        "continuity_rules": _story_bible_string_list(
            payload.get("continuity_rules"), ["manter continuidade de figurino e objetos"]
        ),
        "audio_style": payload.get("audio_style")
        if isinstance(payload.get("audio_style"), dict)
        else {"description": _story_bible_text(payload.get("audio_style"), "audio discreto")},
        "export_profile": export_profile_payload,
    }
    normalized["export_profile"] = {
        "aspect_ratio": str(export_profile_payload.get("aspect_ratio") or "9:16"),
        "resolution": str(export_profile_payload.get("resolution") or "1080x1920"),
        "language": str(export_profile_payload.get("language") or "pt-BR"),
    }
    normalized["script_contract"] = _story_bible_script_contract(normalized)
    normalized["visual_contract"] = _story_bible_visual_contract(normalized)
    normalized["quality_report"] = story_bible_quality_report(normalized)
    return normalized
