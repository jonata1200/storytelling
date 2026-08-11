import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from nicegui import core, ui

from app.config.api_keys import (
    CreationChannel,
    format_missing_api_key_message,
    missing_api_key_messages_for_channels,
    missing_api_key_messages_for_creation_step,
)
from app.visual_bible.prompts import default_views_for

logger = logging.getLogger(__name__)

BRAND_MARK_URL = "/ui-assets/favicon.png"
DEFAULT_STORY_DURATION_MINUTES = 5.0
STORY_DURATION_OPTIONS = [5]
IDEA_COUNT_OPTIONS = list(range(1, 11))
BLOCKING_DIALOG_PROPS = "persistent no-esc-dismiss no-backdrop-dismiss"
UI_GENERATION_TIMEOUT_SECONDS = 300
UI_SCRIPT_PROGRESS_POLL_INTERVALS = (2.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0)
SETTINGS_DATA_URL = "/settings?tab=data"
IDEA_TITLE_PREFIX_RE = re.compile(r"^\s*ideia\s+\d+\s*[:-]\s*", re.IGNORECASE)

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


@dataclass(frozen=True)
class LoadingStatusItem:
    label: str


@dataclass(frozen=True)
class LoadingStatus:
    step_key: str
    completed: int
    total: int
    unit_label: str
    created: tuple[LoadingStatusItem, ...]
    missing: tuple[LoadingStatusItem, ...]
    now: str | None = None

    @property
    def ratio(self) -> float:
        return min(max(self.completed / self.total, 0.0), 1.0) if self.total else 0.0

    def as_text(self) -> str:
        created_text = (
            ", ".join(item.label for item in self.created) if self.created else "nada ainda"
        )
        missing_text = (
            ", ".join(item.label for item in self.missing)
            if self.missing
            else "nada nesta etapa; a IA esta validando e atualizando a tela"
        )
        lines = [self.now] if self.now else []
        lines.extend(
            [
                f"Criado: {created_text}.",
                f"Falta criar: {missing_text}.",
            ]
        )
        return "\n".join(lines)


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
        "Gere duas opções fortes e escolha a melhor promessa emocional.",
        "Gerar ideias",
        "tips_and_updates",
    ),
    ProductionStep(
        "script",
        "Roteiro",
        "Crie o texto base e a duração alvo do filme.",
        "Gerar roteiro",
        "description",
    ),
    ProductionStep(
        "scenes",
        "Cenas",
        "Separe o roteiro em cenas e planos prontos para vídeo.",
        "Gerar cenas",
        "splitscreen",
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
        "Vídeo",
        "Gere clipes reais por plano, com jobs, assets e custos rastreados.",
        "Gerar clipes",
        "movie",
    ),
    ProductionStep(
        "finalization",
        "Finalização",
        "Monte a timeline final e exporte os clipes selecionados.",
        "Finalizar",
        "auto_awesome_motion",
    ),
    ProductionStep(
        "dubbing",
        "Dublagem",
        "Duble o export base com ElevenLabs, reaproveitando jobs e arquivos já criados.",
        "Gerar dublagem",
        "graphic_eq",
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
    ("Biblioteca Visual", "assets"),
    ("Storyboard", "storyboard"),
    ("Vídeo", "video"),
    ("Finalização", "finalization"),
    ("Dublagem", "dubbing"),
]

STEP_LOADING_COPY = {
    "ideas": ("Gerando ideias", "A IA está criando temas, gêneros e emoções."),
    "script": ("Gerando roteiro", "A IA está escrevendo o roteiro cinematográfico."),
    "scenes": ("Gerando cenas", "A IA está separando o roteiro em cenas e planos."),
    "visual": (
        "Gerando prompts visuais",
        "A IA está criando personagens, locais e objetos para revisão.",
    ),
    "storyboard": ("Gerando storyboard", "A IA está criando quadros, planos e animatic."),
    "video": ("Preparando vídeo", "A IA está verificando prompts e deixando os clipes prontos."),
    "dubbing": ("Gerando dublagem", "A IA está preparando o export base e enviando ao ElevenLabs."),
    "finalization": ("Finalizando projeto", "A IA está montando timeline final e export."),
    "quality": ("Revisando qualidade", "A IA está checando continuidade e riscos."),
}


ACTION_LOADING_STEPS = {
    "generate_ideas": "ideas",
    "generate_script": "script",
    "revise_script": "script",
    "generate_assets": "visual",
    "approve_visual_prompt": "visual",
    "approve_storyboard_prompt": "storyboard",
    "generate_storyboard": "storyboard",
    "generate_video": "video",
    "generate_dubbing": "dubbing",
    "generate_finalization": "finalization",
    "run_quality": "quality",
}

