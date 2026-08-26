# ruff: noqa: F401

import math
import re
import unicodedata
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.models import Artifact
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.storytelling.artifacts import (
    _add_dependency,
    _advance_project_status_when_reachable,
    _create_artifact,
)
from app.storytelling.models import (
    Briefing,
    Script,
    ScriptVersion,
    StoryIdea,
)
from app.storytelling.normalization import (
    GenerationOutputError,
    _bounded_required_str,
    _idea_script_contract,
    _required_int,
    _required_list,
    _required_mapping,
    _required_str,
    _shot_narration_text,
    expected_script_scene_count,
    normalize_scene_plan_payload_from_script,
    normalize_script_payload,
    scene_plan_payload_from_script_content,
)
from app.storytelling.normalization import (
    _fallback_script_content_from_bible as _fallback_script_content_from_bible,
)
from app.storytelling.normalization import (
    _fallback_script_content_from_idea as _fallback_script_content_from_idea,  # noqa: F401
)
from app.storytelling.normalization import (
    _story_idea_db_text as _story_idea_db_text,  # noqa: F401
)
from app.storytelling.normalization import (
    _story_idea_retry_guidance as _story_idea_retry_guidance,  # noqa: F401
)
from app.storytelling.normalization import (
    coerce_duration_minutes as coerce_duration_minutes,
)
from app.storytelling.normalization import (
    normalize_scene_plan_payload as normalize_scene_plan_payload,
)
from app.storytelling.normalization import (
    normalize_story_bible_payload as normalize_story_bible_payload,
)
from app.storytelling.normalization import (
    normalize_story_hooks_payload as normalize_story_hooks_payload,
)
from app.storytelling.normalization import (
    normalize_story_idea_payload as normalize_story_idea_payload,  # noqa: F401
)
from app.storytelling.normalization import (
    screenplay_validation_errors as screenplay_validation_errors,
)
from app.storytelling.normalization import (
    story_bible_validation_errors as story_bible_validation_errors,
)
from app.storytelling.normalization import (
    story_idea_diversity_errors as story_idea_diversity_errors,
)
from app.storytelling.normalization import (
    story_idea_validation_errors as story_idea_validation_errors,
)
from app.storytelling.schemas import BriefingCreate
from app.storytelling.story_ideas import (
    create_story_idea_from_payload as create_story_idea_from_payload,  # noqa: F401
)
from app.storytelling.story_ideas import (
    generate_story_ideas as generate_story_ideas,  # noqa: F401
)
from app.storytelling.story_ideas import (
    get_latest_briefing,
)
from app.storytelling.story_ideas import (
    list_story_ideas as list_story_ideas,  # noqa: F401
)
from app.video_generation.durations import (
    VIDEO_CLIP_MAX_SECONDS,
    VIDEO_CLIP_MIN_SECONDS,
    VIDEO_CLIP_TARGET_SECONDS,
    format_clip_durations,
    video_clip_durations,
)
from app.workflows.state_machine import advance_project_status

SCRIPT_GENERATION_MAX_ATTEMPTS = 3


def _revision_match_text(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def _requested_revision_duration_seconds(instruction: str) -> int | None:
    normalized = _revision_match_text(instruction)
    minute_match = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(?:minutos|minuto|mins|min|m)\b",
        normalized,
    )
    if minute_match:
        return max(15, int(float(minute_match.group(1).replace(",", ".")) * 60))
    second_match = re.search(
        r"\b(\d+(?:[,.]\d+)?)\s*(?:segundos|segundo|segs|seg|s)\b",
        normalized,
    )
    if second_match:
        return max(15, int(float(second_match.group(1).replace(",", "."))))
    return None


def _video_package_total_duration_seconds(duration_seconds: int) -> int:
    duration = max(VIDEO_CLIP_MIN_SECONDS, int(duration_seconds))
    return math.ceil(duration / VIDEO_CLIP_TARGET_SECONDS) * VIDEO_CLIP_TARGET_SECONDS


