import hashlib
import re

from app.visual_bible.profiles import (
    _ascii_lower,
    _clean_prompt_fragment,
    _first_value,
    _profile_mapping,
    _prompt_text,
    _seeded_choice,
    _short_text,
)


def _character_gender(raw_gender: object, name: str, role: object) -> str:
    explicit = _ascii_lower(raw_gender).strip()
    if explicit and explicit not in {"pessoa", "personagem", "indefinido", "indefinida"}:
        if any(term in explicit for term in ("fem", "mulher", "female", "woman")):
            return "personagem feminino"
        if any(term in explicit for term in ("masc", "homem", "male", "man")):
            return "personagem masculino"
        return f"genero visual definido: {_prompt_text(raw_gender)}"

    combined = f"{_ascii_lower(name)} {_ascii_lower(role)}"
    female_terms = {
        "dona",
        "senhora",
        "mae",
        "filha",
        "irma",
        "tia",
        "esposa",
        "viuva",
        "mulher",
        "menina",
        "garota",
        "neta",
        "professora",
        "medica",
    }
    male_terms = {
        "senhor",
        "pai",
        "filho",
        "irmao",
        "tio",
        "marido",
        "viuvo",
        "homem",
        "menino",
        "garoto",
        "neto",
        "professor",
        "medico",
    }
    female_names = {
        "clara",
        "marta",
        "maria",
        "ana",
        "helena",
        "lourdes",
        "celia",
        "beatriz",
        "julia",
        "sofia",
        "laura",
        "luiza",
        "alice",
        "mariana",
        "teresa",
        "rosa",
        "cristina",
    }
    male_names = {
        "lucas",
        "pedro",
        "joao",
        "jose",
        "antonio",
        "carlos",
        "miguel",
        "rafael",
        "gabriel",
        "mateus",
        "daniel",
        "paulo",
        "marcos",
        "andre",
        "luiz",
    }
    tokens = set(re.findall(r"[a-z]+", combined))
    first_name = next(iter(re.findall(r"[a-z]+", _ascii_lower(name))), "")
    if tokens & female_terms or first_name in female_names:
        return "personagem feminino"
    if tokens & male_terms or first_name in male_names:
        return "personagem masculino"
    if first_name.endswith("a"):
        return "personagem feminino"
    if first_name.endswith(("o", "os", "el")):
        return "personagem masculino"
    return _seeded_choice(name, ["personagem feminino", "personagem masculino"], 5)


def _character_gender_guardrail(gender: object) -> str:
    normalized = _ascii_lower(gender)
    if "fem" in normalized or "mulher" in normalized:
        return "Genero visual obrigatorio: feminino; nao masculinizar."
    if "masc" in normalized or "homem" in normalized:
        return "Genero visual obrigatorio: masculino; nao feminilizar."
    return f"Genero visual obrigatorio: {_prompt_text(gender)}."


TEMPORAL_VARIANT_NOTES = {
    "futuro": "versao futura mais velha; preservar tracos faciais familiares",
    "futura": "versao futura mais velha; preservar tracos faciais familiares",
    "passado": "versao do passado mais jovem; preservar tracos faciais familiares",
    "passada": "versao do passado mais jovem; preservar tracos faciais familiares",
    "jovem": "versao jovem; preservar tracos faciais familiares",
    "velho": "versao idosa; preservar tracos faciais familiares",
    "velha": "versao idosa; preservar tracos faciais familiares",
    "idoso": "versao idosa; preservar tracos faciais familiares",
    "idosa": "versao idosa; preservar tracos faciais familiares",
    "crianca": "versao crianca; preservar tracos faciais familiares",
    "criança": "versao crianca; preservar tracos faciais familiares",
    "menino": "versao crianca; preservar tracos faciais familiares",
    "menina": "versao crianca; preservar tracos faciais familiares",
    "adolescente": "versao adolescente; preservar tracos faciais familiares",
}


