import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, DependencyKind, ProjectStatus
from app.generation.model_settings import llm_provider_for_task
from app.generation.service import run_structured_generation
from app.projects.models import Artifact, ArtifactVersion
from app.projects.repository import ProjectRepository
from app.projects.versioning import create_artifact_version
from app.storytelling.models import (
    Briefing,
    Scene,
    Script,
    ScriptVersion,
    Shot,
    StoryBible,
    StoryIdea,
)
from app.storytelling.schemas import BriefingCreate
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import advance_project_status


class GenerationOutputError(RuntimeError):
    pass


def _required_mapping(payload: object, context: str) -> dict:
    if not isinstance(payload, dict):
        raise GenerationOutputError(f"{context}: expected JSON object")
    return payload


def _required_list(payload: dict, key: str, context: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise GenerationOutputError(f"{context}: missing non-empty list '{key}'")
    return value


def _required_str(payload: dict, key: str, context: str) -> str:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing field '{key}'")
    text = str(value).strip()
    if not text:
        raise GenerationOutputError(f"{context}: empty field '{key}'")
    return text


def _bounded_required_str(payload: dict, key: str, context: str, max_length: int) -> str:
    text = _required_str(payload, key, context)
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3].rstrip()}..."


def _shot_narration_text(payload: dict, context: str) -> str:
    narration = str(payload.get("narration_text") or "").strip()
    if narration:
        return narration
    dialogue = str(payload.get("dialogue_text") or "").strip()
    if dialogue:
        return dialogue
    return _required_str(payload, "action", context)


def _required_int(payload: dict, key: str, context: str) -> int:
    value = payload.get(key)
    if value is None:
        raise GenerationOutputError(f"{context}: missing integer field '{key}'")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationOutputError(f"{context}: invalid integer field '{key}'") from exc


def _coerce_score(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(round(value))))
    text = str(value).strip().lower()
    if not text:
        return default
    labels = {
        "baixo": 25,
        "baixa": 25,
        "low": 25,
        "medio": 50,
        "médio": 50,
        "media": 50,
        "média": 50,
        "medium": 50,
        "alto": 80,
        "alta": 80,
        "high": 80,
    }
    if text in labels:
        return labels[text]
    match = re.search(r"-?\d+(?:[,.]\d+)?", text)
    if match is None:
        return default
    number = float(match.group(0).replace(",", "."))
    if "/" in text and number <= 10:
        number *= 10
    return max(0, min(100, int(round(number))))


