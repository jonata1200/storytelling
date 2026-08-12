import unicodedata

from app.generation.prompt_language import (
    ensure_portuguese_prompt_text,
    formatted_prompt_sections,
)
from app.visual_bible.profiles import _clean_prompt_fragment, _prompt_text

CHARACTER_REQUIRED_VIEWS = ["front_portrait"]
CHARACTER_OPTIONAL_VIEWS = ["character_reference_sheet"]
CHARACTER_VIEWS = CHARACTER_REQUIRED_VIEWS + CHARACTER_OPTIONAL_VIEWS
LOCATION_VIEWS = ["establishing"]
PROP_REQUIRED_VIEWS = ["front"]
PROP_OPTIONAL_VIEWS = ["side"]
PROP_VIEWS = PROP_REQUIRED_VIEWS + PROP_OPTIONAL_VIEWS
VISUAL_PROMPT_OVERRIDES_KEY = "visual_prompt_overrides"
SIDE_ORIENTED_PROP_TERMS = (
    "ambulancia",
    "aviao",
    "barco",
    "bicicleta",
    "bike",
    "caminhao",
    "camionete",
    "carro",
    "carruagem",
    "espada",
    "faca",
    "helicoptero",
    "lancha",
    "moto",
    "motocicleta",
    "navio",
    "onibus",
    "patinete",
    "prancha",
    "revolver",
    "skate",
    "trem",
    "van",
    "veiculo",
)
VIEW_LABELS_PT = {
    "character_reference_sheet": "Folha de referencia do personagem",
    "front_portrait": "Retrato frontal de corpo inteiro",
    "left_profile": "Perfil lateral esquerdo",
    "right_profile": "Perfil lateral direito",
    "back_view": "Vista de costas",
    "full_body": "Corpo inteiro frontal",
    "expression_sheet": "Folha de expressoes",
    "pose_sheet": "Folha de poses",
    "scale_reference": "Referencia de escala",
    "establishing": "Plano geral do local",
    "floor_plan": "Planta baixa",
    "camera_points": "Pontos de camera",
    "prop_reference_sheet": "Folha de referencia do objeto",
    "front": "Vista frontal",
    "side": "Vista lateral",
    "top": "Vista superior",
}
VIEW_PROMPT_DETAILS = {
    "character_reference_sheet": (
        "folha única de referência em fundo branco: close frontal grande do rosto a esquerda, "
        "corpo inteiro frontal, corpo inteiro em perfil lateral e corpo inteiro de costas; "
        "mesmo rosto, cabelo, figurino, proporções e paleta; composicao horizontal limpa; "
        "sem texto, sem rotulos e sem bordas"
    ),
    "front_portrait": (
        "imagem inicial do personagem em pe, corpo inteiro, vista frontal, pose neutra, "
        "bracos relaxados, corpo dos pés ao topo da cabeça totalmente visivel"
    ),
    "left_profile": (
        "vista lateral esquerda de corpo inteiro, personagem em pe, mesmo rosto, cabelo, "
        "figurino e proporções"
    ),
    "right_profile": (
        "vista lateral direita de corpo inteiro, personagem em pe, mesmo rosto, cabelo, "
        "figurino e proporções"
    ),
    "back_view": (
        "vista de costas de corpo inteiro, personagem em pe, mesmo figurino, cabelo "
        "e proporções corporais visiveis"
    ),
    "full_body": (
        "vista frontal de corpo inteiro em pe, da cabeça aos pés, postura neutra "
        "e figurino base visiveis"
    ),
    "expression_sheet": (
        "folha de expressoes faciais com 4 emocoes, mesma identidade em todas as variacoes"
    ),
    "pose_sheet": (
        "folha de poses com 3 poses praticas de corpo inteiro, anatomia e figurino consistentes"
    ),
    "scale_reference": (
        "referência de escala de corpo inteiro, postura neutra, proporções claras"
    ),
    "establishing": (
        "plano geral cinematográfico do ambiente vazio, perspectiva natural de camera, "
        "organizacao espacial, luz, entradas e objetos principais visiveis"
    ),
    "floor_plan": (
        "planta baixa limpa vista de cima, sem perspectiva, paredes, portas, janelas, moveis "
        "principais e circulacao legíveis"
    ),
    "camera_points": (
        "painel de 3 enquadramentos cinematográficos verticais do mesmo local, mostrando "
        "angulos filmaveis consistentes"
    ),
    "prop_reference_sheet": (
        "folha única de referência do objeto em fundo branco: vista frontal, vista lateral, "
        "vista superior e detalhe ampliado de textura; mesmo material, cor, estado e escala; "
        "composicao limpa de fotografia de produto, sem texto, sem rotulos e sem bordas"
    ),
    "front": (
        "vista frontal, objeto totalmente em destáque, centralizado, material, "
        "cor e detalhes reconheciveis visiveis"
    ),
    "side": (
        "vista lateral ortografica de produto, objeto totalmente em destaque, comprimento, "
        "perfil, espessura, rodas ou eixos quando existirem, silhueta e construcao visiveis"
    ),
    "top": (
        "vista superior, objeto totalmente em destáque, forma, textura e detalhes legíveis visiveis"
    ),
}



