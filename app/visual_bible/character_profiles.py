import hashlib
import re

from app.generation.prompt_language import ensure_portuguese_prompt_text
from app.visual_bible.prompt_balance import (
    CHARACTER_PROMPT_MAX_WORDS,
    balanced_visual_prompt,
    concise_prompt_fragment,
    prompt_word_count,
    repair_portuguese_mojibake,
)
from app.visual_bible.stable_choice import stable_choice
from app.visual_bible.text_helpers import (
    _ascii_lower,
    _clean_prompt_fragment,
    _first_value,
    _profile_mapping,
    _prompt_text,
    _short_text,
)


def _character_gender(
    raw_gender: object, name: str, role: object, apparent_age: object = ""
) -> str:
    explicit = _ascii_lower(raw_gender).strip()
    if explicit and explicit not in {"péssoa", "personagem", "indefinido", "indefinida"}:
        if any(term in explicit for term in ("fem", "mulher", "female", "woman")):
            return "personagem feminino"
        if any(term in explicit for term in ("masc", "homem", "male", "man")):
            return "personagem masculino"
        return f"gênero visual definido: {_prompt_text(raw_gender)}"

    # Nome-base: ignora prefixos temporais ("Menino João" -> "João") para que
    # o gênero não seja decidido pelo próprio qualificador de idade.
    age_key = _ascii_lower(apparent_age)
    base_name = _character_identity_base(name)[0]
    if any(term in age_key.split() for term in ("menino", "garoto")):
        return "personagem masculino"
    if any(term in age_key.split() for term in ("menina", "garota")):
        return "personagem feminino"
    name_tokens = set(re.findall(r"[a-z]+", _ascii_lower(base_name)))
    role_tokens = set(re.findall(r"[a-z]+", _ascii_lower(role)))
    combined = name_tokens | role_tokens
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
        "enfermeira",
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
        "enfermeiro",
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
        "ruth",
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
    if combined & female_terms or name_tokens & female_names:
        return "personagem feminino"
    if combined & male_terms or name_tokens & male_names:
        return "personagem masculino"
    # O nome próprio é o ÚLTIMO token ("Vovó Zilda" -> "zilda", "Detetive
    # Ramos" -> "ramos"); o primeiro pode ser título ("Vovó", "Sra.", "Sr.").
    given_name = sorted(name_tokens)[-1] if name_tokens else ""
    if given_name.endswith("a"):
        return "personagem feminino"
    if given_name.endswith(("o", "os", "el", "s", "is", "az", "iz", "or", "r", "l")):
        # "Elias", "Rafael", "Gabriel", "Detetive Ramos": terminações
        # tipicamente masculinas em pt-BR que antes caíam no vazio.
        return "personagem masculino"
    # Fallback neutro explícito: gênero nunca fica em silêncio — o prompt
    # recebe uma indicação neutra em vez de nada (o provedor de imagem
    # decidiria sozinho, gerando inconsistência entre gerações).
    return "pessoa de gênero não especificado"


def _character_gender_guardrail(gender: object) -> str:
    normalized = _ascii_lower(gender)
    if "fem" in normalized or "mulher" in normalized:
        return "Gênero visual obrigatório: feminino; não masculinizar."
    if "masc" in normalized or "homem" in normalized:
        return "Gênero visual obrigatório: masculino; não feminilizar."
    return f"Gênero visual obrigatório: {_prompt_text(gender)}."


