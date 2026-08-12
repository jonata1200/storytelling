from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.model_settings import llm_provider_for_task
from app.generation.project_agent_intent import (
    _requests_full_script_regeneration,
)
from app.generation.project_agent_types import (
    ACTION_PROGRESS_MESSAGES,
    ProjectChatAction,
    ProjectChatIntent,
)
from app.generation.project_agent_visual import (
    _normalize_match_text,
    _requests_regeneration,
    _requests_visual_prompt_approval,
)
from app.generation.service import run_structured_generation
from app.video_generation.continuous import CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS

CONTINUOUS_VIDEO_WORKFLOW_MODE = "continuous_fast"


def classify_project_chat_action(message: str, active: str) -> ProjectChatAction:
    normalized = _normalize_match_text(message)
    generation_terms = (
        "avancar",
        "avance",
        "continuar",
        "continue",
        "criacao",
        "crie",
        "criar",
        "desenvolvimento",
        "gere",
        "gerar",
        "desenvolva",
        "desenvolver",
        "faca",
        "fazer",
        "faça",
        "monte",
        "montar",
        "parta",
        "partir",
        "produza",
        "produzir",
        "prosseguir",
        "prossiga",
        "seguir",
        "siga",
        "exporte",
        "exportar",
        "finalize",
        "finalizar",
        "valide",
        "validar",
        "rode",
        "rodar",
        "execute",
        "executar",
    )
    script_terms = ("roteiro", "historia", "história", "cena", "cenas", "dialogo", "diálogo")
    idea_terms = (
        "ideia",
        "ideias",
        "premissa",
        "premissas",
        "opcao",
        "opcoes",
        "opção",
        "opções",
    )
    bible_terms = (
        "story bible",
        "bible",
        "biblia",
        "bíblia",
        "universo",
        "mundo",
    )
    asset_terms = (
        "personagem",
        "personagens",
        "visual",
        "cenario",
        "cenarios",
        "locais",
        "local",
        "objeto",
        "objetos",
        "props",
        "referência",
        "referência",
    )
    storyboard_terms = (
        "storyboard",
        "quadro",
        "quadros",
        "frame",
        "frames",
        "enquadramento",
        "animatic",
    )
    video_terms = ("video", "vídeo", "clipe", "clipes", "montagem")
    dubbing_terms = ("dublagem", "dublar", "dubla", "dublado", "dub", "idioma")

    finalization_terms = (
        "finalizacao",
        "finalização",
        "finalizar",
        "export",
        "exportar",
        "timeline",
    )
    quality_terms = (
        "qualidade",
        "qa",
        "controle",
        "continuidade",
        "validar",
        "válidacao",
        "válidação",
    )

    wants_generation = any(term in normalized for term in generation_terms)
    wants_revision = _requests_regeneration(message)
    actionable = wants_generation or wants_revision

    wants_prompt_approval = _requests_visual_prompt_approval(message)
    explicit_video_prompt = "prompt de video" in normalized or "prompts de video" in normalized
    has_storyboard_term = any(term in normalized for term in storyboard_terms)
    if wants_prompt_approval and (
        active == "video"
        or explicit_video_prompt
        or (any(term in normalized for term in video_terms) and not has_storyboard_term)
    ):
        return "generate_video"
    if wants_prompt_approval and has_storyboard_term:
        return "approve_storyboard_prompt"
    if wants_prompt_approval and active == "storyboard":
        return "approve_storyboard_prompt"
    if wants_prompt_approval:
        return "approve_visual_prompt"
    if _requests_full_script_regeneration(message):
        return "generate_script"
    if actionable and any(term in normalized for term in quality_terms):
        return "run_quality"
    if actionable and any(term in normalized for term in dubbing_terms):
        return "generate_dubbing"
    if actionable and any(term in normalized for term in finalization_terms):
        return "generate_finalization"
    if actionable and any(term in normalized for term in video_terms):
        return "generate_video"
    if actionable and any(term in normalized for term in storyboard_terms):
        return "generate_storyboard"
    if actionable and any(term in normalized for term in asset_terms):
        return "generate_assets"
    if actionable and any(term in normalized for term in bible_terms):
        return "generate_script"
    if wants_generation and any(term in normalized for term in idea_terms):
        return "generate_ideas"
    if wants_revision and (active == "script" or any(term in normalized for term in script_terms)):
        return "revise_script"
    if wants_revision:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
        if active == "finalization":
            return "generate_finalization"
        if active == "dubbing":
            return "generate_dubbing"
    if wants_generation and (
        active == "script" or any(term in normalized for term in script_terms)
    ):
        return "generate_script"
    if wants_generation:
        if active == "assets":
            return "generate_assets"
        if active == "storyboard":
            return "generate_storyboard"
        if active == "video":
            return "generate_video"
        if active == "finalization":
            return "generate_finalization"
        if active == "dubbing":
            return "generate_dubbing"
        return "generate_script"
    return "chat"