ACTION_LOADING_TITLES = {
    "revise_script": "Revisando roteiro",
    "approve_visual_prompt": "Aprovando prompts visuais",
    "approve_storyboard_prompt": "Aprovando prompts de storyboard",
    "generate_video": "Gerando clipes",
}

ACTION_NOW_COPY = {
    "generate_ideas": "Agora: criando ideias narrativas.",
    "generate_script": "Agora: criando ou completando o roteiro.",
    "revise_script": "Agora: revisando o roteiro e preservando o que ja existe.",
    "generate_assets": "Agora: criando prompts visuais e preparando referencias.",
    "approve_visual_prompt": "Agora: aprovando os prompts visuais solicitados.",
    "approve_storyboard_prompt": (
        "Agora: aprovando os prompts de storyboard solicitados."
    ),
    "generate_storyboard": "Agora: criando quadros de storyboard e animatic.",
    "generate_video": "Agora: criando clipes de video a partir do storyboard.",
    "generate_dubbing": "Agora: preparando dublagem para os clipes criados.",
    "generate_finalization": "Agora: montando timeline final e export.",
    "run_quality": "Agora: revisando continuidade e riscos de qualidade.",
}

VISUAL_REFERENCE_VIEW_COUNTS = {
    "characters": len(default_views_for("character")),
    "locations": len(default_views_for("location")),
    "props": len(default_views_for("prop")),
}