TEMPORAL_VARIANT_NOTES = {
    "futuro": "versão futura mais velha; preservar tracos faciais familiares",
    "futura": "versão futura mais velha; preservar tracos faciais familiares",
    "passado": "versão do passado mais jovem; preservar tracos faciais familiares",
    "passada": "versão do passado mais jovem; preservar tracos faciais familiares",
    "jovem": "versão jovem; preservar tracos faciais familiares",
    "velho": "versão idosa; preservar tracos faciais familiares",
    "velha": "versão idosa; preservar tracos faciais familiares",
    "idoso": "versão idosa; preservar tracos faciais familiares",
    "idosa": "versão idosa; preservar tracos faciais familiares",
    "crianca": "versão crianca; preservar tracos faciais familiares",
    "criança": "versão crianca; preservar tracos faciais familiares",
    "menino": "versão crianca; preservar tracos faciais familiares",
    "menina": "versão crianca; preservar tracos faciais familiares",
    "adolescente": "versão adolescente; preservar tracos faciais familiares",
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


def _stable_character_choice(name: str, values: tuple[str, ...], offset: int) -> str:
    # Implementação única compartilhada com os presets de locais (INC-04).
    return stable_choice(name, values, offset)


def _character_visual_defaults(
    name: str, gender: object, apparent_age: object = ""
) -> dict[str, object]:
    gender_key = _ascii_lower(gender)
    feminine = "fem" in gender_key or "mulher" in gender_key
    stage = _age_stage(apparent_age)
    child = stage == "child"
    adolescent = stage == "adolescent"
    # Crianças e adolescentes NÃO recebem medidas numéricas de altura/peso:
    # a idade escrita ("deve aparentar oito anos") já determina as
    # proporções corporais para o provedor de imagem, e um número de adulto
    # (1,65 m / 66 kg para uma menina de 8 anos) conflita com ela.
    if child or adolescent:
        heights: tuple[str, ...] = ()
        weights: tuple[str, ...] = ()
    else:
        heights = (
            ("158", "162", "165", "168", "171")
            if feminine
            else (
                "168",
                "172",
                "176",
                "180",
                "184",
            )
        )
        weights = (
            ("54", "58", "62", "66", "70")
            if feminine
            else (
                "66",
                "71",
                "76",
                "81",
                "86",
            )
        )
    hair = (
        (
            "castanho-escuro, ondulado e na altura dos ombros",
            "preto, liso e preso em um rabo de cavalo baixo",
            "castanho, cacheado e cortado na altura do queixo",
        )
        if feminine
        else (
            "preto, curto e levemente ondulado",
            "castanho-escuro, curto nas laterais e mais cheio no topo",
            "castanho, crespo e cortado rente",
        )
    )
    return {
        "origin": "",
        "height_cm": _stable_character_choice(name, heights, 1) if heights else "",
        "weight_kg": _stable_character_choice(name, weights, 2) if weights else "",
        "hair": _stable_character_choice(name, hair, 3),
        "eyes": _stable_character_choice(
            name, ("castanhos escuros", "castanhos claros", "verdes", "azuis"), 4
        ),
        "skin_tone": _stable_character_choice(
            name,
            (
                "parda de subtom quente",
                "morena clara",
                "negra de subtom quente",
                "clara de subtom neutro",
            ),
            5,
        ),
        "body_type": _stable_character_choice(
            name,
            (
                "porte médio e estrutura corporal esguia",
                "porte médio e estrutura corporal robusta",
                "corpo alto e magro",
                "corpo compacto e atlético",
            ),
            6,
        ),
        "face_shape": _stable_character_choice(
            name,
            (
                "rosto oval com maxilar suave",
                "rosto alongado com maçãs discretas",
                "rosto quadrado com maxilar marcado",
                "rosto redondo com traços suaves",
            ),
            7,
        ),
        "base_outfit": "",
        "footwear": "",
        "palette": [],
    }


def _role_apparent_age(name: str, role: object) -> str:
    text = f"{_ascii_lower(name)} {_ascii_lower(role)}"
    child_terms = ("menina", "menino", "garota", "garoto", "crianca", "criança")
    elder_terms = ("avó", "avô", "avoa", "avo", "idoso", "idosa", "senhor", "senhora")
    if any(term in text.split() for term in child_terms):
        return "criança"
    if any(term in text.split() for term in ("adolescente", "jovem")):
        return "adolescente"
    if any(term in text.split() for term in elder_terms):
        return "pessoa idosa"
    if any(term in text.split() for term in ("mae", "pai", "guarda", "medica", "medico")):
        return "pessoa adulta"
    # Fallback obrigatório: idade é estrutural para a continuidade visual —
    # sem ela o provedor de imagem "adivinha" a faixa etária a cada geração.
    return "pessoa adulta"


def _temporal_variant_age(name: str) -> str:
    """Idade derivada da nota temporal embutida no nome (ex.: "Menino João")."""
    normalized = _ascii_lower(name)
    child_terms = ("menina", "menino", "garota", "garoto", "crianca", "criança")
    if any(term in normalized.split() for term in child_terms):
        return "criança"
    if any(term in normalized.split() for term in ("adolescente", "jovem")):
        return "adolescente"
    if any(term in normalized.split() for term in ("idoso", "idosa", "velho", "velha")):
        return "pessoa idosa"
    return ""


def _age_stage(apparent_age: object) -> str:
    """Faixa etária a partir do texto de idade aparente ("oito anos", "criança").

    A extração LLM costuma gravar a idade escrita por extenso ou em número
    ("idade": "oito anos", "10 anos", "16 anos") — comparar só com a palavra
    "criança" deixava meninas de 8 anos receberem 1,65 m e 66 kg de adulto.
    """
    key = _ascii_lower(apparent_age)
    age_match = re.search(r"\b(\d{1,2})\s+anos?\b", key)
    if age_match is not None:
        years = int(age_match.group(1))
        if years <= 12:
            return "child"
        if years <= 17:
            return "adolescent"
    # Idade escrita por extenso ("oito anos", "dez anos") é comum na
    # extração LLM; cobrir 1-12 garante a detecção de crianças.
    _AGE_NUMBER_WORDS = {
        "um": 1,
        "uma": 1,
        "dois": 2,
        "duas": 2,
        "tres": 3,
        "quatro": 4,
        "cinco": 5,
        "seis": 6,
        "sete": 7,
        "oito": 8,
        "nove": 9,
        "dez": 10,
        "onze": 11,
        "doze": 12,
    }
    word_match = re.search(r"\b([a-z]+)\s+anos?\b", key)
    if word_match is not None:
        word_years = _AGE_NUMBER_WORDS.get(word_match.group(1))
        if word_years is not None:
            return "child"
    child_terms = ("crianca", "menina", "menino", "garota", "garoto", "bebe")
    if any(term in key.split() for term in child_terms):
        return "child"
    if any(term in key.split() for term in ("adolescente", "jovem", "teen")):
        return "adolescent"
    return ""


# A extração LLM preenche campos visuais com placeholders quando não sabe
# ("footwear": "não especificado"). Copiá-los para o prompt canônico produz
# instruções sem sentido ("deve calçar não especificado") — tratá-los como
# ausência e cair no fallback contextual do figurino.
_PLACEHOLDER_VALUE_RE = re.compile(
    r"(?i)^\s*(?:nao\s+especificad[oa]|n[aã]o\s+especificad[oa]|nenhum|nada|"
    r"desconhecid[oa]|indeterminad[oa]|indefinid[oa]|not\s+specified|\w*n/a\w*|"
    r"cal[cç]ados?\s+adequados?|cal[cç]ados?\s+com[uu]ns|roupa\s+discreta|"
    r"vestu[áa]rio\s+cotidiano|corte\s+neutro)\s*[.:!]?\.?\s*$"
)


def _is_placeholder_visual_value(value: object) -> bool:
    return bool(_PLACEHOLDER_VALUE_RE.match(str(value or "")))


def _character_prompt_subject(name: object, gender: object) -> str:
    clean_name = concise_prompt_fragment(_prompt_text(name), 10)
    first_word = _ascii_lower(clean_name).split()[0] if clean_name else ""
    if first_word in {"homem", "menino", "garoto", "senhor"}:
        return f"um {clean_name.casefold()}"
    if first_word in {"mulher", "menina", "garota", "senhora"}:
        return f"uma {clean_name.casefold()}"
    if clean_name.casefold() == "personagem":
        gender_key = _ascii_lower(gender)
        if "fem" in gender_key or "mulher" in gender_key:
            return "uma mulher"
        if "masc" in gender_key or "homem" in gender_key:
            return "um homem"
        return "uma pessoa"
    return clean_name


def _human_height(value: object) -> str:
    raw = _prompt_text(value).strip()
    if not raw:
        return ""
    normalized = raw.casefold().replace("metros", "").replace("metro", "").strip()
    number_match = re.fullmatch(r"(\d{3})(?:\s*cm)?", normalized)
    if number_match:
        centimeters = int(number_match.group(1))
        return f"{centimeters // 100},{centimeters % 100:02d} m"
    decimal_match = re.fullmatch(r"(\d)[.,](\d{1,2})(?:\s*m)?", normalized)
    if decimal_match:
        decimals = decimal_match.group(2).ljust(2, "0")
        return f"{decimal_match.group(1)},{decimals} m"
    return raw


ROLE_APPROPRIATE_OUTFITS = (
    # (marcadores de função, figurino, institucional).
    # "institucional" = uniforme que existe desde o início do século XX e
    # sobrevive a praticamente qualquer época (mecânico, enfermagem, polícia,
    # medicina, cozinha). Os flexíveis (professor, crítico, artesão) cedem
    # lugar ao figurino de época quando o contexto da história é histórico —
    # um professor dos anos 1920 não usa "camisa azul e sarja bege" de hoje.
    (
        ("mecanico", "mecanica", "oficina", "automotivo", "automotiva"),
        "macacão azul-marinho de sarja com manchas de graxa sobre camiseta cinza",
        True,
    ),
    (
        ("enfermeiro", "enfermeira", "enfermagem"),
        "uniforme hospitalar verde-claro com crachá branco preso ao peito",
        True,
    ),
    (
        ("medico", "medica", "doutor", "doutora", "cirurgiao", "cirurgia"),
        "jaleco branco sobre camisa azul-clara e calça social cinza",
        True,
    ),
    (
        ("guarda", "policial", "seguranca", "vigilante"),
        "camisa cáqui de manga longa, calça cargo marrom e cinto preto de serviço",
        True,
    ),
    (
        ("cozinheiro", "cozinheira", "chef"),
        "dólmã branca de algodão, avental preto na cintura e calça xadrez escura",
        True,
    ),
    (
        ("professor", "professora", "docente"),
        "camisa azul de algodão, calça de sarja bege e cinto marrom",
        False,
    ),
    (
        ("restaurador", "restauradora", "artesao", "artesa", "atelier", "atelie"),
        "avental bege manchado de tinta sobre camisa branca e calça de sarja marrom",
        False,
    ),
    (
        ("critico", "critica", "curador", "curadora", "galerista"),
        "blazer preto bem cortado sobre camisa branca e calça social grafite",
        False,
    ),
)

FEMININE_EVERYDAY_OUTFITS = (
    "camiseta azul-marinho de algodão e calça jeans de lavagem escura",
    "blusa branca de algodão e calça jeans azul-clara",
    "camiseta vinho de algodão e calça de sarja bege",
    "vestido estampado de algodão na altura do joelho",
    "blusa de tricô cinza e calça preta de tecido",
)

MASCULINE_EVERYDAY_OUTFITS = (
    "camiseta cinza de algodão e calça jeans azul-escura",
    "camisa xadrez azul e calça de sarja cáqui",
    "camiseta preta de algodão e calça jeans de lavagem média",
    "camisa polo verde-oliva e calça de sarja cinza",
    "camiseta branca de algodão e calça jeans preta",
)

NEUTRAL_EVERYDAY_OUTFITS = (
    "camisa branca de algodão e calça de sarja cinza-escura",
    "camiseta cinza de algodão e calça jeans azul-escura",
    "camisa azul-clara de algodão e calça de sarja bege",
)

FEMININE_EVERYDAY_FOOTWEAR = (
    "tênis branco de couro com sola baixa",
    "sapatilhas pretas de couro",
    "tênis cinza de tecido com sola baixa",
)

MASCULINE_EVERYDAY_FOOTWEAR = (
    "tênis preto de lona com cadarços",
    "sapatos marrons de couro",
    "tênis branco de lona com cadarços",
)

# Pools de figurino por ÉPOCA detectada no contexto canônico da história.
# O fallback determinístico é a última rede de segurança (extração e direção
# de arte LLM podem falhar em preencher o figurino): sem isso, o cotidiano
# moderno (jeans + tênis) invadia histórias de época e ambientes onde essas
# peças não existem (relato do usuário, 2026-09). Pools descrevem peças
# concretas e evitam citar calçados para que o calçado próprio seja mantido.
ERA_WARDROBE_POOLS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "pre1960": (
        (
            "vestido de chita florido na altura da canela com mangas compridas e avental de bolso",
            "saia longa de lã, blusa de gola alta fechada e casaco curto de tecido grosso",
            "vestido de corte reto com cintura marcada, mangas três-quartos e broche discreto",
        ),
        (
            "terno de lã de duas peças com colete, camisa branca de gola fechada e chapéu fedora",
            "camisa de algodão com suspensórios, calça de brim de cintura alta e boné de aba reta",
            "jaleco de trabalho com botões, calça de tecido grosso e chapéu de palha de aba larga",
        ),
        (
            "sapatos de couro de salto baixo com fivela",
            "botas de couro de cano médio com cadarços",
        ),
    ),
    "futuristic": (
        (
            "macacão técnico de fibra sintética com gola alta e fechos embutidos",
            "jaqueta térmica de corte minimalista com calça de tecido técnico e cinto utilitário",
        ),
        (
            "macacão técnico de fibra sintética com gola alta e fechos embutidos",
            "jaqueta térmica de corte minimalista com calça de tecido técnico e cinto utilitário",
        ),
        ("botas técnicas de sola grossa com fechos embutidos",),
    ),
}