def _context_counts(project_context: dict[str, Any]) -> dict[str, int]:
    raw_counts = project_context.get("counts")
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        try:
            normalized[key] = int(value or 0)
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def _project_workflow_mode(project_context: dict[str, Any]) -> str:
    settings = project_context.get("production_settings")
    if not isinstance(settings, dict):
        return CONTINUOUS_VIDEO_WORKFLOW_MODE
    return (
        str(settings.get("workflow_mode") or CONTINUOUS_VIDEO_WORKFLOW_MODE).strip()
        or CONTINUOUS_VIDEO_WORKFLOW_MODE
    )


def _workflow_progression_requested(message: str) -> bool:
    normalized = _normalize_match_text(message)
    terms = (
        "agora que",
        "avancar",
        "avance",
        "continuar",
        "continue",
        "etapa seguinte",
        "partir",
        "pode seguir",
        "próxima etapa",
        "próximo passo",
        "prosseguir",
        "prossiga",
        "seguir",
        "siga",
    )
    return any(term in normalized for term in terms)


def _next_project_action(active: str, project_context: dict[str, Any]) -> ProjectChatAction:
    counts = _context_counts(project_context)
    scripts = counts.get("scripts", 0)
    scenes = counts.get("scenes", 0)
    shots = counts.get("shots", 0)
    characters = counts.get("characters", 0)
    locations = counts.get("locations", 0)
    props = counts.get("props", 0)
    frames = counts.get("frames", 0)
    clips = counts.get("clips", 0)
    exports = counts.get("exports", 0)
    dubbing_jobs = counts.get("dubbing_jobs", 0)
    continuous_mode = _project_workflow_mode(project_context) == CONTINUOUS_VIDEO_WORKFLOW_MODE
    continuous_segments = counts.get("continuous_video_segments", 0)
    approved_continuous_segments = counts.get("continuous_video_approved_segments", 0)

    if scripts == 0:
        return "generate_script"
    if not continuous_mode and (scenes == 0 or shots == 0):
        return "generate_script"
    if characters == 0 or locations == 0 or props == 0:
        return "generate_assets"
    if continuous_mode and (
        continuous_segments == 0
        or approved_continuous_segments
        < min(CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS, continuous_segments)
    ):
        return "generate_video"
    if continuous_mode:
        if exports == 0 or active == "finalization":
            return "generate_finalization"
        if dubbing_jobs == 0:
            return "generate_dubbing"
        if active in {"video", "finalization", "dubbing"}:
            return "generate_finalization"
        return "run_quality"
    if frames == 0:
        return "generate_storyboard"
    if clips == 0:
        return "generate_video"
    if exports == 0 or active == "finalization":
        return "generate_finalization"
    if dubbing_jobs == 0:
        return "generate_dubbing"
    if active in {"video", "finalization", "dubbing"}:
        return "generate_finalization"
    return "run_quality"