def _safe_count(counts: dict[str, Any], key: str) -> int:
    try:
        return max(int(counts.get(key, 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _count_text(count: int, singular: str, plural: str) -> str:
    label = singular if count == 1 else plural
    return f"{count} {label}"


def _append_count(
    parts: list[str],
    counts: dict[str, Any],
    key: str,
    singular: str,
    plural: str,
) -> None:
    value = _safe_count(counts, key)
    if value > 0:
        parts.append(_count_text(value, singular, plural))


def _expected_visual_references(counts: dict[str, Any]) -> int:
    return sum(
        _safe_count(counts, key) * view_count
        for key, view_count in VISUAL_REFERENCE_VIEW_COUNTS.items()
    )


def _created_items_for_step(step_key: str, counts: dict[str, Any]) -> list[str]:
    created: list[str] = []
    if step_key in {"ideas", "script"}:
        _append_count(created, counts, "ideas", "ideia", "ideias")
    if step_key in {"script", "visual", "storyboard"}:
        _append_count(created, counts, "scripts", "roteiro", "roteiros")
    if step_key == "storyboard":
        _append_count(created, counts, "scenes", "cena", "cenas")
        _append_count(created, counts, "shots", "plano", "planos")
    if step_key in {"visual", "storyboard"}:
        _append_count(created, counts, "characters", "personagem", "personagens")
        _append_count(created, counts, "locations", "local", "locais")
        _append_count(created, counts, "props", "objeto", "objetos")
        _append_count(
            created,
            counts,
            "visual_refs",
            "referencia visual",
            "referencias visuais",
        )
    if step_key in {"storyboard", "video", "dubbing", "finalization"}:
        _append_count(
            created,
            counts,
            "frames",
            "quadro de storyboard",
            "quadros de storyboard",
        )
        _append_count(created, counts, "animatics", "animatic", "animatics")
    if step_key in {"video", "dubbing", "finalization", "quality"}:
        _append_count(created, counts, "clips", "clipe de video", "clipes de video")
    if step_key in {"dubbing", "finalization", "quality"}:
        _append_count(created, counts, "dubbing_jobs", "job de dublagem", "jobs de dublagem")
    if step_key in {"finalization", "quality"}:
        _append_count(created, counts, "exports", "export final", "exports finais")
    if step_key == "quality":
        created.append(
            _count_text(
                _safe_count(counts, "qa_issues"),
                "alerta de qualidade registrado",
                "alertas de qualidade registrados",
            )
        )
    return created


def _missing_items_for_step(step_key: str, counts: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    scripts = _safe_count(counts, "scripts")
    scenes = _safe_count(counts, "scenes")
    shots = _safe_count(counts, "shots")
    frames = _safe_count(counts, "frames")
    clips = _safe_count(counts, "clips")
    visual_refs = _safe_count(counts, "visual_refs")
    expected_visual_refs = _expected_visual_references(counts)

    if step_key == "ideas" and _safe_count(counts, "ideas") <= 0:
        missing.append("ideia narrativa")
    if step_key in {"script", "visual", "storyboard"}:
        if scripts <= 0:
            missing.append("roteiro")
    if step_key == "storyboard":
        if scenes <= 0 or shots <= 0:
            missing.append("cenas e planos")
    if step_key in {"visual", "storyboard"}:
        if _safe_count(counts, "characters") <= 0:
            missing.append("prompts de personagens")
        if _safe_count(counts, "locations") <= 0:
            missing.append("prompts de locais")
        if _safe_count(counts, "props") <= 0:
            missing.append("prompts de objetos")
        if expected_visual_refs > visual_refs:
            pending_refs = expected_visual_refs - visual_refs
            missing.append(
                _count_text(
                    pending_refs,
                    "referencia visual",
                    "referencias visuais",
                )
            )
    if step_key == "storyboard":
        if shots > 0 and frames < shots:
            pending_frames = shots - frames
            missing.append(
                _count_text(
                    pending_frames,
                    "quadro de storyboard",
                    "quadros de storyboard",
                )
            )
        if frames > 0 and _safe_count(counts, "animatics") <= 0:
            missing.append("animatic")
    if step_key in {"video", "dubbing", "finalization"}:
        if frames <= 0:
            missing.append("storyboard")
        elif clips < frames:
            pending_clips = frames - clips
            missing.append(_count_text(pending_clips, "clipe de video", "clipes de video"))
    if step_key == "dubbing" and _safe_count(counts, "dubbing_jobs") <= 0:
        missing.append("dublagem")
    if step_key == "finalization" and _safe_count(counts, "exports") <= 0:
        missing.append("export final")
    if step_key == "quality":
        missing.append("revisao de qualidade atualizada")
    return missing


def _progress_for_step(step_key: str, counts: dict[str, Any]) -> tuple[int, int, str]:
    if step_key == "ideas":
        ideas = _safe_count(counts, "ideas")
        return min(ideas, max(ideas, 1)), max(ideas, 1), "ideia"

    if step_key == "script":
        completed = 0
        if _safe_count(counts, "ideas") > 0:
            completed += 1
        if _safe_count(counts, "scripts") > 0:
            completed += 1
        return completed, 2, "etapa"

    if step_key == "visual":
        expected_refs = _expected_visual_references(counts)
        if expected_refs > 0:
            return min(_safe_count(counts, "visual_refs"), expected_refs), expected_refs, "imagem"
        completed_groups = sum(
            1
            for key in ("characters", "locations", "props")
            if _safe_count(counts, key) > 0
        )
        return completed_groups, 3, "grupo"

    if step_key == "storyboard":
        shots = _safe_count(counts, "shots")
        frames = _safe_count(counts, "frames")
        animatics = _safe_count(counts, "animatics")
        if shots > 0:
            include_animatic = frames > 0 or animatics > 0
            total = shots + (1 if include_animatic else 0)
            completed = min(frames, shots) + (1 if animatics > 0 else 0)
            return completed, max(total, 1), "item"
        return min(frames, max(frames, 1)), max(frames, 1), "quadro"

    if step_key == "video":
        frames = _safe_count(counts, "frames")
        total = max(frames, 1)
        return min(_safe_count(counts, "clips"), total), total, "clipe"

    if step_key == "dubbing":
        return min(_safe_count(counts, "dubbing_jobs"), 1), 1, "job"

    if step_key == "finalization":
        return min(_safe_count(counts, "exports"), 1), 1, "export"

    if step_key == "quality":
        return 0, 1, "revisao"

    return 0, 1, "item"


def loading_status(
    step_key: str,
    counts: dict[str, Any] | None = None,
    *,
    now: str | None = None,
) -> LoadingStatus:
    count_map = counts if isinstance(counts, dict) else {}
    completed, total, unit_label = _progress_for_step(step_key, count_map)
    return LoadingStatus(
        step_key=step_key,
        completed=completed,
        total=max(total, 1),
        unit_label=unit_label,
        created=tuple(
            LoadingStatusItem(item) for item in _created_items_for_step(step_key, count_map)
        ),
        missing=tuple(
            LoadingStatusItem(item) for item in _missing_items_for_step(step_key, count_map)
        ),
        now=now,
    )


def loading_status_message(
    step_key: str,
    counts: dict[str, Any] | None = None,
    *,
    now: str | None = None,
) -> str:
    return loading_status(step_key, counts, now=now).as_text()


def step_loading_copy(
    step_key: str,
    counts: dict[str, Any] | None = None,
) -> tuple[str, LoadingStatus]:
    title, _message = STEP_LOADING_COPY.get(
        step_key,
        ("Executando etapa", "A IA esta trabalhando nesta etapa."),
    )
    return title, loading_status(step_key, counts)


def action_loading_copy(
    action: str,
    counts: dict[str, Any] | None = None,
) -> tuple[str, LoadingStatus]:
    step_key = ACTION_LOADING_STEPS.get(action, "script")
    title = ACTION_LOADING_TITLES.get(
        action,
        STEP_LOADING_COPY.get(step_key, ("Executando", ""))[0],
    )
    return title, loading_status(
        step_key,
        counts,
        now=ACTION_NOW_COPY.get(action),
    )


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
    if (
        "safety violation" in normalized
        or "blocked due to safety" in normalized
        or "prohibited use policy" in normalized
        or "violated google" in normalized
        or "filtered out" in normalized
    ):
        return (
            "O provedor de imagem bloqueou esta geracao por politica de seguranca. "
            "Revise o prompt do ativo, removendo descricoes sensiveis de sofrimento, "
            "risco medico ou vulnerabilidade, e tente gerar novamente."
        )
    if "http 404" in normalized and (
        "not found for account" in normalized or "modelo selecionado" in normalized
    ):
        return (
            "O modelo escolhido não está disponível para a sua chave ou conta do provider. "
            "Escolha outro modelo nas configurações ou habilite esse modelo no provider."
        )
    if (
        "network" in normalized
        or "connection" in normalized
        or "dns" in normalized
        or "temporarily unavailable" in normalized
    ):
        return (
            "Não foi possível conectar ao provedor de IA. Verifique a internet, a chave "
            "do provider configurado e tente novamente."
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


def is_deleted_ui_context_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "client this element belongs to has been deleted" in text
        or "parent element this slot belongs to has been deleted" in text
    )


def safe_close_ui_element(element: object) -> None:
    close = getattr(element, "close", None)
    if not callable(close):
        return
    try:
        close()
    except RuntimeError as exc:
        if not is_deleted_ui_context_error(exc):
            raise
        logger.warning("Could not close UI element because the page context was removed.")


def script_progress_poll_interval(attempt: int) -> float:
    """Intervalo do proximo poll de progresso da UI, com backoff progressivo."""
    intervals = UI_SCRIPT_PROGRESS_POLL_INTERVALS
    return intervals[min(max(attempt, 0), len(intervals) - 1)]


def safe_notify(message: str, **kwargs: Any) -> None:
    try:
        ui.notify(message, **kwargs)
    except RuntimeError as exc:
        if not is_deleted_ui_context_error(exc):
            raise
        logger.warning("Could not notify because the page context was removed.")


COMPLETION_SOUND_JS = """
(() => {
  try {
    if (window.localStorage?.getItem('storytellingCompletionSound') === 'off') return;
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const context = window.__storytellingCompletionAudioContext || new AudioContext();
    window.__storytellingCompletionAudioContext = context;
    const now = context.currentTime;
    const gain = context.createGain();
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.09, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.42);
    gain.connect(context.destination);
    [523.25, 659.25, 783.99].forEach((frequency, index) => {
      const oscillator = context.createOscillator();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(frequency, now + index * 0.08);
      oscillator.connect(gain);
      oscillator.start(now + index * 0.08);
      oscillator.stop(now + 0.38 + index * 0.04);
    });
  } catch (_) {}
})();
"""


def play_completion_sound() -> None:
    if core.loop is None:
        return
    try:
        ui.run_javascript(COMPLETION_SOUND_JS)
    except (AssertionError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and not is_deleted_ui_context_error(exc):
            raise
        logger.warning("Could not play completion sound because the page context was removed.")


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
        with (
            ui.dialog() as dialog,
            ui.card().classes("entity-card rounded-2xl p-6 w-[min(560px,92vw)] gap-4"),
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
        try:
            ui.notify(f"{title}: {safe_message}", color="negative", timeout=9000, close_button=True)
        except RuntimeError as notify_exc:
            if not is_deleted_ui_context_error(notify_exc):
                raise
            logger.warning("Could not show AI error because the page context was removed.")


def show_missing_api_keys_popup(messages: Iterable[str]) -> bool:
    message = format_missing_api_key_message(messages)
    if not message:
        return False
    show_ai_error_popup(message, title="Chaves de API ausentes")
    return True


def block_if_missing_api_keys_for_step(step: str) -> bool:
    return show_missing_api_keys_popup(missing_api_key_messages_for_creation_step(step))


def block_if_missing_api_keys_for_channels(channels: Iterable[CreationChannel]) -> bool:
    return show_missing_api_keys_popup(missing_api_key_messages_for_channels(channels))