# Famílias de figurino por AMBIENTE detectado no contexto (aplicadas quando
# a época é contemporânea ou indefinida). Cada família evita peças modernas
# que destoem do ambiente (ex.: jeans/tênis em zona rural tradicional).
CONTEXT_WARDROBE_FAMILIES: tuple[
    tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        (
            "fazenda",
            "sitio",
            "roca",
            "lavoura",
            "colheita",
            "sertao",
            "plantacao",
            "cafe",
            "pecuaria",
            "boiada",
            "zona rural",
            "zona da mata",
            "vau",
        ),
        (
            "vestido simples de algodão grosso com mangas compridas e lenço na cabeça",
            "blusa de chita, saia larga de tecido rústico e avental manchado de terra",
        ),
        (
            "camisa de algodão cru gasta com suspensórios e calça de tecido grosso remendada",
            "camisa xadrez de franela, colete de lã e chapéu de palha",
        ),
        ("botas de couro gastas com sola grossa", "chinelos de couro artesanais"),
    ),
    (
        ("praia", "litoral", "pescador", "pesca", "porto", "marina", "maré"),
        (
            "vestido leve de algodão claro com mangas curtas e chapéu de palha",
            "blusa branca de linho e saia curta de tecido leve",
        ),
        (
            "camisa listrada leve de algodão, calça curta de brim e boné de pescador",
            "regata clara de algodão com calça de brim dobrada na canela",
        ),
        ("sandálias de couro simples", "chinelos de borracha"),
    ),
    (
        ("neve", "nevando", "nevasca", "inverno rigoroso", "frio intenso", "montanha", "geada"),
        (
            "casaco de lã comprido com cachecol grosso e luvas de tricô sobre blusa de gola alta",
            "parka acolchoada com capuz sobre calça de tecido encorpado",
        ),
        (
            "casaco de lã pesado com gola alta de tricô e cachecol enrolado",
            "parka impermeável acolchoada sobre camisa de flanela",
        ),
        ("botas de couro forradas com sola de borracha",),
    ),
    (
        ("favela", "periferia", "cortico", "conjunto habitacional", "morro "),
        (
            "blusa básica de algodão com calça jeans resistente e boné",
            "vestido simples de tecido fino com acessórios discretos",
        ),
        (
            "camiseta básica com bermuda de brim e boné",
            "camisa de time gasta com calça jeans resistente",
        ),
        ("chinelos de borracha simples", "tênis de lona desbotado"),
    ),
    (
        (
            "mansao",
            "palacete",
            "milion",
            "aristocr",
            "alta sociedade",
            "magnata",
            "banqueiro",
            "luxo",
        ),
        (
            "vestido de seda de corte sofisticado com joias discretas",
            "conjunto de alfaiataria em blazer com calça de linho fina",
        ),
        (
            "terno escuro de alfaiataria impecável com camisa de seda",
            "blazer de linho com camisa clara e relógio de pulso clássico",
        ),
        # Pool neutro: o mesmo contexto veste homens e mulheres, e "scarpins"
        # num homem destoa do figurino (calçado deve ser congruente com a roupa).
        ("sapatos de couro polido de sola fina", "sapatos sociais de couro preto"),
    ),
    (
        ("guerra", "exercito", "soldado", "batalha", "trincheira", "quartel", "farda"),
        ("farda cáqui de campanha com insígnias discretas e cinto de equipamento",),
        ("farda cáqui de campanha com insígnias discretas e cinto de equipamento",),
        ("botas militares de cano alto com cadarços",),
    ),
    (
        ("convento", "mosteiro", "seminario", "freira", "padre ", "clero"),
        ("hábito religioso de tecido simples com cordão na cintura e crucifixo discreto",),
        ("túnica sóbria de mangas compridas com cordão na cintura",),
        ("sandálias de couro simples",),
    ),
)


