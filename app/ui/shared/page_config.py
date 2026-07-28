import re
from dataclasses import dataclass

from nicegui import ui

BRAND_MARK_URL = "/ui-assets/favicon.png"
DEFAULT_STORY_DURATION_MINUTES = 5.0
STORY_DURATION_OPTIONS = [5, 10, 15, 20, 25]
IDEA_COUNT_OPTIONS = list(range(1, 11))
BLOCKING_DIALOG_PROPS = "persistent no-esc-dismiss no-backdrop-dismiss"
UI_GENERATION_TIMEOUT_SECONDS = 300
SETTINGS_DATA_URL = "/settings?tab=data"
IDEA_TITLE_PREFIX_RE = re.compile(r"^\s*ideia\s+\d+\s*[:\-â€“]\s*", re.IGNORECASE)

IDEA_GENRES = [
    "AÃ§Ã£o",
    "AnimaÃ§Ã£o",
    "Aventura",
    "ComÃ©dia",
    "Drama",
    "Fantasia",
    "FicÃ§Ã£o CientÃ­fica",
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
        "Defina tema, pÃºblico, emoÃ§Ã£o, duraÃ§Ã£o e objetivo do vÃ­deo.",
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
        "Crie o texto base, duraÃ§Ã£o alvo, cenas e planos estruturados.",
        "Gerar roteiro",
        "description",
    ),
    ProductionStep(
        "visual",
        "Visual",
        "Crie fichas canÃ´nicas e referÃªncias visuais aprovÃ¡veis.",
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
        "Gere clipes reais por plano, com jobs, assets e custos rastreados.",
        "Gerar clipes",
        "movie",
    ),
    ProductionStep(
        "finalization",
        "FinalizaÃ§Ã£o",
        "Monte a timeline final e exporte os clipes selecionados.",
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
    ("VÃ­deo", "video"),
]

STEP_LOADING_COPY = {
    "ideas": ("Gerando ideias", "A IA estÃ¡ criando temas, gÃªneros e emoÃ§Ãµes."),
    "script": ("Gerando roteiro", "A IA estÃ¡ escrevendo o roteiro e separando cenas."),
    "visual": (
        "Gerando prompts visuais",
        "A IA estÃ¡ criando personagens, locais e objetos para revisÃ£o.",
    ),
    "storyboard": ("Gerando storyboard", "A IA estÃ¡ criando quadros, planos e animatic."),
    "video": ("Preparando vÃ­deo", "A IA estÃ¡ verificando prompts e deixando os clipes prontos."),
    "finalization": ("Finalizando projeto", "A IA esta montando timeline final e export."),
    "quality": ("Revisando qualidade", "A IA estÃ¡ checando continuidade e riscos."),
}


def settings_tab_key(value: object) -> str:
    normalized = re.sub(r"[\s_-]+", "-", str(value or "").strip().casefold())
    if normalized in {"data", "dados"}:
        return "data"
    if normalized in {"ai", "ia", "inteligencia-artificial"}:
        return "ai"
    return "profile"


def clean_idea_title(value: object, fallback: str = "HistÃ³ria sem tÃ­tulo") -> str:
    title = str(value or "").strip()
    title = IDEA_TITLE_PREFIX_RE.sub("", title).strip()
    return title or fallback


def friendly_ai_error(exc: BaseException) -> str:
    text = str(exc).strip()
    normalized = text.lower()
    if isinstance(exc, TimeoutError) or "demorou mais" in normalized or "timed out" in normalized:
        return (
            "O modelo de IA demorou demais para responder. Tente novamente ou escolha "
            "um modelo de texto mais estÃ¡vel nas configuraÃ§Ãµes."
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
            "NÃ£o foi possÃ­vel conectar ao provedor de IA. Verifique a internet, a chave "
            "do OpenRouter e tente novamente."
        )
    if "json" in normalized:
        return (
            "O modelo respondeu fora do formato esperado pela aplicaÃ§Ã£o. Tente novamente "
            "ou use um modelo com melhor suporte a JSON estruturado."
        )
    if "api_key" in normalized or "api key" in normalized or "chave" in normalized:
        return "A chave da IA parece ausente ou invÃ¡lida. Confira as configuraÃ§Ãµes de IA."
    if text:
        return text[:500]
    return "A IA nÃ£o respondeu ou retornou um erro inesperado. Tente novamente."


def show_ai_error_popup(
    message: str | None = None,
    *,
    title: str = "Falha na IA",
    details: str | None = None,
) -> None:
    safe_message = (
        message or "A IA nÃ£o retornou nenhuma resposta. Tente novamente ou escolha outro modelo."
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
                with ui.expansion("Detalhes tÃ©cnicos").classes("w-full text-sm text-[#9aa19b]"):
                    ui.label(details.strip()[:1200]).classes("whitespace-pre-wrap")
            with ui.row().classes("w-full justify-end"):
                ui.button("Entendi", on_click=dialog.close).props("unelevated no-caps").classes(
                    "acid-bg rounded-xl font-semibold"
                )
        dialog.open()
    except RuntimeError:
        ui.notify(f"{title}: {safe_message}", color="negative", timeout=9000, close_button=True)
