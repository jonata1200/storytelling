from app.visual_bible.character_profiles import PHOTO_STYLE_DETAIL
from app.visual_bible.profiles import _character_profile, _location_profile
from app.visual_bible.prompt_balance import (
    CHARACTER_PROMPT_MAX_WORDS,
    CHARACTER_PROMPT_MIN_WORDS,
    LOCATION_PROMPT_MAX_WORDS,
    LOCATION_PROMPT_MIN_WORDS,
    contains_mojibake,
    prompt_word_count,
    repair_portuguese_mojibake,
)


def test_character_profile_uses_role_appropriate_outfit_when_evidence_is_missing() -> None:
    profile = _character_profile({"name": "Guarda", "role": "guarda"})

    assert profile["apparent_age"] == "pessoa adulta"
    assert profile["origin"] == ""
    assert profile["height_cm"]
    assert profile["weight_kg"]
    assert profile["hair"]
    assert profile["eyes"]
    assert profile["skin_tone"]
    assert profile["base_outfit"] == (
        "camisa cáqui de manga longa, calça cargo marrom e cinto preto de serviço"
    )
    assert profile["footwear"] == "botas pretas de segurança com cadarços"
    assert profile["palette"] == []
    assert profile["canonical_prompt"].startswith("Crie a imagem de Guarda")
    assert "deve usar camisa cáqui" in profile["canonical_prompt"]
    assert "deve calçar botas pretas" in profile["canonical_prompt"]


def test_professional_uniform_is_fixed_across_characters() -> None:
    first = _character_profile({"name": "Carlos", "role": "policial", "gender": "masculino"})
    second = _character_profile({"name": "Marcos", "role": "policial", "gender": "masculino"})
    mechanic_a = _character_profile(
        {"name": "Clara", "role": "protagonista e mecânica", "gender": "feminino"}
    )
    mechanic_b = _character_profile({"name": "Martha", "role": "mecânica", "gender": "feminino"})
    nurse = _character_profile({"name": "Joana", "role": "enfermeira", "gender": "feminino"})

    assert first["base_outfit"] == second["base_outfit"]
    assert first["footwear"] == second["footwear"]
    assert mechanic_a["base_outfit"] == mechanic_b["base_outfit"]
    assert "macacão azul-marinho" in mechanic_a["base_outfit"]
    assert "botas pretas de segurança" in mechanic_a["canonical_prompt"]
    assert nurse["base_outfit"] == (
        "uniforme hospitalar verde-claro com crachá branco preso ao peito"
    )
    assert nurse["base_outfit"] in nurse["canonical_prompt"]


def test_everyday_outfit_uses_character_gender_without_professional_context() -> None:
    feminine = _character_profile({"name": "Clara", "role": "protagonista", "gender": "feminino"})
    masculine = _character_profile({"name": "Lucas", "role": "protagonista", "gender": "masculino"})

    assert feminine["base_outfit"] in {
        "camiseta azul-marinho de algodão e calça jeans de lavagem escura",
        "blusa branca de algodão e calça jeans azul-clara",
        "camiseta vinho de algodão e calça de sarja bege",
        "vestido estampado de algodão na altura do joelho",
        "blusa de tricô cinza e calça preta de tecido",
    }
    assert feminine["base_outfit"] in feminine["canonical_prompt"]
    assert masculine["base_outfit"] in {
        "camiseta cinza de algodão e calça jeans azul-escura",
        "camisa xadrez azul e calça de sarja cáqui",
        "camiseta preta de algodão e calça jeans de lavagem média",
        "camisa polo verde-oliva e calça de sarja cinza",
        "camiseta branca de algodão e calça jeans preta",
    }
    assert masculine["base_outfit"] in masculine["canonical_prompt"]
    assert "vestuário cotidiano" not in feminine["canonical_prompt"]
    assert "corte neutro" not in masculine["canonical_prompt"]


