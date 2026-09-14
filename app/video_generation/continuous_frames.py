"""Generation and continuity helpers for shot storyboard anchors."""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.provider_policy import effective_provider_for_channel, provider_model
from app.config.settings import get_settings
from app.core.enums import AssetKind
from app.generation.shot_prompt_compiler import bounded_prompt
from app.providers.image.types import ImageGenerationRequest, ImageReference
from app.providers.registry import resolve_image_provider
from app.providers.storage import generated_output_dir
from app.storage.service import apply_asset_storage_metadata
from app.video_generation.models import ContinuousVideoSegment
from app.visual_bible.models import Character, Location, VisualReference

FRAME_PROMPT_MAX_CHARS = 520


def _clean_excerpt(value: object, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    excerpt = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    words = excerpt.split()
    if words and len(words[-1]) <= 2:
        excerpt = " ".join(words[:-1]).rstrip(" ,.;:")
    return f"{excerpt}…"


def _clean_storyboard_action_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"(?i)^\s*cena\s+\d+\b[:.]?\s*", "", text)
    text = re.sub(
        r"(?i)^\s*(?:int|ext|int/ext|int\./ext)\.?\s+.{3,120}?\s+[–-]\s*"
        r"(?:dia|noite|tarde|manha|manhã|madrugada)\b\.?\s*",
        "",
        text,
    )
    return text.strip()


def _storyboard_narrative_action(segment: ContinuousVideoSegment, metadata: dict[str, Any]) -> str:
    shot_spec = metadata.get("shot_generation_spec")
    spec_action = shot_spec.get("action") if isinstance(shot_spec, dict) else ""
    source = (
        metadata.get("storyboard_action")
        or spec_action
        or metadata.get("action")
        or metadata.get("source_text")
        or segment.prompt
    )
    return _clean_excerpt(_clean_storyboard_action_text(source), limit=1200)


def _storyboard_action_beats(action: str) -> tuple[str, str]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", str(action or ""))
        if sentence.strip()
    ]
    if len(sentences) <= 2:
        beat = _clean_excerpt(action, limit=320)
        return beat, beat
    initial = _clean_excerpt(" ".join(sentences[:2]), limit=320)
    final = _clean_excerpt(" ".join(sentences[-2:]), limit=320)
    return initial, final


# O frame é uma IMAGEM ESTÁTICA: movimento de câmera e descrições sonoras não
# aparecem nela — essas direções pertencem ao prompt de vídeo, que continua
# recebendo a ação completa do shot.
_CAMERA_DIRECTION_RE = re.compile(
    r"(?i)^[^\S\r\n]*(?:"
    r"c[âa]mera(?:\s+(?:lenta|r[áa]pida|est[áa]tica|sobe|desce|avan[çc]a|recua|"
    r"gira|orbita|se\s+aproxima|se\s+afasta))?|slow\s?motion|close[-\s]?up|"
    r"plano\s+(?:geral|americano|m[ée]dio|detalh?[eo]|fechado|aberto|pr[óo]ximo)|"
    r"primeiro\s+plano|grande\s+plano|contra[-\s]?plano|zoom(?:\s+in|\s+out)?|"
    r"pan(?:or[âa]mic[ao])?\b|tilt|dolly|travelling"
    r")[^\S\r\n]*:?[^\S\r\n]*"
)

_SOUND_WORD_RE = re.compile(
    r"(?i)\b(?:rang\w*|estal\w*|crepit\w*|zumb\w*|eco[ao]m?\b|barulh\w*|"
    r"ru[íi]do\w*|sil[êe]ncio\b|resso\w*|m[úu]sic\w*|sussurr\w*|tinid\w*|"
    r"badal\w*|tambor\w*|cantal\w*|cantam?\b|grit\w*|berr\w*|toqu\w*|"
    r"tocando|soa\b|soando|estridul\w*|chi\w*|sibil\w*|murmur\w*|tril\w*)\b"
)