def default_views_for(target_kind: str) -> list[str]:
    return {
        "character": CHARACTER_REQUIRED_VIEWS,
        "location": LOCATION_VIEWS,
        "prop": PROP_REQUIRED_VIEWS,
    }[target_kind]


def _normalized_prop_search_text(profile: dict) -> str:
    values: list[str] = []
    for key in (
        "name",
        "description",
        "dimensions",
        "material",
        "narrative_importance",
        "canonical_prompt",
    ):
        value = profile.get(key)
        if value:
            values.append(str(value))
    visual_profile = profile.get("visual_profile")
    if isinstance(visual_profile, dict):
        values.extend(str(value) for value in visual_profile.values() if value)
    narrative_profile = profile.get("narrative_profile")
    if isinstance(narrative_profile, dict):
        values.extend(str(value) for value in narrative_profile.values() if value)
    text = " ".join(values).casefold()
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def preferred_prop_view(profile: dict) -> str:
    text = _normalized_prop_search_text(profile)
    if any(term in text for term in SIDE_ORIENTED_PROP_TERMS):
        return "side"
    return "front"


def default_views_for_profile(target_kind: str, profile: dict) -> list[str]:
    if target_kind == "prop":
        return [preferred_prop_view(profile)]
    return default_views_for(target_kind)


def allowed_views_for(target_kind: str) -> list[str]:
    return {
        "character": CHARACTER_VIEWS,
        "location": LOCATION_VIEWS,
        "prop": PROP_VIEWS,
    }[target_kind]


def validated_visual_reference_views(target_kind: str, view_types: list[str] | None) -> list[str]:
    allowed = allowed_views_for(target_kind)
    if view_types is None:
        return default_views_for(target_kind)
    invalid = [view for view in view_types if view not in allowed]
    if invalid:
        raise ValueError(
            f"View type inválido para {target_kind}: {', '.join(invalid)}. "
            f"Use: {', '.join(allowed)}"
        )
    return view_types


def visual_reference_view_label(view_type: str) -> str:
    return VIEW_LABELS_PT.get(
        view_type,
        view_type.replace("_", " ").strip().capitalize() or "Vista visual",
    )


def initial_view_for(target_kind: str) -> str:
    return {
        "character": "front_portrait",
        "location": "establishing",
        "prop": "front",
    }[target_kind]


def initial_view_for_profile(target_kind: str, profile: dict) -> str:
    if target_kind == "prop":
        return preferred_prop_view(profile)
    return initial_view_for(target_kind)


COMMON_NEGATIVE_GUARDRAIL = (
    "sem texto, marca d'agua, logotipo, interface visual, borrado ou duplicacoes"
)


def _character_view_guardrail(view_type: str) -> str:
    if view_type == "character_reference_sheet":
        return (
            "uma única imagem, não separar em arquivos; fundo branco puro de estudio; "
            "mesmo personagem nas perspectivas solicitadas; rosto, anatomia e figurino "
            "consistentes; iluminação uniforme; alinhar altura das poses; não cortar cabeça, "
            "pés ou mãos"
        )
    if view_type == "front_portrait":
        return (
            "personagem em pe, corpo inteiro, vista frontal, pose neutra, olhando para a camera, "
            "fundo cinza neutro de estudio, uma única péssoa, sem cenario, sem objetos extras, "
            "não cortar cabeça, pés ou mãos"
        )
    return (
        "fundo branco puro de estudio, corpo inteiro, angulo solicitado, manter mesmo rosto, "
        "cabelo, corpo, figurino, sapatos, proporções e paleta"
    )


def _location_view_guardrail(view_type: str) -> str:
    if view_type == "floor_plan":
        return (
            "visual tecnico limpo, vista ortografica de cima, sem pessoas ou perspectiva "
            "cinematografica; portas, janelas, moveis e circulacao claros"
        )
    if view_type == "camera_points":
        return (
            "tres quadros no mesmo painel, mesmo ambiente, sem pessoas, sem personagens; "
            "variar angulos mantendo arquitetura, portas, janelas e objetos fixos consistentes"
        )
    return (
        "cenario vazio, sem pessoas, sem personagens ou silhuetas; priorizar arquitetura, "
        "organizacao espacial, luz, materiais e objetos fixos"
    )


def _prop_view_guardrail(view_type: str) -> str:
    if view_type == "prop_reference_sheet":
        return (
            "uma única imagem, não separar em arquivos; objeto isolado em fundo branco puro; "
            "mesmo objeto em varias vistas, sem pessoas, sem mãos ou ambiente; permitir detalhe "
            "ampliado e escala discreta"
        )
    if view_type == "scale_reference":
        return (
            "objeto isolado em fundo branco puro; permitir regua, grade simples ou silhueta "
            "neutra apenas para escala; sem pessoas reais, sem mãos, sem cenario"
        )
    return (
        "objeto isolado, fundo branco puro, inteiro e centralizado, sem pessoas, sem mãos, "
        "sem ambiente, sem outros objetos"
    )