def coerce_script_duration_minutes(value: object, default: float = 5.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        duration = float(str(value).replace(",", "."))
    except ValueError:
        return default
    return max(1.0, min(20.0, duration))


def coerce_script_scene_count(value: object | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        count = int(float(str(value).replace(",", ".")))
    except ValueError:
        return None
    return max(1, min(24, count))


def _script_scene_count_guidance(target_scene_count: int | None) -> str:
    if target_scene_count is None:
        return (
            "Mantenha a quantidade de cenas adequada à duração alvo, com cenas numeradas "
            "sequencialmente."
        )
    return (
        f"Organize o roteiro em exatamente {target_scene_count} cenas numeradas, "
        "sem pular números e sem combinar duas cenas sob o mesmo marcador."
    )


def _script_revision_size_targets(
    instruction: str, current_duration_seconds: int, current_word_count: int
) -> tuple[int, int, str]:
    normalized = _revision_match_text(instruction)
    explicit_duration = _requested_revision_duration_seconds(instruction)
    current_duration_seconds = max(15, int(current_duration_seconds or 15))
    current_word_count = max(1, int(current_word_count or 1))
    shrink_terms = (
        "reduz",
        "reduzir",
        "reduza",
        "diminu",
        "encurt",
        "menor",
        "mais curto",
        "curto",
        "menos extenso",
        "resum",
        "compact",
        "grande",
        "extensa",
        "extenso",
    )
    expand_terms = (
        "aument",
        "expand",
        "along",
        "maior",
        "mais longo",
        "mais extensa",
        "mais extenso",
        "desenvolva mais",
    )
    wants_shrink = any(term in normalized for term in shrink_terms)
    wants_expand = any(term in normalized for term in expand_terms) and not wants_shrink
    if wants_shrink:
        target_duration = _video_package_total_duration_seconds(
            explicit_duration or max(15, int(current_duration_seconds * 0.65))
        )
        target_ratio = target_duration / current_duration_seconds
        target_words = max(80, int(current_word_count * target_ratio))
        return (
            target_duration,
            target_words,
            (
                "O pedido é de redução/compactação. Reescreva uma versão claramente "
                f"mais curta que a atual, com cerca de {target_words} palavras e "
                f"duração aproximada de {target_duration}s. Corte repetições, cenas "
                "redundantes e diálogos explicativos, preservando começo, virada dramática "
                "e desfecho."
            ),
        )
    if wants_expand:
        target_duration = _video_package_total_duration_seconds(
            explicit_duration or int(current_duration_seconds * 1.35)
        )
        target_words = max(
            current_word_count + 80,
            int(current_word_count * (target_duration / current_duration_seconds)),
        )
        return (
            target_duration,
            target_words,
            (
                "O pedido é de ampliação. Reescreva uma versão claramente mais desenvolvida "
                f"que a atual, com cerca de {target_words} palavras e duração aproximada "
                f"de {target_duration}s, acrescentando conflito, subtexto e progressão "
                "dramática sem perder o formato cinematográfico."
            ),
        )
    if explicit_duration is not None:
        explicit_duration = _video_package_total_duration_seconds(explicit_duration)
        ratio = explicit_duration / current_duration_seconds
        target_words = max(80, int(current_word_count * ratio))
        return (
            explicit_duration,
            target_words,
            (
                f"Ajuste o roteiro para a nova duração solicitada de {explicit_duration}s, "
                f"com cerca de {target_words} palavras, preservando o contrato narrativo."
            ),
        )
    return (
        _video_package_total_duration_seconds(current_duration_seconds),
        current_word_count,
        (
            "Se o pedido não solicitar mudança de tamanho ou duração, mantenha a duração "
            "e a escala narrativa atuais. Se solicitar, obedeça ao pedido do usuário."
        ),
    )


async def _ensure_script_video_package_duration(session: AsyncSession, script: Script) -> int:
    target_duration_seconds = _video_package_total_duration_seconds(script.target_duration_seconds)
    if target_duration_seconds != script.target_duration_seconds:
        script.target_duration_seconds = target_duration_seconds
        await session.flush()
    return target_duration_seconds


def _retry_script_generation_after_runtime_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "api_key" in message or "api key" in message or "chave" in message:
        return False
    retry_terms = (
        "json",
        "formato",
        "format",
        "content vazio",
        "fora do formato",
        "resposta fora",
        "timeout",
        "demorou mais",
        "connection",
        "network",
        "temporarily unavailable",
    )
    return any(term in message for term in retry_terms)


def _script_runtime_retry_guidance(exc: Exception) -> str:
    return (
        "A resposta anterior não pôde ser lida pela aplicação: "
        f"{str(exc)[:600]}. Responda com um único objeto JSON válido, sem markdown, "
        "sem comentários antes ou depois, mantendo o roteiro completo em content. "
        "Escape aspas internas de diálogo quando necessário."
    )


def _briefing_payload(data: BriefingCreate) -> dict:
    return data.model_dump(mode="json")


async def create_briefing(
    session: AsyncSession, project_id: UUID, data: BriefingCreate
) -> Briefing | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None

    payload = _briefing_payload(data)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.BRIEFING,
        "Briefing",
        payload,
        ArtifactStatus.APPROVED,
    )
    briefing = Briefing(
        project_id=project_id,
        artifact_id=artifact.id,
        theme=data.theme,
        audience=data.audience,
        genre=data.genre,
        primary_emotion=data.primary_emotion,
        emotional_intensity=data.emotional_intensity,
        ending_type=data.ending_type,
        language=data.language,
        country_context=data.country_context,
        desired_duration_minutes=data.desired_duration_minutes,
        has_narrator=data.has_narrator,
        visual_style=data.visual_style,
        content_objective=data.content_objective,
        call_to_action=data.call_to_action,
        constraints=data.constraints,
    )
    advance_project_status(project, ProjectStatus.IDEA_GENERATION)
    session.add(briefing)
    await session.commit()
    await session.refresh(briefing)
    return briefing


async def generate_story_hooks(
    session: AsyncSession,
    project_id: UUID,
    story_idea_id: UUID,
) -> list[dict] | None:
    """Gera pelo menos 5 ganchos de historia a partir da ideia aprovada.

    Os ganchos sao opcoes alternativas de abertura para o usuario escolher
    antes da geracao do roteiro. O gancho escolhido e repassado a
    ``generate_script`` via ``story_hook``.
    """
    project = await ProjectRepository(session).get_project(project_id)
    idea = await session.get(StoryIdea, story_idea_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or idea is None or idea.project_id != project_id or briefing is None:
        return None

    narrative_contract = _idea_script_contract(idea, briefing)
    variables = {
        "narrative_contract": narrative_contract,
        "idea": idea.payload,
        "idea_title": idea.title,
        "language": briefing.language,
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_hooks")
    hooks: list[dict] | None = None
    last_error: GenerationOutputError | None = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        try:
            result, _execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "generate_story_hooks",
                variables,
                model=model,
                fallback_on_runtime_error=True,
            )
        except RuntimeError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1 or not (
                _retry_script_generation_after_runtime_error(exc)
            ):
                raise
            variables["retry_guidance"] = _script_runtime_retry_guidance(exc)
            continue
        try:
            hooks = normalize_story_hooks_payload(
                _required_mapping(result.content, "generate_story_hooks"),
            )
            break
        except GenerationOutputError as exc:
            last_error = exc
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque não seguiu o formato exigido: "
                f"{exc}. Responda somente JSON, sem markdown, com a chave hooks e "
                "pelo menos 5 itens com title e description em portugues do Brasil."
            )
    if hooks is None:
        if last_error is not None:
            raise last_error
        raise GenerationOutputError("generate_story_hooks: resposta vazia do modelo")
    return hooks


async def generate_script(
    session: AsyncSession,
    project_id: UUID,
    story_idea_id: UUID,
    target_duration_minutes: float | Decimal | None = None,
    target_scene_count: int | None = None,
    story_hook: dict | None = None,
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    idea = await session.get(StoryIdea, story_idea_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or idea is None or idea.project_id != project_id or briefing is None:
        return None

    if target_duration_minutes is not None:
        briefing.desired_duration_minutes = Decimal(
            str(coerce_script_duration_minutes(target_duration_minutes))
        )
        await session.flush()
    target_duration_seconds = _video_package_total_duration_seconds(
        int(briefing.desired_duration_minutes * Decimal("60"))
    )
    clip_durations = video_clip_durations(target_duration_seconds)
    requested_scene_count = coerce_script_scene_count(target_scene_count)
    scene_count = requested_scene_count or expected_script_scene_count(target_duration_seconds)
    narrative_contract = _idea_script_contract(idea, briefing)
    if story_hook is not None:
        narrative_contract["story_hook"] = story_hook
    variables = {
        "narrative_contract": narrative_contract,
        "idea": idea.payload,
        "idea_title": idea.title,
        "language": briefing.language,
        "story_hook": story_hook,
        "target_duration_seconds": target_duration_seconds,
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "expected_clip_count": len(clip_durations),
        "expected_scene_count": scene_count,
        "target_scene_count": scene_count,
        "scene_count_guidance": _script_scene_count_guidance(requested_scene_count),
        "clip_durations": format_clip_durations(clip_durations),
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    payload: dict | None = None
    last_error: GenerationOutputError | None = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        try:
            result, _execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "generate_script",
                variables,
                model=model,
                fallback_on_runtime_error=True,
            )
        except RuntimeError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1 or not (
                _retry_script_generation_after_runtime_error(exc)
            ):
                raise
            variables["retry_guidance"] = _script_runtime_retry_guidance(exc)
            continue
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "generate_script"),
                default_title=idea.title,
                language=briefing.language,
                target_duration_seconds=target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            last_error = exc
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque não seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo content como roteiro de filme limpo e "
                "sem plano tecnico, lista de shots ou cenas compactadas em parágrafos. "
                "Cada cena comeca com UMA linha no padrao 'CENA NN - INT./EXT. LOCAL - "
                "PERIODO' (ex.: 'CENA 04 - EXT. PRACA CENTRAL - DIA'); nunca use "
                "'CORTE PARA:', 'CORTA PARA:', 'CUT TO:' ou 'SEGUINTE' como transição. "
                "Em blocos de dialogo, use apenas nomes de personagens como cue; nunca "
                "use local/cenario como SALA, CASA, RUA, HOSPITAL ou QUARTO no lugar do "
                "personagem. Não use parentéticos nem sufixos como (CONT.), (V.O.) ou "
                "(O.S.)."
            )
    if payload is None:
        if last_error is not None:
            raise last_error
        raise GenerationOutputError("generate_script: resposta vazia do modelo")
    title = _required_str(payload, "title", "generate_script")
    if not str(payload.get("content") or "").strip():
        raise GenerationOutputError("generate_script: resposta sem roteiro")
    if story_hook is not None:
        payload["story_hook"] = story_hook
    artifact = await _create_artifact(session, project_id, ArtifactType.SCRIPT, title, payload)
    await _add_dependency(session, idea.artifact_id, artifact.id)
    script = Script(
        project_id=project_id,
        artifact_id=artifact.id,
        story_idea_id=idea.id,
        title=title,
        language=_required_str(payload, "language", "generate_script"),
        target_duration_seconds=_required_int(
            payload, "target_duration_seconds", "generate_script"
        ),
        word_count=_required_int(payload, "word_count", "generate_script"),
        content=_required_str(payload, "content", "generate_script"),
        story_hook=story_hook,
    )
    session.add(script)
    await session.flush()
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=1,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    _advance_project_status_when_reachable(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def revise_script(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    instruction: str,
    project_context: dict | None = None,
    mark_downstream_stale: bool = True,
    target_duration_minutes: float | Decimal | None = None,
    target_scene_count: int | None = None,
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or script is None or script.project_id != project_id or briefing is None:
        return None
    artifact = await session.get(Artifact, script.artifact_id)
    if artifact is None:
        return None

    duration_instruction = instruction
    if target_duration_minutes is not None:
        duration_seconds = int(coerce_script_duration_minutes(target_duration_minutes) * 60)
        duration_instruction = f"{instruction}\nDuração alvo solicitada: {duration_seconds}s."
    revision_target_duration_seconds, revision_target_word_count, revision_sizing_guidance = (
        _script_revision_size_targets(
            duration_instruction,
            script.target_duration_seconds,
            script.word_count,
        )
    )
    revision_target_scene_count = coerce_script_scene_count(target_scene_count)
    variables = {
        "title": script.title,
        "language": script.language,
        "target_duration_seconds": revision_target_duration_seconds,
        "current_duration_seconds": script.target_duration_seconds,
        "current_word_count": script.word_count,
        "revision_target_duration_seconds": revision_target_duration_seconds,
        "revision_target_word_count": revision_target_word_count,
        "revision_sizing_guidance": revision_sizing_guidance,
        "revision_target_scene_count": revision_target_scene_count
        or expected_script_scene_count(revision_target_duration_seconds),
        "scene_count_guidance": _script_scene_count_guidance(revision_target_scene_count),
        "clip_min_seconds": VIDEO_CLIP_MIN_SECONDS,
        "clip_max_seconds": VIDEO_CLIP_MAX_SECONDS,
        "clip_target_seconds": VIDEO_CLIP_TARGET_SECONDS,
        "current_script": script.content,
        "instruction": instruction,
        "project_context": project_context or {},
        "retry_guidance": "",
    }
    provider, model = await llm_provider_for_task(session, project_id, "revise_script")
    payload: dict | None = None
    execution = None
    for attempt in range(SCRIPT_GENERATION_MAX_ATTEMPTS):
        try:
            result, execution = await run_structured_generation(
                session,
                provider,
                project_id,
                "revise_script",
                variables,
                artifact_id=script.artifact_id,
                model=model,
                fallback_on_runtime_error=True,
            )
        except RuntimeError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1 or not (
                _retry_script_generation_after_runtime_error(exc)
            ):
                raise
            variables["retry_guidance"] = _script_runtime_retry_guidance(exc)
            continue
        try:
            payload = normalize_script_payload(
                _required_mapping(result.content, "revise_script"),
                default_title=script.title,
                language=script.language,
                target_duration_seconds=revision_target_duration_seconds,
            )
            break
        except GenerationOutputError as exc:
            if attempt == SCRIPT_GENERATION_MAX_ATTEMPTS - 1:
                break
            variables["retry_guidance"] = (
                "A resposta anterior foi recusada porque não seguiu o formato exigido: "
                f"{exc}. Reescreva mantendo apenas roteiro de filme em content, com "
                "FADE IN, cabecalhos 'CENA NN - INT./EXT. LOCAL - PERIODO' em uma linha "
                "por cena, acao e dialogo em parágrafos separados; nunca use 'CORTE "
                "PARA:' ou 'SEGUINTE' como transição. Em falas, a cue deve ser nome de "
                "personagem, nunca nome de local/cenario, e não deve ter parentéticos "
                "como (CONT.), (V.O.) ou (O.S.)."
            )
    if payload is None or execution is None:
        return None
    title = _required_str(payload, "title", "revise_script")
    content = _required_str(payload, "content", "revise_script")
    script.title = title
    script.language = _required_str(payload, "language", "revise_script")
    script.target_duration_seconds = _required_int(
        payload, "target_duration_seconds", "revise_script"
    )
    script.word_count = _required_int(payload, "word_count", "revise_script")
    script.content = content
    await create_artifact_version(
        session,
        artifact,
        payload,
        change_note=f"Revisão por chat: {instruction[:160]}",
        mark_downstream_stale=mark_downstream_stale,
    )
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=artifact.current_version,
            content=script.content,
            word_count=script.word_count,
            payload=payload,
        )
    )
    execution.response = result.content
    _advance_project_status_when_reachable(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


from app.storytelling.scene_service import (  # noqa: E402,F401
    generate_scenes_and_shots,
    mark_scene_plan_stale,
    regenerate_scenes_and_shots,
)
