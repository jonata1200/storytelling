from app.storytelling.script_contracts import expected_script_scene_count
from app.storytelling.script_normalization import _clean_screenplay_location


def _fallback_script_content_from_bible(
    story_bible_payload: dict, title: str, target_duration_seconds: int
) -> str:
    logline = str(story_bible_payload.get("logline") or "").strip()
    protagonist = "A PROTAGONISTA"
    if isinstance(story_bible_payload.get("characters"), list):
        first_character = (
            story_bible_payload["characters"][0] if story_bible_payload["characters"] else {}
        )
        if isinstance(first_character, dict):
            protagonist = str(first_character.get("name") or "A PROTAGONISTA").upper()
    location = "CASA DA FAMILIA"
    if isinstance(story_bible_payload.get("locations"), list):
        first_location = (
            story_bible_payload["locations"][0] if story_bible_payload["locations"] else {}
        )
        if isinstance(first_location, dict):
            location = _clean_screenplay_location(first_location.get("name"), location)
    prop = "objeto de revelacao"
    if isinstance(story_bible_payload.get("props"), list):
        first_prop = story_bible_payload["props"][0] if story_bible_payload["props"] else {}
        if isinstance(first_prop, dict):
            prop = str(first_prop.get("name") or prop)
    return "\n\n".join(
        [
            f"TITULO: {title}",
            "FADE IN:",
            (
                "CENA 01\n"
                f"INT. {location} - FIM DE TARDE\n\n"
                f"{protagonist} permanece diante de uma mesa coberta por marcas do passado. "
                f"O {prop} aparece onde não deveria estar. Ela toca o objeto como se a "
                "casa inteira prendesse a respiracao.\n\n"
                f"{protagonist}\n"
                "Eu achei que essa historia tinha acabado."
            ),
            (
                "CENA 02\n"
                f"INT. {location} - NOITE\n\n"
                "A luz do corredor corta a sala em duas metades. Fotografias antigas, "
                f"cartas e pequenos sinais da vida familiar cercam {protagonist}. "
                f"Ela relê cada pista ate entender que {logline or 'a verdade sempre esteve ali'}."
            ),
            (
                "CENA 03\n"
                "EXT. RUA DIANTE DA CASA - MADRUGADA\n\n"
                f"{protagonist} sai para a rua vazia com o {prop} contra o peito. "
                "O silencio deixa claro que a próxima escolha não podera ser escondida."
            ),
            (
                "CENA 04\n"
                f"INT. {location} - AMANHECER\n\n"
                "A primeira luz revela poeira suspensa no ar. "
                f"{protagonist} coloca o {prop} no centro da mesa e encara a consequencia "
                "do que descobriu.\n\n"
                f"{protagonist}\n"
                "A verdade vai doer. Mas a mentira ja doeu por tempo demais."
            ),
            (
                "CENA 05\n"
                "EXT. FRENTE DA CASA - MANHA\n\n"
                f"{protagonist} fecha a porta sem tranca-la. Pela primeira vez, ela atravessa "
                "a luz da manha sem esconder o passado.\n\n"
                "FADE OUT."
            ),
        ]
    )


def _fallback_script_content_from_idea(
    idea_payload: dict, title: str, target_duration_seconds: int
) -> str:
    premise = str(idea_payload.get("premise") or "").strip()
    hook = str(idea_payload.get("hook") or "").strip()
    protagonist = str(idea_payload.get("protagonist") or "Clara").strip() or "Clara"
    protagonist_upper = protagonist.split(",", 1)[0].strip().upper() or "CLARA"
    conflict = str(idea_payload.get("conflict") or premise or "a verdade chega tarde demais")
    payoff = str(idea_payload.get("payoff") or idea_payload.get("resolution") or "").strip()
    scene_count = expected_script_scene_count(target_duration_seconds)
    base_beats = [
        (
            "INT. CASA DA FAMILIA - FIM DE TARDE",
            f"{protagonist_upper} percebe um detalhe fora do lugar. "
            f"{hook or 'Uma pista simples muda o péso da casa inteira.'}\n\n"
            f"{protagonist_upper}\n"
            "Isso não podia estar aqui.",
        ),
        (
            "INT. CORREDOR DA CASA - NOITE",
            f"A busca transforma cada fotografia em suspeita. {conflict}. "
            "A duvida avanca mais rapido do que a coragem.",
        ),
        (
            "INT. SALA DA FAMILIA - MADRUGADA",
            f"{protagonist_upper} junta as pistas e entende que a historia escondida "
            "não era sobre culpa simples. Era sobre uma escolha que feriu todos ao redor.",
        ),
        (
            "EXT. RUA DIANTE DA CASA - AMANHECER",
            f"{protagonist_upper} atravessa a primeira luz do dia decidido a contar "
            f"a verdade. {payoff or 'A reparacao não apaga a dor, mas abre uma porta.'}",
        ),
    ]
    expanded_beats: list[str] = []
    for index in range(scene_count):
        slugline, action = base_beats[index % len(base_beats)]
        turn = (
            "O conflito ganha nova camada, com uma escolha concreta que empurra "
            "a historia para a próxima virada."
            if index >= len(base_beats)
            else ""
        )
        ending = "\n\nFADE OUT." if index == scene_count - 1 else ""
        expanded_beats.append(
            f"CENA {index + 1:02d}\n{slugline}\n\n{action}"
            + (f"\n\n{turn}" if turn else "")
            + ending
        )
    return "\n\n".join(
        [
            f"TITULO: {title}",
            "FADE IN:",
            *expanded_beats,
        ]
    )