def coerce_duration_minutes(value: object, default: float = 5.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        duration = float(str(value).replace(",", "."))
    except ValueError:
        return default
    return max(3.0, min(8.0, duration))


def _script_block_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(
            text for item in value if (text := _script_block_to_text(item))
        )
    if not isinstance(value, dict):
        return str(value).strip() if value is not None else ""

    label_order = [
        "scene_number",
        "number",
        "title",
        "heading",
        "duration_seconds",
        "summary",
        "objective",
        "characters",
        "location",
        "setting",
        "action",
        "narration",
        "narration_text",
        "dialogue",
        "dialogue_text",
        "storyboard",
        "storyboard_direction",
        "video",
        "video_direction",
        "camera_movement",
    ]
    labels = {
        "scene_number": "Cena",
        "number": "Numero",
        "title": "Titulo",
        "heading": "Cabecalho",
        "duration_seconds": "Duracao",
        "summary": "Resumo",
        "objective": "Objetivo dramatico",
        "characters": "Personagens",
        "location": "Local",
        "setting": "Ambiente",
        "action": "Acao",
        "narration": "Narracao",
        "narration_text": "Narracao",
        "dialogue": "Dialogo",
        "dialogue_text": "Dialogo",
        "storyboard": "Indicacao para storyboard",
        "storyboard_direction": "Indicacao para storyboard",
        "video": "Indicacao para video",
        "video_direction": "Indicacao para video",
        "camera_movement": "Movimento de camera",
    }
    lines: list[str] = []
    for key in label_order:
        if key not in value:
            continue
        text = _script_block_to_text(value[key])
        if text:
            lines.append(f"{labels[key]}: {text}")
    return "\n".join(lines)


def _script_content_from_payload(payload: dict) -> str:
    direct_content = (
        payload.get("content")
        or payload.get("script")
        or payload.get("roteiro")
        or payload.get("text")
        or payload.get("texto")
    )
    if text := _script_block_to_text(direct_content):
        return text

    for key in (
        "scenes",
        "cenas",
        "acts",
        "atos",
        "beats",
        "sequencias",
        "sequences",
        "structure",
        "outline",
        "roteiro_cenas",
    ):
        if key in payload and (text := _script_block_to_text(payload[key])):
            return text
    return ""


def _fallback_script_content_from_bible(
    story_bible_payload: dict, title: str, target_duration_seconds: int
) -> str:
    logline = str(story_bible_payload.get("logline") or "").strip()
    theme = str(story_bible_payload.get("theme") or "").strip()
    tone = str(story_bible_payload.get("tone") or "").strip()
    visual_style = str(story_bible_payload.get("visual_style") or "").strip()
    characters = _script_block_to_text(story_bible_payload.get("characters"))
    locations = _script_block_to_text(story_bible_payload.get("locations"))
    props = _script_block_to_text(story_bible_payload.get("props"))
    scene_duration = max(30, target_duration_seconds // 5)
    return "\n\n".join(
        [
            f"ROTEIRO DE PRODUCAO - {title}",
            f"Duracao alvo: {target_duration_seconds}s",
            f"Logline: {logline or title}",
            f"Tema: {theme or 'transformacao emocional'}",
            f"Tom: {tone or 'cinematico e emocional'}",
            f"Estilo visual: {visual_style or 'cinematico vertical'}",
            f"Personagens principais:\n{characters or 'Definir a partir da Story Bible.'}",
            f"Locais:\n{locations or 'Local principal definido pela Story Bible.'}",
            f"Objetos importantes:\n{props or 'Objetos narrativos definidos pela Story Bible.'}",
            (
                f"CENA 1 - GANCHO INICIAL - {scene_duration}s\n"
                "Objetivo dramatico: apresentar conflito visual imediato.\n"
                "Acao: o protagonista encontra um sinal, objeto ou decisao que muda a rotina.\n"
                "Narracao: uma frase curta introduz a promessa emocional.\n"
                "Indicacao para storyboard: plano vertical forte com foco no rosto e no objeto.\n"
                "Indicacao para video: camera lenta suave, ritmo de descoberta."
            ),
            (
                f"CENA 2 - CONTEXTO E DESEJO - {scene_duration}s\n"
                "Objetivo dramatico: mostrar o que o protagonista quer proteger ou conquistar.\n"
                "Acao: interacoes revelam relacoes, limites e stakes emocionais.\n"
                "Dialogo: falas curtas, com nomes em caixa alta quando houver personagem falando.\n"
                "Indicacao para storyboard: alternar plano medio e detalhe significativo.\n"
                "Indicacao para video: movimento discreto acompanhando a decisao."
            ),
            (
                f"CENA 3 - VIRADA - {scene_duration}s\n"
                "Objetivo dramatico: colocar o protagonista diante de uma escolha irreversivel.\n"
                "Acao: uma descoberta muda o sentido da historia.\n"
                "Indicacao para storyboard: composicao vertical com contraste de luz e sombra.\n"
                "Indicacao para video: aproximacao gradual ate o momento da virada."
            ),
            (
                f"CENA 4 - CLIMAX - {scene_duration}s\n"
                "Objetivo dramatico: resolver a escolha com acao clara e filmavel.\n"
                "Acao: o protagonista age, perde algo ou revela uma verdade.\n"
                "Indicacao para storyboard: planos de reacao e gesto decisivo.\n"
                "Indicacao para video: ritmo mais intenso, cortes curtos e camera firme."
            ),
            (
                f"CENA 5 - PAYOFF EMOCIONAL - {scene_duration}s\n"
                "Objetivo dramatico: entregar consequencia emocional e imagem final memoravel.\n"
                "Acao: o mundo da historia mostra a mudanca causada pela decisao.\n"
                "Narracao: frase final curta com fechamento emocional.\n"
                "Indicacao para storyboard: plano aberto ou detalhe final simbolico.\n"
                "Indicacao para video: movimento suave de encerramento e pausa final."
            ),
        ]
    )


def normalize_script_payload(
    payload: dict,
    *,
    default_title: str,
    language: str,
    target_duration_seconds: int,
) -> dict:
    normalized = dict(payload)
    normalized.setdefault("title", default_title)
    normalized.setdefault("language", language)
    normalized["target_duration_seconds"] = _coerce_positive_int(
        normalized.get("target_duration_seconds"), target_duration_seconds
    )
    normalized["content"] = _script_content_from_payload(normalized)
    normalized["word_count"] = _coerce_positive_int(
        normalized.get("word_count"), len(normalized["content"].split())
    )
    return normalized


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return max(1, default)
    try:
        number = int(float(str(value).replace(",", ".")))
    except ValueError:
        return max(1, default)
    return max(1, number)


async def _create_artifact(
    session: AsyncSession,
    project_id: UUID,
    artifact_type: ArtifactType,
    name: str,
    payload: dict,
    status: ArtifactStatus = ArtifactStatus.READY_FOR_REVIEW,
) -> Artifact:
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        name=name,
        status=status,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            payload=payload,
            change_note="Generated by phase 3 storytelling workflow",
        )
    )
    await session.flush()
    return artifact