def _era_wardrobe_key(story_context: str) -> str:
    """Detecta a família de época no contexto canônico da história."""
    context = _ascii_lower(story_context)
    if any(
        marker in context
        for marker in (
            "1920",
            "1930",
            "1940",
            "1950",
            "anos 20",
            "anos 30",
            "anos 40",
            "anos 50",
            "seculo xix",
            "século xix",
            "seculo 19",
            "século 19",
            "seculo xx",
            "século xx",
            "seculo 20",
            "século 20",
            "colonial",
            "imperio",
            "império",
            "vitoriano",
            "vitoriana",
            "era industrial",
            "velho oeste",
            "cangaço",
            "cangaco",
            "medieval",
            "renascenca",
            "renascença",
        )
    ):
        return "pre1960"
    if any(
        marker in context
        for marker in (
            "2077",
            "2087",
            "2099",
            "futuro",
            "futurista",
            "distopia",
            "distópica",
            "nave espacial",
            "espaconave",
            "colonia espacial",
            "colônia espacial",
            "cyberpunk",
            " cibernetico",
            " cibernético",
            "inteligencia artificial",
            "inteligência artificial",
        )
    ):
        return "futuristic"
    # Contemporânea ou época não detectada: sem pool de época (o cotidiano
    # moderno é o fallback plausível).
    return ""