def _contextual_project_chat_intent(
    message: str,
    active: str,
    project_context: dict[str, Any],
    classified_action: ProjectChatAction,
) -> ProjectChatIntent:
    normalized = _normalize_match_text(message)
    wants_prompt_approval = _requests_visual_prompt_approval(message)
    storyboard_context = (
        "storyboard" in normalized
        or "quadro" in normalized
        or "quadros" in normalized
        or "frame" in normalized
        or "frames" in normalized
        or "enquadramento" in normalized
        or active == "storyboard"
    )
    explicit_video_prompt = "prompt de video" in normalized or "prompts de video" in normalized
    video_context = (
        "video" in normalized
        or "clipe" in normalized
        or "clipes" in normalized
        or active == "video"
    )
    continuous_mode = _project_workflow_mode(project_context) == CONTINUOUS_VIDEO_WORKFLOW_MODE
    if continuous_mode and (storyboard_context or classified_action == "generate_storyboard"):
        return ProjectChatIntent(
            "generate_video",
            0.92,
            "modo continuo usa segmentos de video no lugar de storyboard",
        )
    if wants_prompt_approval and (
        active == "video"
        or explicit_video_prompt
        or (video_context and not storyboard_context)
    ):
        return ProjectChatIntent(
            "generate_video",
            1.0,
            "pedido explicito de aprovacao de prompts de video",
        )
    if wants_prompt_approval and storyboard_context:
        return ProjectChatIntent(
            "approve_storyboard_prompt",
            1.0,
            "pedido explicito de aprovacao de prompts de storyboard",
        )
    if wants_prompt_approval:
        return ProjectChatIntent("approve_visual_prompt", 1.0, "pedido explicito de aprovacao")

    asset_phrase = all(term in normalized for term in ("personagens", "locais", "objetos"))
    if asset_phrase and _workflow_progression_requested(message):
        return ProjectChatIntent(
            "generate_assets",
            0.96,
            "pedido para avancar criando personagens, locais e objetos",
        )

    if _workflow_progression_requested(message):
        next_action = _next_project_action(active, project_context)
        return ProjectChatIntent(next_action, 0.86, "pedido para avancar no fluxo do projeto")

    if classified_action != "chat":
        return ProjectChatIntent(classified_action, 0.8, "classificador por regras")

    return ProjectChatIntent("chat", 0.0, "sem intencao executavel clara")


def _coerce_project_chat_action(value: object) -> ProjectChatAction:
    action = str(value or "").strip()
    valid_actions = set(ACTION_PROGRESS_MESSAGES)
    return cast(ProjectChatAction, action) if action in valid_actions else "chat"


async def _infer_project_chat_intent_with_ai(
    session: AsyncSession,
    project_id: UUID,
    active: str,
    message: str,
    project_context: dict[str, Any],
) -> ProjectChatIntent:
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    prompt = (
        "Interprete a intencao operacional do usuario dentro de um software de criacao "
        "audiovisual. Retorne somente JSON válido, sem markdown. Acoes possíveis: "
        "chat, generate_ideas, generate_script, revise_script, generate_assets, "
        "approve_visual_prompt, approve_storyboard_prompt, generate_storyboard, "
        "generate_video, generate_dubbing, "
        "generate_finalization, run_quality. Use o estado real do projeto para decidir se "
        "o usuario quer executar "
        "uma etapa ou apenas conversar. Se a confianca for menor que 0.70, use chat. "
        'Formato: {"action":"generate_assets","confidence":0.92,"reason":"..."}. '
        f"Etapa ativa: {active}. Estado do projeto: {project_context}. "
        f"Mensagem do usuario: {message}"
    )
    try:
        result, _execution = await run_structured_generation(
            session,
            provider,
            project_id,
            "director_agent_chat",
            {
                "prompt": prompt,
                "section": active,
                "message": message,
                "project_context": project_context,
                "history": [],
            },
            model=model,
            fallback_on_runtime_error=True,
        )
    except Exception:
        return ProjectChatIntent("chat", 0.0, "falha ao interpretar por IA")

    action = _coerce_project_chat_action(
        result.content.get("action") or result.content.get("intent")
    )
    try:
        confidence = float(result.content.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(result.content.get("reason") or "").strip()
    if confidence < 0.7:
        action = "chat"
    return ProjectChatIntent(action, confidence, reason)