def visual_reference_aspect_ratio(profile: dict, view_type: str) -> str:
    if view_type == "character_reference_sheet":
        return "16:9"
    asset_kind = str(profile.get("asset_kind") or "")
    if asset_kind == "prop":
        return "9:16"
    if asset_kind == "location":
        return "16:9"
    if asset_kind == "character" and view_type != "front_portrait":
        return "16:9"
    return "9:16"


def _truncate_prompt_text(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.;") + "."


def _compact_visual_base_prompt(profile: dict) -> str:
    asset_kind = str(profile.get("asset_kind") or "")
    name = str(profile.get("name") or "").strip()
    if asset_kind == "character":
        identity_base_name = _prompt_text(profile.get("identity_base_name"))
        identity_variant_note = _prompt_text(profile.get("identity_variant_note"))
        parts = [
            "Fotorrealista, referência de elenco",
            name,
            f"identidade base {identity_base_name}" if identity_base_name else "",
            f"variante {identity_variant_note}" if identity_variant_note else "",
            _clean_prompt_fragment(
                profile.get("gender"),
                ("personagem", "gênero visual", "gênero visual"),
            ),
            _prompt_text(profile.get("apparent_age")),
            _prompt_text(profile.get("body_type")),
            f"rosto {_clean_prompt_fragment(profile.get('face_shape'), ('rosto', 'face'))}",
            f"pele {_clean_prompt_fragment(profile.get('skin_tone'), ('pele', 'tom de pele'))}",
            f"olhos {_clean_prompt_fragment(profile.get('eyes'), ('olhos',))}",
            f"cabelo {_clean_prompt_fragment(profile.get('hair'), ('cabelo',))}",
            f"figurino {_clean_prompt_fragment(profile.get('base_outfit'), ('figurino', 'roupa'))}",
            f"paleta {_clean_prompt_fragment(profile.get('palette'), ('paleta',))}",
        ]
        return _truncate_prompt_text(
            ensure_portuguese_prompt_text(". ".join(part for part in parts if part)),
            370,
        )
    if asset_kind == "location":
        parts = [
            "Fotorrealista, arquitetura cinematografica",
            name,
            f"funcao {_prompt_text(profile.get('description'))}",
            f"organizacao espacial {_prompt_text(profile.get('layout'))}",
            f"materiais {_prompt_text(profile.get('materials'))}",
            f"paleta {_clean_prompt_fragment(profile.get('palette'), ('paleta',))}",
            f"luz {_prompt_text(profile.get('lighting'))}",
        ]
        return _truncate_prompt_text(
            ensure_portuguese_prompt_text(". ".join(part for part in parts if part)),
            360,
        )
    if asset_kind == "prop":
        parts = [
            "Fotorrealista, fotografia de produto",
            name,
            f"dimensoes {_prompt_text(profile.get('dimensions'))}",
            f"material {_prompt_text(profile.get('material'))}",
            f"cor {_prompt_text(profile.get('color'))}",
            f"estado {_prompt_text(profile.get('state'))}",
            "referencia isolada do objeto, sem encenar contexto narrativo",
        ]
        return _truncate_prompt_text(
            ensure_portuguese_prompt_text(". ".join(part for part in parts if part)),
            320,
        )
    fallback = str(profile.get("canonical_prompt") or name or "").strip()
    return _truncate_prompt_text(ensure_portuguese_prompt_text(fallback), 360)


def _visual_prompt_override(profile: dict, view_type: str) -> str:
    overrides = profile.get(VISUAL_PROMPT_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return ""
    prompt = str(overrides.get(view_type) or "").strip()
    if not prompt:
        return ""
    return ensure_portuguese_prompt_text(prompt)


def visual_reference_prompt(profile: dict, view_type: str) -> str:
    if override := _visual_prompt_override(profile, view_type):
        return override

    base_prompt = _compact_visual_base_prompt(profile)
    view_detail = VIEW_PROMPT_DETAILS.get(view_type, view_type.replace("_", " "))
    asset_kind = str(profile.get("asset_kind") or "")
    aspect_ratio = visual_reference_aspect_ratio(profile, view_type)
    if asset_kind == "location":
        guardrail = _location_view_guardrail(view_type)
    elif asset_kind == "prop":
        guardrail = _prop_view_guardrail(view_type)
    else:
        guardrail = _character_view_guardrail(view_type)
    return formatted_prompt_sections(
        [
            (
                "Objetivo",
                "Criar uma referencia visual fotorrealista e consistente para continuidade.",
            ),
            ("Ativo", base_prompt),
            ("Vista solicitada", f"{visual_reference_view_label(view_type)}. {view_detail}."),
            ("Composicao e foco", guardrail),
            (
                "Continuidade obrigatoria",
                "Preservar identidade, materiais, cor, escala, proporcoes e detalhes legiveis.",
            ),
            ("Restricoes", COMMON_NEGATIVE_GUARDRAIL),
            ("Proporcao", aspect_ratio),
        ]
    )