async def _add_dependency(
    session: AsyncSession,
    upstream_artifact_id: UUID,
    downstream_artifact_id: UUID,
    kind: DependencyKind = DependencyKind.DERIVED_FROM,
) -> None:
    session.add(
        ArtifactDependency(
            upstream_artifact_id=upstream_artifact_id,
            downstream_artifact_id=downstream_artifact_id,
            dependency_kind=kind,
        )
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


async def get_latest_briefing(session: AsyncSession, project_id: UUID) -> Briefing | None:
    result = await session.execute(
        select(Briefing)
        .where(Briefing.project_id == project_id)
        .order_by(Briefing.created_at.desc())
    )
    return result.scalars().first()


def normalize_story_idea_payload(payload: dict) -> dict:
    normalized = dict(payload)
    title = _required_str(normalized, "title", "story_idea")
    normalized.setdefault("hook", normalized.get("premise") or title)
    normalized.setdefault("premise", normalized.get("hook") or title)
    normalized.setdefault("protagonist", "Protagonista a definir")
    normalized["duration_minutes"] = coerce_duration_minutes(normalized.get("duration_minutes"))
    normalized["retention_potential"] = _coerce_score(
        normalized.get("retention_potential"), 75
    )
    normalized["cliche_risk"] = _coerce_score(normalized.get("cliche_risk"), 25)
    normalized["production_complexity"] = _coerce_score(
        normalized.get("production_complexity"), 35
    )
    normalized["title"] = title
    return normalized


async def create_story_idea_from_payload(
    session: AsyncSession, project_id: UUID, payload: dict
) -> StoryIdea | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    item = normalize_story_idea_payload(payload)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.STORY_IDEA,
        _required_str(item, "title", "story_idea"),
        item,
    )
    await _add_dependency(session, briefing.artifact_id, artifact.id)
    idea = StoryIdea(
        project_id=project_id,
        artifact_id=artifact.id,
        title=_required_str(item, "title", "story_idea"),
        hook=_required_str(item, "hook", "story_idea"),
        premise=_required_str(item, "premise", "story_idea"),
        protagonist=_required_str(item, "protagonist", "story_idea"),
        retention_potential=_required_int(item, "retention_potential", "story_idea"),
        cliche_risk=_required_int(item, "cliche_risk", "story_idea"),
        production_complexity=_required_int(item, "production_complexity", "story_idea"),
        payload=item,
    )
    session.add(idea)
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    await session.refresh(idea)
    return idea


