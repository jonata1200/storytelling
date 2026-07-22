import re
from dataclasses import dataclass

from nicegui import ui

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
        "Defina tema, público, emoção, duração e objetivo do vídeo.",
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
        "Crie o texto base, duração alvo, cenas e planos estruturados.",
        "Gerar roteiro",
        "description",
    ),
    ProductionStep(
        "visual",
        "Visual",
        "Crie fichas canônicas e referências visuais aprováveis.",
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
        "Finalização",
        "Crie narração final, legendas, timeline final e exportação.",
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
    "ideas": ("Gerando ideias", "A IA está criando temas, gêneros e emoções."),
    "script": ("Gerando roteiro", "A IA está escrevendo o roteiro e separando cenas."),
    "visual": (
        "Gerando prompts visuais",
        "A IA está criando personagens, locais e objetos para revisão.",
    ),
    "storyboard": ("Gerando storyboard", "A IA está criando quadros, planos e animatic."),
    "video": ("Preparando vídeo", "A IA está verificando prompts e deixando os clipes prontos."),
    "finalization": ("Finalizando projeto", "A IA está montando narração, legendas e export."),
    "quality": ("Revisando qualidade", "A IA está checando continuidade e riscos."),
}


def settings_tab_key(value: object) -> str:
    normalized = re.sub(r"[\s_-]+", "-", str(value or "").strip().casefold())
    if normalized in {"data", "dados"}:
        return "data"
    if normalized in {"ai", "ia", "inteligencia-artificial"}:
        return "ai"
    return "profile"


def clean_idea_title(value: object, fallback: str = "História sem título") -> str:
    title = str(value or "").strip()
    title = IDEA_TITLE_PREFIX_RE.sub("", title).strip()
    return title or fallback


def friendly_ai_error(exc: BaseException) -> str:
    text = str(exc).strip()
    normalized = text.lower()
    if isinstance(exc, TimeoutError) or "demorou mais" in normalized or "timed out" in normalized:
        return (
            "O modelo de IA demorou demais para responder. Tente novamente ou escolha "
            "um modelo de texto mais estável nas configurações."
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
            "Não foi possível conectar ao provedor de IA. Verifique a internet, a chave "
            "do OpenRouter e tente novamente."
        )
    if "json" in normalized:
        return (
            "O modelo respondeu fora do formato esperado pela aplicação. Tente novamente "
            "ou use um modelo com melhor suporte a JSON estruturado."
        )
    if "api_key" in normalized or "api key" in normalized or "chave" in normalized:
        return "A chave da IA parece ausente ou inválida. Confira as configurações de IA."
    if text:
        return text[:500]
    return "A IA não respondeu ou retornou um erro inesperado. Tente novamente."


def show_ai_error_popup(
    message: str | None = None,
    *,
    title: str = "Falha na IA",
    details: str | None = None,
) -> None:
    safe_message = (
        message or "A IA não retornou nenhuma resposta. Tente novamente ou escolha outro modelo."
    )
    try:
        with ui.dialog() as dialog, ui.card().classes(
            "entity-card rounded-2xl p-6 w-[min(560px,92vw)] gap-4"
        ):
            with ui.row().classes("items-start gap-3 w-full"):
                ui.icon("error_outline").classes("text-3xl text-red-300 shrink-0")
                with ui.column().classes("gap-1 flex-1"):
                    ui.label(title).classes("brand-type text-2xl font-bold text-red-100")
                    ui.label(safe_message).classes("text-sm text-[#d8dbd8] leading-6")
            if details and details.strip() and details.strip() != safe_message:
                with ui.expansion("Detalhes técnicos").classes("w-full text-sm text-[#9aa19b]"):
                    ui.label(details.strip()[:1200]).classes("whitespace-pre-wrap")
            with ui.row().classes("w-full justify-end"):
                ui.button("Entendi", on_click=dialog.close).props("unelevated no-caps").classes(
                    "acid-bg rounded-xl font-semibold"
                )
        dialog.open()
    except RuntimeError:
        ui.notify(f"{title}: {safe_message}", color="negative", timeout=9000, close_button=True)