def _role_appropriate_outfit(
    name: str, role: object, gender: object, story_context: str = ""
) -> str:
    normalized_role = _ascii_lower(repair_portuguese_mojibake(role))
    era_key = _era_wardrobe_key(story_context)
    for markers, outfit, institutional in ROLE_APPROPRIATE_OUTFITS:
        if any(marker in normalized_role for marker in markers):
            # Uniformes institucionais (médico, policial, mecânico) existem
            # em qualquer época. Figurinos flexíveis (professor, crítico,
            # artesão) cedem ao figurino de época em contextos históricos
            # ou futuristas — um professor dos anos 1920 não usa sarja
            # bege de hoje.
            if institutional or era_key == "":
                return outfit
            break

    normalized_gender = _ascii_lower(repair_portuguese_mojibake(gender))
    if "fem" in normalized_gender or "mulher" in normalized_gender:
        return _contextual_wardrobe_choice(name, "feminine", story_context)
    if "masc" in normalized_gender or "homem" in normalized_gender:
        return _contextual_wardrobe_choice(name, "masculine", story_context)
    return _contextual_wardrobe_choice(name, "neutral", story_context)


def _contextual_wardrobe_choice(name: str, gender_key: str, story_context: str) -> str:
    """Figurino de fallback por família de ambiente e época da história.

    Ordem: família de AMBIENTE (fazenda, litoral, neve...) tem prioridade sobre
    a época contemporânea; sem ambiente batido, época histórica/futurista usa
    o pool de época. Só cai no cotidiano moderno quando o contexto não indica
    nada — exatamente onde jeans/tênis são plausíveis.
    """
    context = _ascii_lower(story_context)
    for markers, feminine, masculine, _footwear in CONTEXT_WARDROBE_FAMILIES:
        if any(marker in context for marker in markers):
            pool = feminine if gender_key == "feminine" else masculine
            return _stable_character_choice(name, pool, 8)
    era_key = _era_wardrobe_key(story_context)
    if era_key in ERA_WARDROBE_POOLS:
        feminine, masculine, _footwear = ERA_WARDROBE_POOLS[era_key]
        pool = feminine if gender_key == "feminine" else masculine
        return _stable_character_choice(name, pool, 8)
    # Época contemporânea ou indefinida: cotidiano moderno é plausível.
    pools = {
        "feminine": FEMININE_EVERYDAY_OUTFITS,
        "masculine": MASCULINE_EVERYDAY_OUTFITS,
    }
    return _stable_character_choice(name, pools.get(gender_key, NEUTRAL_EVERYDAY_OUTFITS), 8)