async def generate_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea] | None:
    project = await ProjectRepository(session).get_project(project_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or briefing is None:
        return None

    variables = {
        "theme": briefing.theme,
        "audience": briefing.audience,
        "primary_emotion": briefing.primary_emotion,
        "genre": briefing.genre,
        "target_duration_minutes": float(briefing.desired_duration_minutes),
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_ideas")
    result, execution = await run_structured_generation(
        session, provider, project_id, "generate_story_ideas", variables, model=model
    )
    ideas: list[StoryIdea] = []
    content = _required_mapping(result.content, "generate_story_ideas")
    for index, raw_item in enumerate(_required_list(content, "ideas", "generate_story_ideas"), 1):
        item = normalize_story_idea_payload(
            _required_mapping(raw_item, f"generate_story_ideas.ideas[{index}]")
        )
        artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.STORY_IDEA,
            _required_str(item, "title", f"generate_story_ideas.ideas[{index}]"),
            item,
        )
        await _add_dependency(session, briefing.artifact_id, artifact.id)
        idea = StoryIdea(
            project_id=project_id,
            artifact_id=artifact.id,
            title=_required_str(item, "title", f"generate_story_ideas.ideas[{index}]"),
            hook=_required_str(item, "hook", f"generate_story_ideas.ideas[{index}]"),
            premise=_required_str(item, "premise", f"generate_story_ideas.ideas[{index}]"),
            protagonist=_required_str(
                item, "protagonist", f"generate_story_ideas.ideas[{index}]"
            ),
            retention_potential=_required_int(
                item, "retention_potential", f"generate_story_ideas.ideas[{index}]"
            ),
            cliche_risk=_required_int(item, "cliche_risk", f"generate_story_ideas.ideas[{index}]"),
            production_complexity=_required_int(
                item, "production_complexity", f"generate_story_ideas.ideas[{index}]"
            ),
            payload=item,
        )
        session.add(idea)
        ideas.append(idea)
    execution.response = result.content
    advance_project_status(project, ProjectStatus.IDEA_APPROVAL)
    await session.commit()
    for idea in ideas:
        await session.refresh(idea)
    return ideas


async def list_story_ideas(session: AsyncSession, project_id: UUID) -> list[StoryIdea]:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return []
    result = await session.execute(
        select(StoryIdea).where(StoryIdea.project_id == project_id).order_by(StoryIdea.created_at)
    )
    return list(result.scalars())


async def generate_story_bible(
    session: AsyncSession, project_id: UUID, story_idea_id: UUID
) -> StoryBible | None:
    project = await ProjectRepository(session).get_project(project_id)
    idea = await session.get(StoryIdea, story_idea_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or idea is None or idea.project_id != project_id or briefing is None:
        return None

    variables = _briefing_payload(
        BriefingCreate.model_validate(briefing, from_attributes=True)
    ) | {"idea": idea.payload, "idea_title": idea.title}
    provider, model = await llm_provider_for_task(session, project_id, "generate_story_bible")
    result, _execution = await run_structured_generation(
        session, provider, project_id, "generate_story_bible", variables, model=model
    )
    payload = _required_mapping(result.content, "generate_story_bible")
    title = _required_str(payload, "title", "generate_story_bible")
    artifact = await _create_artifact(
        session, project_id, ArtifactType.STORY_BIBLE, title, payload
    )
    await _add_dependency(session, idea.artifact_id, artifact.id)
    story_bible = StoryBible(
        project_id=project_id,
        artifact_id=artifact.id,
        story_idea_id=idea.id,
        title=title,
        logline=_required_str(payload, "logline", "generate_story_bible"),
        payload=payload,
    )
    session.add(story_bible)
    advance_project_status(project, ProjectStatus.STORY_APPROVAL)
    await session.commit()
    await session.refresh(story_bible)
    return story_bible


async def generate_script(
    session: AsyncSession, project_id: UUID, story_bible_id: UUID
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    story_bible = await session.get(StoryBible, story_bible_id)
    briefing = await get_latest_briefing(session, project_id)
    if (
        project is None
        or story_bible is None
        or story_bible.project_id != project_id
        or briefing is None
    ):
        return None

    target_duration_seconds = int(briefing.desired_duration_minutes * Decimal("60"))
    variables = {
        "story_bible": story_bible.payload,
        "language": briefing.language,
        "target_duration_seconds": target_duration_seconds,
    }
    provider, model = await llm_provider_for_task(session, project_id, "generate_script")
    result, _execution = await run_structured_generation(
        session, provider, project_id, "generate_script", variables, model=model
    )
    payload = normalize_script_payload(
        _required_mapping(result.content, "generate_script"),
        default_title=story_bible.title,
        language=briefing.language,
        target_duration_seconds=target_duration_seconds,
    )
    title = _required_str(payload, "title", "generate_script")
    if not str(payload.get("content") or "").strip():
        payload["content"] = _fallback_script_content_from_bible(
            story_bible.payload,
            title,
            target_duration_seconds,
        )
        payload["word_count"] = len(payload["content"].split())
    artifact = await _create_artifact(
        session, project_id, ArtifactType.SCRIPT, title, payload
    )
    await _add_dependency(session, story_bible.artifact_id, artifact.id)
    script = Script(
        project_id=project_id,
        artifact_id=artifact.id,
        story_bible_id=story_bible.id,
        title=title,
        language=_required_str(payload, "language", "generate_script"),
        target_duration_seconds=_required_int(
            payload, "target_duration_seconds", "generate_script"
        ),
        word_count=_required_int(payload, "word_count", "generate_script"),
        content=_required_str(payload, "content", "generate_script"),
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
    advance_project_status(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def revise_script(
    session: AsyncSession,
    project_id: UUID,
    script_id: UUID,
    instruction: str,
    project_context: dict | None = None,
) -> Script | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    briefing = await get_latest_briefing(session, project_id)
    if project is None or script is None or script.project_id != project_id or briefing is None:
        return None
    artifact = await session.get(Artifact, script.artifact_id)
    if artifact is None:
        return None

    variables = {
        "title": script.title,
        "language": script.language,
        "target_duration_seconds": script.target_duration_seconds,
        "current_script": script.content,
        "instruction": instruction,
        "project_context": project_context or {},
    }
    provider, model = await llm_provider_for_task(session, project_id, "revise_script")
    result, execution = await run_structured_generation(
        session,
        provider,
        project_id,
        "revise_script",
        variables,
        artifact_id=script.artifact_id,
        model=model,
    )
    payload = normalize_script_payload(
        _required_mapping(result.content, "revise_script"),
        default_title=script.title,
        language=script.language,
        target_duration_seconds=script.target_duration_seconds,
    )
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
        change_note=f"Revisao por chat: {instruction[:160]}",
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
    advance_project_status(project, ProjectStatus.SCRIPT_APPROVAL)
    await session.commit()
    await session.refresh(script)
    return script


async def generate_scenes_and_shots(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> list[Scene] | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None

    provider, model = await llm_provider_for_task(session, project_id, "generate_scenes_and_shots")
    result, _execution = await run_structured_generation(
        session,
        provider,
        project_id,
        "generate_scenes_and_shots",
        {
            "script": script.content,
            "target_duration_seconds": script.target_duration_seconds,
        },
        model=model,
    )

    scenes: list[Scene] = []
    content = _required_mapping(result.content, "generate_scenes_and_shots")
    for scene_index, raw_scene_payload in enumerate(
        _required_list(content, "scenes", "generate_scenes_and_shots"), 1
    ):
        scene_payload = _required_mapping(
            raw_scene_payload, f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_title = _required_str(
            scene_payload, "title", f"generate_scenes_and_shots.scenes[{scene_index}]"
        )
        scene_artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.SCENE,
            scene_title,
            scene_payload,
        )
        await _add_dependency(session, script.artifact_id, scene_artifact.id)
        scene = Scene(
            project_id=project_id,
            artifact_id=scene_artifact.id,
            script_id=script.id,
            scene_number=_required_int(
                scene_payload, "scene_number", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            title=scene_title,
            summary=_required_str(
                scene_payload, "summary", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            duration_seconds=_required_int(
                scene_payload,
                "duration_seconds",
                f"generate_scenes_and_shots.scenes[{scene_index}]",
            ),
            payload=scene_payload,
        )
        session.add(scene)
        await session.flush()
        for shot_index, raw_shot_payload in enumerate(
            _required_list(
                scene_payload, "shots", f"generate_scenes_and_shots.scenes[{scene_index}]"
            ),
            1,
        ):
            shot_context = (
                f"generate_scenes_and_shots.scenes[{scene_index}].shots[{shot_index}]"
            )
            shot_payload = _required_mapping(raw_shot_payload, shot_context)
            shot_artifact = await _create_artifact(
                session,
                project_id,
                ArtifactType.SHOT,
                f"{scene.title} - Plano {_required_int(shot_payload, 'shot_number', shot_context)}",
                shot_payload,
            )
            await _add_dependency(session, scene_artifact.id, shot_artifact.id)
            session.add(
                Shot(
                    project_id=project_id,
                    artifact_id=shot_artifact.id,
                    scene_id=scene.id,
                    shot_number=_required_int(shot_payload, "shot_number", shot_context),
                    duration_seconds=_required_int(shot_payload, "duration_seconds", shot_context),
                    narration_text=_shot_narration_text(shot_payload, shot_context),
                    dialogue_text=str(shot_payload.get("dialogue_text") or ""),
                    action=_required_str(shot_payload, "action", shot_context),
                    emotion=_bounded_required_str(shot_payload, "emotion", shot_context, 120),
                    visual_composition=_required_str(
                        shot_payload, "visual_composition", shot_context
                    ),
                    camera_movement=_bounded_required_str(
                        shot_payload, "camera_movement", shot_context, 120
                    ),
                    generation_type=_bounded_required_str(
                        shot_payload, "generation_type", shot_context, 80
                    ),
                    payload=shot_payload,
                )
            )
        scenes.append(scene)
    advance_project_status(project, ProjectStatus.VISUAL_BIBLE_GENERATION)
    await session.commit()
    for scene in scenes:
        await session.refresh(scene)
    return scenes