def test_everyday_outfits_vary_between_characters() -> None:
    names = ("Clara", "Lucas", "Marta", "Pedro", "Helena", "Rafael", "Beatriz", "Miguel")
    feminine_outfits = {
        _character_profile({"name": name, "role": "protagonista", "gender": "feminino"})[
            "base_outfit"
        ]
        for name in names
    }
    masculine_outfits = {
        _character_profile({"name": name, "role": "protagonista", "gender": "masculino"})[
            "base_outfit"
        ]
        for name in names
    }

    assert len(feminine_outfits) >= 2
    assert len(masculine_outfits) >= 2
    for name in names:
        profile = _character_profile({"name": name, "role": "protagonista", "gender": "feminino"})
        repeat = _character_profile(
            {"name": name, "role": "protagonista", "gender": "feminino"}
        )
        assert profile["base_outfit"] == repeat["base_outfit"]


def test_character_and_location_prompts_have_balanced_visual_density() -> None:
    character = _character_profile(
        {
            "name": "Clara",
            "role": "protagonista e mecÃ¢nica",
            "gender": "feminino",
            "apparent_age": "35 anos",
            "body_type": "estatura mÃ©dia e corpo esguio",
            "face_shape": "rosto oval com traÃ§os marcantes",
            "skin_tone": "morena clara",
            "eyes": "castanhos atentos",
            "hair": "preto ondulado na altura dos ombros",
            "base_outfit": "camisa bege, calÃ§a escura e botas discretas",
            "palette": "tons terrosos e azul-petrÃ³leo",
            "personality": "reservada, observadora e determinada",
        }
    )
    location = _location_profile(
        {
            "name": "Cozinha da casa",
            "description": "cozinha modesta brasileira, estreita, funcional e silenciosa",
            "layout": "bancada junto Ã  parede, mesa pequena ao centro e janela acima da pia",
            "materials": "granito gasto, madeira clara e azulejos antigos",
            "palette": "bege, verde desbotado e marrom",
            "lighting": "luz fria da manhÃ£ entrando lateralmente",
        }
    )

    character_words = prompt_word_count(character["canonical_prompt"])
    location_words = prompt_word_count(location["canonical_prompt"])

    assert CHARACTER_PROMPT_MIN_WORDS <= character_words <= CHARACTER_PROMPT_MAX_WORDS
    assert LOCATION_PROMPT_MIN_WORDS <= location_words <= LOCATION_PROMPT_MAX_WORDS
    assert character["canonical_prompt"].startswith("Crie a imagem de Clara")
    assert "deve usar camisa bege" in character["canonical_prompt"]
    assert location["canonical_prompt"].startswith("Crie a imagem de Cozinha da casa")
    assert "Organize o espaço com" in location["canonical_prompt"]
    assert "Os materiais visíveis devem incluir" in location["canonical_prompt"]
    assert "proporções anatômicas" not in character["canonical_prompt"]
    assert "continuidade visual" not in location["canonical_prompt"]


def test_character_prompt_reads_like_a_human_physical_description() -> None:
    profile = _character_profile(
        {
            "name": "Homem vendado",
            "role": "personagem",
            "gender": "masculino",
            "height_cm": "180",
            "weight_kg": "78",
            "hair": "preto",
            "skin_tone": "parda",
            "eyes": "verdes",
            "distinctive_features": "uma venda da cor branca",
            "base_outfit": "camisa branca desbotada e calça jeans desbotada",
            "footwear": "sapatênis rasgado",
        }
    )

    prompt = profile["canonical_prompt"]
    assert prompt.startswith("Crie a imagem de um homem vendado")
    assert "com uma venda da cor branca" in prompt
    assert "deve ter 1,80 m de altura" in prompt
    assert "deve pesar aproximadamente 78 kg" in prompt
    assert "deve ter cabelo preto" in prompt
    assert "seu tom de pele deve ser parda" in prompt
    assert "deve ter olhos verdes" in prompt
    assert "deve usar camisa branca desbotada e calça jeans desbotada" in prompt
    assert "deve calçar sapatênis rasgado" in prompt