def _contextual_footwear_choice(name: str, gender_key: str, story_context: str) -> str:
    """Calçado de fallback coerente com ambiente/época da história."""
    context = _ascii_lower(story_context)
    for markers, _feminine, _masculine, footwear in CONTEXT_WARDROBE_FAMILIES:
        if any(marker in context for marker in markers):
            return _stable_character_choice(name, footwear, 9)
    era_key = _era_wardrobe_key(story_context)
    if era_key in ERA_WARDROBE_POOLS:
        _feminine, _masculine, footwear = ERA_WARDROBE_POOLS[era_key]
        return _stable_character_choice(name, footwear, 9)
    footwear_pools = {
        "feminine": FEMININE_EVERYDAY_FOOTWEAR,
    }
    return _stable_character_choice(
        name, footwear_pools.get(gender_key, MASCULINE_EVERYDAY_FOOTWEAR), 9
    )


def _role_appropriate_footwear(
    name: str, role: object, gender: object, story_context: str = ""
) -> str:
    normalized_role = _ascii_lower(role)
    if any(term in normalized_role for term in ("mecan", "oficina", "guarda", "policial")):
        return "botas pretas de segurança com cadarços"
    if any(term in normalized_role for term in ("enferm", "medic", "hospital")):
        return "tênis branco fechado com sola de borracha"
    if any(term in normalized_role for term in ("cozinh", "chef")):
        return "sapatos pretos antiderrapantes"
    if any(term in normalized_role for term in ("professor", "docente")):
        return "sapatos marrons de couro sem brilho"
    normalized_gender = _ascii_lower(gender)
    if "fem" in normalized_gender or "mulher" in normalized_gender:
        return _contextual_footwear_choice(name, "feminine", story_context)
    return _contextual_footwear_choice(name, "masculine", story_context)


# A extração/design às vezes descreve em distinctive_features e nos olhos
# MOMENTOS da história ("trava no meio da cozinha ao entrar", "úmidos ao
# cantar", "olhar seguindo a melodia") em vez de traços físicos permanentes.
# O prompt canônico é uma ficha física: ação e enredo não entram (decisão de
# produto 2026-09). A cauda temporal ("ao amanhecer") é removida antes do
# teste para preservar o traço físico real da cláusula ("barro nas barras da
# calça" sobrevive sem "ao amanhecer").
_TEMPORAL_TAIL_RE = re.compile(
    r"\s+ao\s+(?:amanhecer|anoitecer|entardecer|meio-dia|cair da noite|"
    r"in[ií]cio da noite|raio do dia|crep[uú]sculo)\b",
    flags=re.IGNORECASE,
)

_NARRATIVE_ACTION_RE = re.compile(
    r"\b(?:ao|quando|enquanto)\s+\S+(?:ar|er|ir)\b"
    r"|\b\S+(?:ando|endo|indo)\b"
    r"|\b(?:entra|sai|chega|canta|chora|sorri|corre|caminha|imita|segura"
    r"|carrega|aponta|fala|grita|senta|levanta|toca|dirige|escreve|l[eê]"
    r"|respira|aperta|sussurra|reza|medita|trava|treme|observa|beija|abra[çc]a"
    r"|fuma|bebe|dorme|acorda|espera|procura|segue|pinta|corta|costura"
    r"|conserta|atende)\b",
    flags=re.IGNORECASE,
)


# Estilo fotográfico obrigatório em TODO prompt canônico de personagem:
# sem ele a Meta ora produz render de animação 3D, ora foto real para o
# MESMO personagem (relato do usuário, 2026-09). Constante própria para que
# os testes e o builder nunca diverjam da frase exata.
PHOTO_STYLE_DETAIL = "a imagem deve ser fotorrealista, como uma fotografia real de uma pessoa"


def _physical_traits_fragment(value: object, *, eyes: bool = False) -> str:
    """Mantém apenas cláusulas de traço físico em campos do perfil visual.

    Divide o texto em cláusulas (vírgula/ponto-e-vírgula), remove caudas
    temporais e descarta cláusulas de ação/momento da história. Usado em
    distinctive_features e olhos — os campos que a extração mais contamina
    com o que a pessoa FAZ em vez de como ela é.
    """
    text = re.sub(r"\s+", " ", _prompt_text(value)).strip(" ,;.")
    if not text:
        return ""
    kept: list[str] = []
    for clause in re.split(r"[;,]", text):
        clause = _TEMPORAL_TAIL_RE.sub("", clause).strip(" ,;:.")
        if not clause:
            continue
        if _NARRATIVE_ACTION_RE.search(clause):
            continue
        if eyes and _ascii_lower(clause).startswith("olhar"):
            continue
        kept.append(clause)
    return ", ".join(kept)