def _character_identity_base(name: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    if not text:
        return "Personagem", ""

    normalized = _ascii_lower(text)
    matched_note = ""
    for token, note in TEMPORAL_VARIANT_NOTES.items():
        if re.search(rf"\b{re.escape(_ascii_lower(token))}\b", normalized):
            matched_note = note
            break

    temporal_terms = "|".join(re.escape(term) for term in TEMPORAL_VARIANT_NOTES)
    base = re.sub(rf"(?i)^\s*(?:{temporal_terms})\s+", "", text).strip()
    base = re.sub(rf"(?i)\s+(?:{temporal_terms})\s*$", "", base).strip()
    base = re.sub(r"(?i)\s+(?:do|da|de)\s+futuro\s*$", "", base).strip()
    base = re.sub(r"\s+", " ", base).strip(" .:-")
    if not base:
        base = text
        matched_note = ""
    if base == text:
        matched_note = ""
    return base, matched_note


def _character_visual_defaults(name: str) -> dict[str, object]:
    outfit_layers = [
        "casaco de linho verde musgo sobre camisa creme amarrotada",
        "jaqueta jeans clara com costuras aparentes e camiseta vinho",
        "cardiga azul petroleo com vestido floral discreto",
        "blazer cinza gasto, camisa branca sem gravata e calca escura",
        "sueter mostarda texturizado com saia preta simples",
        "camisa de algodao terracota com suspensorio marrom envelhecido",
        "vestido azul escuro com xale de la rustico",
        "jaqueta de couro caramelo marcada pelo uso e blusa neutra",
    ]
    hair_styles = [
        "cabelo castanho curto com franja irregular",
        "cabelo grisalho preso em coque baixo",
        "cabelo preto ondulado na altura dos ombros",
        "cabelo ruivo cacheado preso de lado",
        "cabelo raspado nas laterais com topo natural",
        "cabelo loiro escuro comprido, levemente despenteado",
        "tranças finas presas para tras",
        "cabelo branco curto, bem alinhado",
    ]
    eye_details = [
        "olhos cansados com olhar atento e sobrancelhas marcantes",
        "olhos pequenos e intensos, expressao desconfiada",
        "olhos grandes e melancolicos, brilho contido",
        "olhos claros, postura emocional reservada",
        "olhos escuros, olhar caloroso mas firme",
    ]
    body_types = [
        "silhueta alta e magra, postura levemente curvada",
        "corpo baixo e compacto, gestos precisos",
        "porte medio, ombros relaxados e presenca discreta",
        "corpo robusto, postura protetora",
        "silhueta delicada, movimentos contidos",
    ]
    palettes = [
        ["verde musgo", "creme envelhecido", "marrom quente"],
        ["azul petroleo", "vinho profundo", "cinza frio"],
        ["mostarda", "preto fosco", "branco antigo"],
        ["terracota", "caramelo", "azul desbotado"],
        ["lilas queimado", "grafite", "dourado suave"],
    ]
    origins = [
        "brasileira",
        "brasileira do interior",
        "brasileira urbana",
        "brasileira litoranea",
        "brasileira de origem nordestina",
    ]
    height_cm = 155 + (
        int(hashlib.sha1(f"{name}:height".encode()).hexdigest()[:8], 16) % 36
    )
    return {
        "origin": _seeded_choice(name, origins, 0),
        "height_cm": height_cm,
        "hair": _seeded_choice(name, hair_styles, 1),
        "eyes": _seeded_choice(name, eye_details, 2),
        "body_type": _seeded_choice(name, body_types, 3),
        "base_outfit": _seeded_choice(name, outfit_layers, 4),
        "palette": palettes[int(hashlib.sha1(name.encode()).hexdigest()[:8], 16) % len(palettes)],
    }


def _character_profile(raw: object) -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Personagem")
    identity_base_name, identity_variant_note = _character_identity_base(name)
    defaults = _character_visual_defaults(identity_base_name)
    role = _short_text(_first_value(raw, "role", "funcao", "função"), "personagem", 120)
    gender = _character_gender(
        _first_value(raw, "gender", "genero", "sexo", fallback=""),
        name,
        role,
    )
    origin = _first_value(raw, "origin", "origem", "nacionalidade", fallback=defaults["origin"])
    height_cm = _first_value(
        raw, "height_cm", "altura_cm", "altura", fallback=defaults["height_cm"]
    )
    apparent_age = _first_value(
        raw,
        "apparent_age",
        "idade_aparente",
        "idade",
        fallback=identity_variant_note or "adulto de idade visual definida",
    )
    body_type = _first_value(
        raw, "body_type", "tipo_fisico", "corpo", fallback=defaults["body_type"]
    )
    face_shape = _first_value(
        raw,
        "face_shape",
        "formato_rosto",
        "rosto",
        fallback="rosto com estrutura clara e memoravel",
    )
    skin_tone = _first_value(
        raw, "skin_tone", "tom_de_pele", "pele", fallback="tom de pele natural sob luz cinematica"
    )
    eyes = _first_value(raw, "eyes", "olhos", fallback=defaults["eyes"])
    hair = _first_value(raw, "hair", "cabelo", fallback=defaults["hair"])
    base_outfit = _first_value(
        raw, "base_outfit", "figurino_base", "roupa", "figurino", fallback=defaults["base_outfit"]
    )
    palette = _first_value(
        raw, "palette", "paleta", "paleta_de_cores", fallback=defaults["palette"]
    )
    personality = _first_value(
        raw,
        "personality",
        "personalidade",
        fallback="personalidade especifica e coerente com a historia",
    )
    narrative_profile = {
        "name": name,
        "role": role,
        "personality": personality,
        "arc": _first_value(raw, "arc", "arco", fallback=""),
        "voice": raw.get("voice", "voz humana calorosa"),
    }
    visual_profile = {
        "gender": gender,
        "origin": origin,
        "height_cm": height_cm,
        "apparent_age": apparent_age,
        "body_type": body_type,
        "face_shape": face_shape,
        "skin_tone": skin_tone,
        "eyes": eyes,
        "hair": hair,
        "base_outfit": base_outfit,
        "palette": palette,
    }
    return {
        "permanent_id": raw.get("id", f"char_{hashlib.sha1(name.encode()).hexdigest()[:8]}"),
        "name": name,
        "identity_base_name": identity_base_name,
        "identity_variant_note": identity_variant_note,
        "role": role,
        "gender": gender,
        "origin": origin,
        "height_cm": height_cm,
        "apparent_age": apparent_age,
        "body_type": body_type,
        "face_shape": face_shape,
        "skin_tone": skin_tone,
        "eyes": eyes,
        "hair": hair,
        "base_outfit": base_outfit,
        "palette": palette,
        "voice": raw.get("voice", "voz humana calorosa"),
        "personality": personality,
        "arc": narrative_profile["arc"],
        "scene_numbers": raw.get("scene_numbers", []),
        "evidence_text": raw.get("evidence_text", []),
        "importance": raw.get("importance", ""),
        "narrative_profile": narrative_profile,
        "visual_profile": visual_profile,
        "asset_kind": "character",
        "visual_constraints": [
            "manter idade aparente",
            "manter cabelo",
            "manter figurino base exclusivo deste personagem",
            "nao reutilizar roupa de outro personagem",
            "preservar identidade visual base em versoes temporais do mesmo personagem",
        ],
        "canonical_prompt": (
            "Fotorrealista, referencia de elenco, identidade consistente do personagem. "
            f"Identidade visual base: {identity_base_name}. "
            f"{f'Variante temporal: {identity_variant_note}. ' if identity_variant_note else ''}"
            f"{_character_gender_guardrail(gender)} "
            f"{name}, {_prompt_text(origin)}, {_prompt_text(apparent_age)}, "
            f"{_prompt_text(body_type)}, {_prompt_text(height_cm)}cm. "
            f"Rosto {_clean_prompt_fragment(face_shape, ('rosto', 'face'))}, "
            f"pele {_clean_prompt_fragment(skin_tone, ('pele', 'tom de pele'))}, "
            f"olhos {_clean_prompt_fragment(eyes, ('olhos',))}, "
            f"cabelo {_clean_prompt_fragment(hair, ('cabelo',))}. "
            f"Papel: {_prompt_text(role)}. "
            "Figurino base exclusivo: "
            f"{_clean_prompt_fragment(base_outfit, ('figurino', 'roupa'))}. "
            f"Paleta: {_clean_prompt_fragment(palette, ('paleta',))}. "
            "Manter mesmo rosto, cabelo, corpo, figurino e paleta."
        ),
    }