def test_location_prompt_caps_excessive_narrative_prose() -> None:
    verbose = " ".join(f"detalhe{i}" for i in range(200))
    profile = _location_profile(
        {
            "name": "EstaÃ§Ã£o",
            "description": verbose,
            "layout": verbose,
            "materials": verbose,
            "palette": verbose,
            "lighting": verbose,
        }
    )

    assert prompt_word_count(profile["canonical_prompt"]) <= LOCATION_PROMPT_MAX_WORDS


def test_location_prompt_uses_concrete_details_instead_of_generic_placeholders() -> None:
    profile = _location_profile({"name": "Oficina mecânica"})
    prompt = profile["canonical_prompt"]

    assert prompt.startswith("Crie a imagem de Oficina mecânica")
    assert "bancadas nas laterais" in prompt
    assert "concreto manchado" in prompt
    assert "azul-petróleo" in prompt
    assert "luminárias industriais" in prompt
    assert "elevador automotivo" in prompt
    assert "conforme o roteiro" not in prompt
    assert "geografia coerente" not in prompt


def test_portuguese_mojibake_is_repaired_before_prompt_generation() -> None:
    broken = (
        "Presen\u00c3\u00a7a e express\u00c3\u00a3o \u00c2\u00b7 curto \u00c2\u00b7 "
        "80\u00e2\u20ac\u201c120"
    )

    repaired = repair_portuguese_mojibake(broken)

    assert repaired == "Presen\u00e7a e express\u00e3o \u00b7 curto \u00b7 80\u2013120"
    assert contains_mojibake(broken) is True
    assert contains_mojibake(repaired) is False


def test_saved_mojibake_fields_do_not_reach_canonical_prompt() -> None:
    profile = _character_profile(
        {
            "name": "Clara",
            "role": "protagonista",
            "distinctive_features": "cicatriz discreta e presen\u00c3\u00a7a marcante",
        }
    )

    assert "cicatriz discreta e presen\u00e7a marcante" in profile["canonical_prompt"]
    assert contains_mojibake(profile["canonical_prompt"]) is False


def test_character_prompt_always_states_gender_and_age() -> None:
    # Nomes sem terminação decisiva e sem gênero explícito antes ficavam
    # sem gênero e sem idade no prompt ("Elias" real do projeto).
    profile = _character_profile({"name": "Elias", "role": "pescador"})
    prompt = profile["canonical_prompt"]

    assert "deve ser um homem" in prompt
    assert "deve aparentar" in prompt
    assert profile["gender"] == "personagem masculino"
    assert profile["apparent_age"] == "pessoa adulta"

    # Sobrenome como último token: "Ramos" termina em "s" -> masculino.
    detective = _character_profile({"name": "Detetive Ramos", "role": "policial"})
    assert "deve ser um homem" in detective["canonical_prompt"]

    # Título + nome próprio feminino: o título não decide o gênero.
    grandmother = _character_profile({"name": "Vovó Zilda", "role": "avó"})
    assert grandmother["gender"] == "personagem feminino"
    assert "deve ser uma mulher" in grandmother["canonical_prompt"]
    assert grandmother["apparent_age"] == "pessoa idosa"

    # Nome totalmente ambíguo recebe descrição neutra em vez de silêncio.
    neutral = _character_profile({"name": "Sky", "role": "protagonista"})
    assert "deve ser uma pessoa" in neutral["canonical_prompt"]
    assert "deve aparentar" in neutral["canonical_prompt"]


