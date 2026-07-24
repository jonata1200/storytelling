from app.visual_bible.profiles import _clean_prompt_fragment, _prompt_text

CHARACTER_VIEWS = ["character_reference_sheet"]
LOCATION_VIEWS = ["establishing", "floor_plan", "camera_points"]
PROP_VIEWS = ["prop_reference_sheet"]
VIEW_PROMPT_DETAILS = {
    "character_reference_sheet": (
        "folha unica de referencia em fundo branco: close frontal grande do rosto a esquerda, "
        "corpo inteiro frontal, corpo inteiro em perfil lateral e corpo inteiro de costas; "
        "mesmo rosto, cabelo, figurino, proporcoes e paleta; composicao horizontal limpa; "
        "sem texto, sem labels e sem bordas"
    ),
    "front_portrait": (
        "imagem inicial do personagem em pe, corpo inteiro, vista frontal, pose neutra, "
        "bracos relaxados, corpo dos pes ao topo da cabeca totalmente visivel"
    ),
    "left_profile": (
        "vista lateral esquerda de corpo inteiro, personagem em pe, mesmo rosto, cabelo, "
        "figurino e proporcoes"
    ),
    "right_profile": (
        "vista lateral direita de corpo inteiro, personagem em pe, mesmo rosto, cabelo, "
        "figurino e proporcoes"
    ),
    "back_view": (
        "vista de costas de corpo inteiro, personagem em pe, mesmo figurino, cabelo "
        "e proporcoes corporais visiveis"
    ),
    "full_body": (
        "vista frontal de corpo inteiro em pe, da cabeca aos pes, postura neutra "
        "e figurino base visiveis"
    ),
    "expression_sheet": (
        "folha de expressoes faciais com 4 emocoes, mesma identidade em todas as variacoes"
    ),
    "pose_sheet": (
        "folha de poses com 3 poses praticas de corpo inteiro, anatomia e figurino consistentes"
    ),
    "scale_reference": (
        "referencia de escala de corpo inteiro, postura neutra, proporcoes claras"
    ),
    "establishing": (
        "plano geral cinematografico do ambiente vazio, perspectiva natural de camera, "
        "layout espacial, luz, entradas e objetos principais visiveis"
    ),
    "floor_plan": (
        "planta baixa limpa vista de cima, sem perspectiva, paredes, portas, janelas, moveis "
        "principais e circulacao legiveis"
    ),
    "camera_points": (
        "painel de 3 enquadramentos cinematograficos verticais do mesmo local, mostrando "
        "angulos filmaveis consistentes"
    ),
    "prop_reference_sheet": (
        "folha unica de referencia do objeto em fundo branco: vista frontal, vista lateral, "
        "vista superior e detalhe ampliado de textura; mesmo material, cor, estado e escala; "
        "composicao limpa de fotografia de produto, sem texto, sem labels e sem bordas"
    ),
    "front": (
        "vista frontal, objeto totalmente em destaque, centralizado, material, "
        "cor e detalhes reconheciveis visiveis"
    ),
    "side": (
        "vista lateral, objeto totalmente em destaque, espessura, silhueta e construcao visiveis"
    ),
    "top": (
        "vista superior, objeto totalmente em destaque, forma, textura e detalhes legiveis visiveis"
    ),
}



def default_views_for(target_kind: str) -> list[str]:
    return {
        "character": CHARACTER_VIEWS,
        "location": LOCATION_VIEWS,
        "prop": PROP_VIEWS,
    }[target_kind]


def validated_visual_reference_views(target_kind: str, view_types: list[str] | None) -> list[str]:
    allowed = default_views_for(target_kind)
    if view_types is None:
        return allowed
    invalid = [view for view in view_types if view not in allowed]
    if invalid:
        raise ValueError(
            f"View type invalido para {target_kind}: {', '.join(invalid)}. "
            f"Use: {', '.join(allowed)}"
        )
    return view_types


def initial_view_for(target_kind: str) -> str:
    return {
        "character": "character_reference_sheet",
        "location": "establishing",
        "prop": "prop_reference_sheet",
    }[target_kind]


