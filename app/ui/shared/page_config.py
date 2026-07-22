import re
from dataclasses import dataclass

BRAND_MARK_URL = "/ui-assets/favicon.png"
DEFAULT_STORY_DURATION_MINUTES = 5.0
STORY_DURATION_OPTIONS = [5, 10, 15, 20, 25]
IDEA_COUNT_OPTIONS = list(range(1, 11))
BLOCKING_DIALOG_PROPS = "persistent no-esc-dismiss no-backdrop-dismiss"
UI_GENERATION_TIMEOUT_SECONDS = 150
SETTINGS_DATA_URL = "/settings?tab=data"
IDEA_TITLE_PREFIX_RE = re.compile(r"^\s*ideia\s+\d+\s*[:\-–]\s*", re.IGNORECASE)

IDEA_GENRES = [
    "Ação",
    "Animação",
    "Aventura",
    "Comédia",
    "Drama",
    "Fantasia",
    "Ficção Científica",
    "Romance",
    "Suspense (Thriller)",
    "Terror (ou Horror)",
]


@dataclass(frozen=True)
class ProductionStep:
    key: str
    title: str
    description: str
    action_label: str
    icon: str


PRODUCTION_STEPS = [
    ProductionStep(
        "briefing",
        "Briefing",
        "Defina tema, publico, emocao, duracao e objetivo do video.",
        "Criar novo projeto",
        "edit_note",
    ),
    ProductionStep(
        "ideas",
        "Ideias",
        "Gere tres caminhos narrativos e escolha a melhor promessa emocional.",
        "Gerar ideias",
        "tips_and_updates",
    ),
    ProductionStep(
        "script",
        "Roteiro",
        "Crie o texto base, duracao alvo, cenas e planos estruturados.",
        "Gerar roteiro",
        "description",
    ),
    ProductionStep(
        "visual",
        "Visual",
        "Crie fichas canonicas e referencias visuais aprovaveis.",
        "Gerar visual",
        "palette",
    ),
    ProductionStep(
        "storyboard",
        "Storyboard",
        "Transforme planos em quadros, animatic e timeline preliminar.",
        "Gerar storyboard",
        "view_comfy",
    ),
    ProductionStep(
        "video",
        "Video",
        "Gere clipes mock por plano, com jobs, assets e custos rastreados.",
        "Gerar clipes",
        "movie",
    ),
    ProductionStep(
        "finalization",
        "Finalizacao",
        "Crie narracao final, legendas, timeline final e exportacao.",
        "Finalizar",
        "auto_awesome_motion",
    ),
    ProductionStep(
        "quality",
        "Qualidade",
        "Rode continuity ledger, alertas, score e observabilidade do projeto.",
        "Rodar QA",
        "verified",
    ),
]

WORKSPACE_TABS = [
    ("Roteiro", "script"),
    ("Personagens", "assets"),
    ("Storyboard", "storyboard"),
    ("Vídeo", "video"),
]

STEP_LOADING_COPY = {
    "ideas": ("Gerando ideias", "A IA esta criando temas, generos e emocoes."),
    "script": ("Gerando roteiro", "A IA esta escrevendo o roteiro e separando cenas."),
    "visual": (
        "Gerando prompts visuais",
        "A IA esta criando personagens, locais e objetos para revisao.",
    ),
    "storyboard": ("Gerando storyboard", "A IA esta criando quadros, planos e animatic."),
    "video": ("Preparando video", "A IA esta verificando prompts e deixando os clipes prontos."),
    "finalization": ("Finalizando projeto", "A IA esta montando narracao, legendas e export."),
    "quality": ("Revisando qualidade", "A IA esta checando continuidade e riscos."),
}


def settings_tab_key(value: object) -> str:
    normalized = re.sub(r"[\s_-]+", "-", str(value or "").strip().casefold())
    if normalized in {"data", "dados"}:
        return "data"
    if normalized in {"ai", "ia", "inteligencia-artificial"}:
        return "ai"
    return "profile"


def clean_idea_title(value: object, fallback: str = "Historia sem titulo") -> str:
    title = str(value or "").strip()
    title = IDEA_TITLE_PREFIX_RE.sub("", title).strip()
    return title or fallback


def friendly_ai_error(exc: BaseException) -> str:
    text = str(exc).strip()
    normalized = text.lower()
    if isinstance(exc, TimeoutError) or "demorou mais" in normalized or "timed out" in normalized:
        return (
            "O modelo de IA demorou demais para responder. Tente novamente ou escolha "
            "um modelo de texto mais estavel nas configuracoes."
        )
    if "rate limit" in normalized or "429" in normalized or "resourceexhausted" in normalized:
        return (
            "O provedor de IA recusou a chamada por limite de uso. Aguarde alguns minutos "
            "ou troque para um modelo com mais disponibilidade."
        )
    if "openrouter" in normalized and (
        "network" in normalized
        or "connection" in normalized
        or "dns" in normalized
        or "temporarily unavailable" in normalized
    ):
        return (
            "Nao foi possivel conectar ao provedor de IA. Verifique a internet, a chave "
            "do OpenRouter e tente novamente."
        )
    if "json" in normalized:
        return (
            "O modelo respondeu fora do formato esperado pela aplicacao. Tente novamente "
            "ou use um modelo com melhor suporte a JSON estruturado."
        )
    if "api_key" in normalized or "api key" in normalized or "chave" in normalized:
        return "A chave da IA parece ausente ou invalida. Confira as configuracoes de IA."
    if text:
        return text[:500]
    return "A IA nao respondeu ou retornou um erro inesperado. Tente novamente."