def test_child_variant_gets_child_age_measures_and_wording() -> None:
    # Antes: "Menino João" recebia "deve ser um homem", 1,72 m e 81 kg.
    profile = _character_profile({"name": "Menino João", "role": "garoto de 8 anos"})
    prompt = profile["canonical_prompt"]

    assert profile["apparent_age"] == "criança"
    assert "deve ser um menino" in prompt
    assert "deve aparentar criança" in prompt
    assert "1,72 m" not in prompt
    assert "81 kg" not in prompt
    assert float(profile["height_cm"]) < 140
    assert float(profile["weight_kg"]) < 45

    girl = _character_profile({"name": "Menina Alice", "role": "criança perdida"})
    assert girl["gender"] == "personagem feminino"
    assert "deve ser uma menina" in girl["canonical_prompt"]
    assert girl["apparent_age"] == "criança"


def test_temporal_variant_gets_age_from_name_without_adult_measures() -> None:
    # Antes: "Jovem Maria" recebia defaults masculinos (1,80 m / 86 kg).
    profile = _character_profile({"name": "Jovem Maria", "role": "versão jovem"})
    prompt = profile["canonical_prompt"]

    assert profile["gender"] == "personagem feminino"
    assert "deve ser uma mulher" in prompt
    assert profile["apparent_age"] == "adolescente"
    assert "deve aparentar adolescente" in prompt
    assert "1,80 m" not in prompt
    assert "86 kg" not in prompt


def test_explicit_gender_and_age_always_win_over_fallbacks() -> None:
    profile = _character_profile(
        {"name": "Ruth", "role": "enfermeira", "gender": "feminino", "apparent_age": "45 anos"}
    )

    assert profile["gender"] == "personagem feminino"
    assert profile["apparent_age"] == "45 anos"
    assert "deve aparentar 45 anos" in profile["canonical_prompt"]


def test_canonical_prompt_is_always_photorealistic() -> None:
    # Sem instrução de estilo a Meta ora devolve render de animação 3D, ora
    # foto real para o MESMO personagem — o estilo fotográfico é estrutural e
    # fica no prompt canônico (fora do orçamento do corpo, nunca truncado).
    minimal = _character_profile({"name": "Elias", "role": "pescador"})
    verbose = _character_profile(
        {
            "name": "Clara",
            "role": "protagonista",
            "distinctive_features": " ".join(f"detalhe{i}" for i in range(60)),
            "base_outfit": "camisa bege, calça escura e botas discretas",
        }
    )

    for profile in (minimal, verbose):
        prompt = profile["canonical_prompt"]
        assert prompt.endswith(PHOTO_STYLE_DETAIL)
        assert "fotorrealista" in prompt
        assert prompt_word_count(prompt) <= CHARACTER_PROMPT_MAX_WORDS


def test_narrative_actions_never_enter_the_canonical_prompt() -> None:
    # Caso real (A Última Falante): a extração descreve em distinctive_features
    # e olhos MOMENTOS da história em vez de traços físicos permanentes.
    profile = _character_profile(
        {
            "name": "Menina",
            "role": "garota",
            "distinctive_features": "canta a melodia baixinho sem errar nota, imitando Zefa",
            "eyes": "castanhos grandes e curiosos, olhar seguindo a melodia",
        }
    )
    prompt = profile["canonical_prompt"]

    assert "canta" not in prompt
    assert "imitando" not in prompt
    assert "seguindo a melodia" not in prompt
    assert "deve ter olhos castanhos grandes e curiosos" in prompt

    # Traço físico real com cauda temporal sobrevive sem a cauda.
    physical = _character_profile(
        {
            "name": "Rute",
            "role": "professora",
            "distinctive_features": "barro nas barras da calça ao amanhecer",
        }
    )
    assert "barro nas barras da calça" in physical["canonical_prompt"]
    assert "ao amanhecer" not in physical["canonical_prompt"]

    # Evidência só-de-ação: o campo sai inteiro em vez de vazar enredo.
    action_only = _character_profile(
        {
            "name": "Cida",
            "role": "protagonista",
            "distinctive_features": "trava no meio da cozinha ao entrar",
        }
    )
    assert "com trava" not in action_only["canonical_prompt"]
    assert "trava" not in action_only["canonical_prompt"]