COMMON_NEGATIVE_GUARDRAIL = (
    "sem texto, marca d'agua, logotipo, UI, borrado ou duplicacoes"
)


def _character_view_guardrail(view_type: str) -> str:
    if view_type == "character_reference_sheet":
        return (
            "uma unica imagem, nao separar em arquivos; fundo branco puro de estudio; "
            "mesmo personagem nas perspectivas solicitadas; rosto, anatomia e figurino "
            "consistentes; iluminacao uniforme; alinhar altura das poses; nao cortar cabeca, "
            "pes ou maos"
        )
    if view_type == "front_portrait":
        return (
            "personagem em pe, corpo inteiro, vista frontal, pose neutra, olhando para a camera, "
            "fundo cinza neutro de estudio, uma unica pessoa, sem cenario, sem objetos extras, "
            "nao cortar cabeca, pes ou maos"
        )
    return (
        "fundo branco puro de estudio, corpo inteiro, angulo solicitado, manter mesmo rosto, "
        "cabelo, corpo, figurino, sapatos, proporcoes e paleta"
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
        "layout, luz, materiais e objetos fixos"
    )


def _prop_view_guardrail(view_type: str) -> str:
    if view_type == "prop_reference_sheet":
        return (
            "uma unica imagem, nao separar em arquivos; objeto isolado em fundo branco puro; "
            "mesmo objeto em varias vistas, sem pessoas, sem maos ou ambiente; permitir detalhe "
            "ampliado e escala discreta"
        )
    if view_type == "scale_reference":
        return (
            "objeto isolado em fundo branco puro; permitir regua, grade simples ou silhueta "
            "neutra apenas para escala; sem pessoas reais, sem maos, sem cenario"
        )
    return (
        "objeto isolado, fundo branco puro, inteiro e centralizado, sem pessoas, sem maos, "
        "sem ambiente, sem outros objetos"
    )


def visual_reference_aspect_ratio(profile: dict, view_type: str) -> str:
    if view_type == "character_reference_sheet":
        return "16:9"
    if view_type == "prop_reference_sheet":
        return "16:9"
    asset_kind = str(profile.get("asset_kind") or "")
    if asset_kind == "location":
        return "16:9"
    if asset_kind == "prop":
        return "1:1"
    if asset_kind == "character":
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
        parts = [
            "Fotorrealista, referencia de elenco",
            name,
            _clean_prompt_fragment(
                profile.get("gender"),
                ("personagem", "genero visual", "gênero visual"),
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
        return _truncate_prompt_text(". ".join(part for part in parts if part), 420)
    if asset_kind == "location":
        parts = [
            "Fotorrealista, arquitetura cinematografica",
            name,
            f"funcao {_prompt_text(profile.get('description'))}",
            f"layout {_prompt_text(profile.get('layout'))}",
            f"materiais {_prompt_text(profile.get('materials'))}",
            f"paleta {_clean_prompt_fragment(profile.get('palette'), ('paleta',))}",
            f"luz {_prompt_text(profile.get('lighting'))}",
        ]
        return _truncate_prompt_text(". ".join(part for part in parts if part), 360)
    if asset_kind == "prop":
        parts = [
            "Fotorrealista, fotografia de produto",
            name,
            f"importancia {_prompt_text(profile.get('narrative_importance'))}",
            f"dimensoes {_prompt_text(profile.get('dimensions'))}",
            f"material {_prompt_text(profile.get('material'))}",
            f"cor {_prompt_text(profile.get('color'))}",
            f"estado {_prompt_text(profile.get('state'))}",
        ]
        return _truncate_prompt_text(". ".join(part for part in parts if part), 320)
    fallback = str(profile.get("canonical_prompt") or name or "").strip()
    return _truncate_prompt_text(fallback, 360)


def visual_reference_prompt(profile: dict, view_type: str) -> str:
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
    return (
        f"{base_prompt}. Vista: {view_detail}. Regras: {guardrail}. "
        f"Evitar: {COMMON_NEGATIVE_GUARDRAIL}. Proporcao: {aspect_ratio}. "
        "Referencia de continuidade; detalhes legiveis."
    )