def _static_image_beat(beat: str, character_names: list[str]) -> str:
    """Adapta o beat da ação para o prompt de frame (imagem estática).

    Remove o prefixo de direção de câmera ("Câmera lenta:", "Close-up:",
    "Plano geral...") e, quando o beat tem várias frases, descarta as frases
    apenas sonoras ("As rodas rangem.") e as frases que SÓ descrevem câmera/
    enquadramento ("Plano geral da praça.") — som e movimento não existem numa
    imagem. Frases com personagem nomeado são sempre mantidas (descrevem ação
    visível) e, se o beat tiver uma única frase, ela é preservada mesmo com
    som (algo é melhor que nada). O prompt de vídeo segue usando a ação
    completa.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(beat or "")) if s.strip()]
    if not sentences:
        return beat
    stripped = [_CAMERA_DIRECTION_RE.sub("", sentence).strip() for sentence in sentences]
    if len(stripped) == 1:
        cleaned = stripped[0] or beat
        return cleaned[:1].upper() + cleaned[1:] if cleaned else beat
    lowered_names = {
        str(name or "").strip().casefold()
        for name in character_names
        if str(name or "").strip()
    }
    kept: list[str] = []
    for sentence in stripped:
        if not sentence:
            continue
        lowered = sentence.casefold()
        # Frase só de câmera/enquadramento ("Plano geral da praça."): a
        # direção foi removida e não sobrou verbo de ação visível útil —
        # descarta se virou muito curta ou sem personagem nomeado.
        if len(lowered.split()) <= 3 and not any(
            name in lowered for name in lowered_names
        ):
            continue
        if _SOUND_WORD_RE.search(sentence) and not any(
            name in lowered for name in lowered_names
        ):
            continue
        kept.append(sentence[:1].upper() + sentence[1:])
    result = " ".join(kept).strip()
    return result or beat


def _action_inside_sentence(value: str) -> str:
    return re.sub(r"^(A|O|Uma|Um)\s+", lambda match: match.group(0).casefold(), value)


def _action_is_fragment(action: str) -> bool:
    """Detecta beats que são apenas um nome/fragmento (ex.: 'DANIEL.').

    Um cue solto sem verbo não descreve ação; usar como frase principal do
    prompt de frame gera instruções sem sentido ("Mostre o momento inicial em
    que DANIEL.").
    """
    text = " ".join(str(action or "").split()).strip().rstrip(".")
    if not text:
        return True
    words = text.split()
    if len(words) <= 2:
        return True
    # Uma só palavra própria em caixa alta ("DANIEL") é um cue, não uma ação.
    if len(words) == 1 and text.isupper():
        return True
    # Sem verbo visível nos primeiros termos e palavras quase todas em caixa alta.
    verb_like = any(
        re.search(r"(?i)(?:\b[a-zà-ÿ]{3,}(?:s|ou|ava|ando|endo|indo)?\b)", word)
        for word in words
        if not word.isupper()
    )
    return not verb_like


def _drop_leading_fragments(text: str) -> str:
    """Remove frases-fragmento do início do beat (ex.: 'DANIEL.' sozinho).

    O particionamento por frases pode deixar um cue solto ('DANIEL.') como
    primeira sentença do beat; copiá-lo para o prompt do frame produz
    instruções sem sentido ("Mostre o momento inicial em que DANIEL.").
    """
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", str(text or ""))
        if sentence.strip()
    ]
    while len(sentences) > 1 and _action_is_fragment(sentences[0]):
        sentences.pop(0)
    return " ".join(sentences)


def segment_frame_prompts(segment: ContinuousVideoSegment) -> dict[str, str]:
    metadata = dict(segment.metadata_json or {})
    action = _storyboard_narrative_action(segment, metadata)
    initial_action, final_action = _storyboard_action_beats(action)
    shot_spec = metadata.get("shot_generation_spec")
    shot_spec = shot_spec if isinstance(shot_spec, dict) else {}
    scene_context = _clean_excerpt(
        str(metadata.get("scene_context") or shot_spec.get("scene_context") or ""),
        limit=320,
    )

    def _resolve_beat(beat: str) -> str:
        if not _action_is_fragment(beat):
            dropped = _drop_leading_fragments(beat)
            return dropped or beat
        # O beat inteiro é um fragmento (ex.: 'DANIEL.'): substitui pelo
        # contexto da cena, que descreve a ação completa.
        return scene_context or beat

    initial_action = _resolve_beat(initial_action)
    final_action = _resolve_beat(final_action)
    initial_action = _clean_excerpt(initial_action, limit=190)
    final_action = _clean_excerpt(final_action, limit=190)
    raw_characters = [
        str(name).strip() for name in metadata.get("characters") or [] if str(name).strip()
    ]
    # O frame inicial é IMAGEM ESTÁTICA: sem direção de câmera e sem frases
    # apenas sonoras ("As rodas rangem."). O prompt de vídeo mantém tudo.
    initial_action = _static_image_beat(initial_action, raw_characters)
    initial_sentence = _action_inside_sentence(initial_action.rstrip(" ."))
    final_sentence = (
        final_action if final_action.endswith((".", "!", "?", "…")) else f"{final_action}."
    )
    # v3 dos frames: o prompt é SÓ a ação, com os personagens referenciados
    # PELO NOME no próprio texto. Todas as imagens do projeto são geradas no
    # mesmo chat, então a identidade visual vem das referências do chat — e
    # local/iluminação saem do texto (decisão do usuário, 2026-09): linhas
    # tipo "A cena acontece..."/"Iluminação: ..." poluíam o prompt sem
    # aumentar a clareza da imagem pedida.
    initial_default = bounded_prompt(
        [f"Crie uma imagem de {initial_sentence}."],
        max_chars=FRAME_PROMPT_MAX_CHARS,
    )
    final_default = bounded_prompt(
        [
            "Crie uma imagem.",
            final_sentence,
            "Mostre a pose final da ação em andamento (o corpo já executou o movimento "
            "principal), não um retrato estático anterior ao movimento.",
        ],
        max_chars=420,
    )
    return {
        "initial": str(metadata.get("initial_frame_prompt_override") or initial_default).strip(),
        "final": str(metadata.get("final_frame_prompt_override") or final_default).strip(),
    }


def frame_provider_prompt(prompt: str, frame_kind: str) -> str:
    """Mantém o prompt visível simples e adiciona as regras somente no envio."""
    clean_prompt = _clean_excerpt(prompt, limit=FRAME_PROMPT_MAX_CHARS)
    technical = (
        "Imagem cinematográfica fotorrealista. Não acrescente texto ou logos."
    )
    return f"{clean_prompt}\n\n{technical}".strip()


async def _approved_references(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
) -> list[ImageReference]:
    metadata = dict(segment.metadata_json or {})
    wanted = {
        str(name).strip().casefold()
        for name in [*(metadata.get("characters") or []), *(metadata.get("locations") or [])]
        if str(name).strip()
    }
    if not wanted:
        return []
    char_rows = await session.execute(select(Character).where(Character.project_id == project_id))
    location_rows = await session.execute(select(Location).where(Location.project_id == project_id))
    targets: list[Any] = [*char_rows.scalars().all(), *location_rows.scalars().all()]
    target_ids = {item.id for item in targets if str(item.name or "").strip().casefold() in wanted}
    if not target_ids:
        return []
    rows = await session.execute(
        select(VisualReference)
        .where(
            VisualReference.project_id == project_id,
            VisualReference.target_id.in_(target_ids),
            VisualReference.asset_id.is_not(None),
            VisualReference.status == "approved",
        )
        .order_by(VisualReference.is_canonical.desc(), VisualReference.created_at.desc())
    )
    references: list[ImageReference] = []
    seen: set[UUID] = set()
    for reference in rows.scalars().all():
        if reference.asset_id in seen:
            continue
        asset = await session.get(Asset, reference.asset_id)
        if asset is None or not str(asset.storage_uri or "").strip():
            continue
        seen.add(reference.asset_id)
        references.append(
            ImageReference(
                uri=str(asset.storage_uri),
                role="canonical" if reference.is_canonical else reference.view_type,
                metadata={"visual_reference_id": str(reference.id)},
            )
        )
        if len(references) >= 4:
            break
    return references


async def _storyboard_frame_references(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
) -> list[ImageReference]:
    references: list[ImageReference] = []
    source_frame_asset_id = getattr(segment, "source_frame_asset_id", None)
    if source_frame_asset_id is not None:
        source_asset = await session.get(Asset, source_frame_asset_id)
        if source_asset is not None and str(source_asset.storage_uri or "").strip():
            references.append(
                ImageReference(
                    uri=str(source_asset.storage_uri),
                    role="initial_frame",
                    metadata={"asset_id": str(source_asset.id)},
                )
            )
    canonical_references = await _approved_references(session, project_id, segment)
    referenced_uris = {item.uri for item in references}
    references.extend(
        reference for reference in canonical_references if reference.uri not in referenced_uris
    )
    return references[:4]


def propagate_approved_storyboard_frame(
    segment: ContinuousVideoSegment,
    following_segments: list[ContinuousVideoSegment],
) -> None:
    """Link the approved final frame forward and invalidate stale downstream frames."""

    if segment.final_frame_asset_id is None or not following_segments:
        return
    next_segment = following_segments[0]
    source_changed = next_segment.source_frame_asset_id != segment.final_frame_asset_id
    next_segment.source_segment_id = segment.id
    next_segment.source_frame_asset_id = segment.final_frame_asset_id
    next_metadata = dict(next_segment.metadata_json or {})
    next_metadata["source_segment_id"] = str(segment.id)
    next_metadata["source_frame_asset_id"] = str(segment.final_frame_asset_id)
    next_metadata["initial_frame_asset_id"] = str(segment.final_frame_asset_id)
    segment_metadata = dict(segment.metadata_json or {})
    if segment_metadata.get("final_frame_storage_uri"):
        next_metadata["source_frame_storage_uri"] = segment_metadata["final_frame_storage_uri"]
    next_segment.metadata_json = next_metadata
    if not source_changed:
        return
    for downstream in following_segments:
        metadata = dict(downstream.metadata_json or {})
        metadata["storyboard_approved"] = False
        metadata["initial_frame_approved"] = False
        metadata["final_frame_approved"] = False
        metadata.pop("final_frame_asset_id", None)
        metadata.pop("final_frame_storage_uri", None)
        downstream.final_frame_asset_id = None
        if downstream is not next_segment:
            downstream.source_segment_id = None
            downstream.source_frame_asset_id = None
            metadata.pop("source_segment_id", None)
            metadata.pop("source_frame_asset_id", None)
            metadata.pop("initial_frame_asset_id", None)
            metadata.pop("source_frame_storage_uri", None)
        downstream.metadata_json = metadata


async def _generate_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    frame_kind: str,
) -> UUID:
    settings = get_settings()
    provider_name = effective_provider_for_channel(settings, "image")
    model = provider_model(settings, provider_name, "image")
    provider = resolve_image_provider(settings, provider_name)
    references = await _storyboard_frame_references(session, project_id, segment)
    result = await provider.generate(
        ImageGenerationRequest(
            prompt=frame_provider_prompt(segment_frame_prompts(segment)[frame_kind], frame_kind),
            model=model,
            aspect_ratio="9:16",
            references=references,
            output_dir=generated_output_dir("image", project_id, settings.local_storage_path),
            metadata={
                "project_id": str(project_id),
                "segment_id": str(segment.id),
                "shot_id": str(segment.shot_id) if segment.shot_id else None,
                "frame_kind": frame_kind,
            },
        )
    )
    metadata = {
        "provider": result.provider,
        "model": result.model,
        "segment_id": str(segment.id),
        "shot_id": str(segment.shot_id) if segment.shot_id else None,
        "frame_kind": frame_kind,
        "technical_role": f"storyboard_{frame_kind}_frame",
        "reference_count": len(references),
    }
    asset = Asset(
        project_id=project_id,
        artifact_id=None,
        kind=AssetKind.IMAGE,
        name=f"Storyboard {segment.segment_number:03d} — {frame_kind}",
        storage_uri=result.storage_uri,
        content_type=result.content_type,
        sha256=result.sha256,
        metadata_json=metadata,
    )
    apply_asset_storage_metadata(asset)
    session.add(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            metadata_json=metadata,
        )
    )
    segment_metadata = dict(segment.metadata_json or {})
    segment_metadata[f"{frame_kind}_frame_asset_id"] = str(asset.id)
    segment_metadata[f"{frame_kind}_frame_storage_uri"] = result.storage_uri
    segment_metadata["storyboard_reference_count"] = len(references)
    segment.metadata_json = segment_metadata
    if frame_kind == "initial":
        segment.source_frame_asset_id = asset.id
    else:
        segment.final_frame_asset_id = asset.id
    await session.flush()
    return asset.id


async def _ensure_package_initial_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    _production_settings: Any,
) -> None:
    """Garante que o segmento tem um source_frame_asset_id.

    Comportamento:
      - Se já tem source_frame_asset_id, nada a fazer.
      - Caso contrário, gera um frame inicial novo.

    Cada segmento sempre recebe um frame inicial próprio, gerado do zero.
    """
    if segment.source_frame_asset_id is not None:
        return

    await _generate_frame(session, project_id, segment, "initial")


async def _generate_segment_initial_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    _production_settings: Any,
) -> UUID:
    return await _generate_frame(session, project_id, segment, "initial")


async def _generate_segment_final_frame(
    session: AsyncSession,
    project_id: UUID,
    segment: ContinuousVideoSegment,
    _production_settings: Any,
) -> UUID:
    return await _generate_frame(session, project_id, segment, "final")