def _character_profile(raw: object, story_context: str = "") -> dict:
    raw = _profile_mapping(raw)
    name = str(raw.get("name") or "Personagem")
    identity_base_name, identity_variant_note = _character_identity_base(name)
    role = _short_text(_first_value(raw, "role", "funcao", "função"), "personagem", 120)
    # A idade vem ANTES dos defaults: variantes temporais no nome ("Menino
    # João", "Jovem Maria") definem a faixa etária e evitam que altura/peso
    # de adulto sejam derivados para menores.
    temporal_age = _temporal_variant_age(name)
    apparent_age = _first_value(
        raw,
        "apparent_age",
        "idade_aparente",
        "idade",
        fallback=temporal_age or _role_apparent_age(name, role),
    )
    gender = _character_gender(
        _first_value(raw, "gender", "gênero", "sexo", fallback=""),
        name,
        role,
        str(apparent_age),
    )
    defaults = _character_visual_defaults(identity_base_name, gender, apparent_age)
    origin = _first_value(raw, "origin", "origem", "nacionalidade", fallback=defaults["origin"])
    # Crianças e adolescentes não recebem altura/peso nem da extração LLM:
    # a idade escrita no prompt basta (relato do usuário, 2026-09).
    is_minor = _age_stage(apparent_age) in {"child", "adolescent"}
    height_cm = (
        ""
        if is_minor
        else _first_value(raw, "height_cm", "altura_cm", "altura", fallback=defaults["height_cm"])
    )
    weight_kg = (
        ""
        if is_minor
        else _first_value(raw, "weight_kg", "peso_kg", "peso", fallback=defaults["weight_kg"])
    )
    body_type = _first_value(
        raw, "body_type", "tipo_fisico", "corpo", fallback=defaults["body_type"]
    )
    face_shape = _first_value(
        raw,
        "face_shape",
        "formato_rosto",
        "rosto",
        fallback=defaults["face_shape"],
    )
    skin_tone = _first_value(
        raw, "skin_tone", "tom_de_pele", "pele", fallback=defaults["skin_tone"]
    )
    eyes = _first_value(raw, "eyes", "olhos", fallback=defaults["eyes"])
    hair = _first_value(raw, "hair", "cabelo", fallback=defaults["hair"])
    # O fallback de figurino/calçado é sensível ao contexto canônico (época,
    # ambiente, classe): sem ele, histórias de época recebem jeans e tênis
    # quando a extração e a direção de arte LLM falham em preencher o campo.
    raw_outfit = _first_value(
        raw,
        "base_outfit",
        "figurino_base",
        "roupa",
        "figurino",
        fallback="",
    )
    base_outfit = (
        raw_outfit
        if raw_outfit and not _is_placeholder_visual_value(raw_outfit)
        else (
            defaults["base_outfit"]
            or _role_appropriate_outfit(identity_base_name, role, gender, story_context)
        )
    )
    # Placeholder da extração LLM ("não especificado") conta como ausência:
    # cai no fallback contextual em vez de virar "deve calçar não especificado".
    raw_footwear = _first_value(
        raw,
        "footwear",
        "calcados",
        "calçados",
        "sapatos",
        fallback="",
    )
    footwear = (
        raw_footwear
        if raw_footwear and not _is_placeholder_visual_value(raw_footwear)
        else (
            defaults["footwear"]
            or _role_appropriate_footwear(identity_base_name, role, gender, story_context)
        )
    )
    palette = _first_value(
        raw, "palette", "paleta", "paleta_de_cores", fallback=defaults["palette"]
    )
    personality = _first_value(
        raw,
        "personality",
        "personalidade",
        fallback="",
    )
    distinctive_features = _first_value(
        raw,
        "distinctive_features",
        "caracteristicas_marcantes",
        "características_marcantes",
        "accessories",
        "acessorios",
        "acessórios",
        fallback="",
    )
    narrative_profile = {
        "name": name,
        "role": role,
        "personality": personality,
        "arc": _first_value(raw, "arc", "arco", fallback=""),
        "voice": raw.get("voice", "voz humana calorosa"),
    }
    # Campos visuais recebem APENAS traços físicos: o que o personagem faz na
    # história (ação/enredo) não entra no prompt canônico — ele descreve COMO
    # a pessoa é, não o que ela vive.
    filtered_features = _physical_traits_fragment(distinctive_features)
    filtered_eyes = _physical_traits_fragment(eyes, eyes=True)
    subject = _character_prompt_subject(name, gender)
    introduction = f"Crie a imagem de {subject}"
    details: list[str] = []
    if filtered_features:
        details.append(f"com {concise_prompt_fragment(filtered_features, 14)}")
    gender_key = _ascii_lower(gender)
    generic_subject = _ascii_lower(subject).startswith(("um homem", "uma mulher"))
    age_text = _prompt_text(apparent_age)
    is_child = _age_stage(age_text) == "child"
    if not generic_subject:
        if "fem" in gender_key or "mulher" in gender_key:
            details.append("deve ser uma mulher" if not is_child else "deve ser uma menina")
        elif "masc" in gender_key or "homem" in gender_key:
            details.append("deve ser um homem" if not is_child else "deve ser um menino")
        elif "nao especificado" in _ascii_lower(gender):
            # Gênero desconhecido: descrição neutra em vez de silêncio.
            details.append("deve ser uma pessoa")
    if height_cm:
        details.append(f"deve ter {_human_height(height_cm)} de altura")
    if weight_kg:
        weight = re.sub(r"\s*(?:kg|quilos?)\s*$", "", _prompt_text(weight_kg), flags=re.I)
        details.append(f"deve pesar aproximadamente {weight} kg")
    if hair:
        details.append(f"deve ter cabelo {_clean_prompt_fragment(hair, ('cabelo',))}")
    if skin_tone:
        details.append(
            f"seu tom de pele deve ser {_clean_prompt_fragment(skin_tone, ('pele', 'tom de pele'))}"
        )
    if filtered_eyes:
        details.append(f"deve ter olhos {_clean_prompt_fragment(filtered_eyes, ('olhos',))}")
    if base_outfit:
        details.append(f"deve usar {_clean_prompt_fragment(base_outfit, ('figurino', 'roupa'))}")
    outfit_key = _ascii_lower(base_outfit)
    mentions_footwear = bool(
        re.search(
            r"\b(?:tenis|sapatos?|botas?|sandalias?|chinelos?|sapatenis?|calcados?)\b",
            outfit_key,
        )
    )
    if footwear and not mentions_footwear:
        details.append(f"deve calçar {_prompt_text(footwear)}")
    if face_shape:
        details.append(f"deve ter {_clean_prompt_fragment(face_shape, ('face',))}")
    if body_type:
        body_text = _prompt_text(body_type)
        if _ascii_lower(body_text).startswith("porte"):
            details.append(f"deve ter {body_text}")
        else:
            details.append(f"deve ter corpo {_clean_prompt_fragment(body_text, ('corpo',))}")
    if apparent_age:
        details.append(f"deve aparentar {_prompt_text(apparent_age)}")

    def _assemble_prompt(items: list[str]) -> str:
        return f"{introduction}, {', '.join(items)}." if items else f"{introduction}."

    # Estilo fotográfico é ESTRUTURAL: sem ele a Meta ora produz render de
    # animação 3D, ora foto real para o MESMO personagem (relato do usuário,
    # 2026-09). Entra SEMPRE no prompt canônico, fora do orçamento do corpo —
    # nunca pode ser cortado no meio pelo limite de palavras.
    budget = CHARACTER_PROMPT_MAX_WORDS - len(PHOTO_STYLE_DETAIL.split())
    kept = list(details)
    if prompt_word_count(_assemble_prompt(kept)) > budget:
        # Descarta do FIM os detalhes não estruturais até caber, em vez de
        # deixar o truncamento rasgar o último detalhe no meio (ex.: "deve
        # aparentar."). Gênero, idade aparente e calçado são estruturais e
        # não cedem — o calçado é exigência de continuidade visual do
        # usuário (2026-09): "deve calçar" não pode sumir do prompt.
        for index in range(len(kept) - 1, -1, -1):
            if prompt_word_count(_assemble_prompt(kept)) <= budget:
                break
            if not kept[index].startswith(("deve ser ", "deve aparentar ", "deve calçar ")):
                kept.pop(index)
        while prompt_word_count(_assemble_prompt(kept)) > budget and kept:
            kept.pop()
    body = balanced_visual_prompt([_assemble_prompt(kept)], max_words=budget)
    canonical_prompt = ensure_portuguese_prompt_text(f"{body} {PHOTO_STYLE_DETAIL}")

    return {
        "permanent_id": raw.get(
            "id",
            # SEC-06: sha1 não-criptográfico (derivador determinístico de ID).
            f"char_{hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()[:8]}",
        ),
        "name": name,
        "identity_base_name": identity_base_name,
        "identity_variant_note": identity_variant_note,
        "role": role,
        "gender": gender,
        "origin": origin,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "apparent_age": apparent_age,
        "body_type": body_type,
        "face_shape": face_shape,
        "skin_tone": skin_tone,
        "eyes": eyes,
        "hair": hair,
        "base_outfit": base_outfit,
        "footwear": footwear,
        "palette": palette,
        "voice": raw.get("voice", "voz humana calorosa"),
        "personality": personality,
        "distinctive_features": distinctive_features,
        "arc": narrative_profile["arc"],
        "scene_numbers": raw.get("scene_numbers", []),
        "evidence_text": raw.get("evidence_text", []),
        "importance": raw.get("importance", ""),
        "narrative_profile": narrative_profile,
        "asset_kind": "character",
        "canonical_prompt": canonical_prompt,
    }
