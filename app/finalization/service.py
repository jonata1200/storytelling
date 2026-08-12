import asyncio
import hashlib
import json
import logging
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import (
    ArtifactStatus,
    ArtifactType,
    AssetKind,
    CostEntryType,
    DependencyKind,
    GenerationJobStatus,
    ProjectStatus,
)
from app.costs.models import CostEntry
from app.costs.service import cost_audit_metadata, estimate_operation_cost
from app.finalization import ffmpeg_exporter
from app.finalization.models import Export, SubtitleTrack
from app.finalization.subtitles import safe_area_profile
from app.observability.redaction import redact_secrets
from app.observability.schemas import OperationalEventCreate
from app.observability.service import emit_project_event
from app.projects.models import Artifact, ArtifactVersion
from app.projects.repository import ProjectRepository
from app.providers.media_utils import resolve_ffmpeg_path
from app.providers.speech.service import (
    speech_configuration_status,
    speech_model_from_settings,
    speech_provider_from_settings,
)
from app.providers.speech.types import SpeechRequest
from app.storage.service import apply_asset_storage_metadata
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline, TimelineItem
from app.storyboards.timeline import build_word_alignment
from app.video_generation.models import ContinuousVideoSegment, VideoClip
from app.visual_bible.models import Character
from app.workflows.models import ArtifactDependency
from app.workflows.state_machine import advance_project_status

logger = logging.getLogger(__name__)

DEFAULT_CHARACTER_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)


@dataclass(frozen=True)
class DialogueLine:
    speaker: str
    text: str


@dataclass(frozen=True)
class TimelineAudioAsset:
    path: Path
    start_ms: int


def _concat_file_line(path: Path) -> str:
    return ffmpeg_exporter.concat_file_line(path)


def _render_timeline_video(
    ffmpeg_path: str,
    clip_paths: list[Path],
    output_path: Path,
    profile: dict,
) -> str:
    return ffmpeg_exporter.render_timeline_video(ffmpeg_path, clip_paths, output_path, profile)


def _render_timeline_video_with_audio(
    ffmpeg_path: str,
    clip_paths: list[Path],
    audio_assets: list[TimelineAudioAsset],
    output_path: Path,
    profile: dict,
) -> str:
    if not audio_assets:
        return _render_timeline_video(ffmpeg_path, clip_paths, output_path, profile)
    with tempfile.TemporaryDirectory() as temporary_dir:
        video_only_path = Path(temporary_dir) / "video_only.mp4"
        video_log = _render_timeline_video(ffmpeg_path, clip_paths, video_only_path, profile)
        command = [ffmpeg_path, "-y", "-i", str(video_only_path)]
        for audio in audio_assets:
            command.extend(["-i", str(audio.path)])
        filter_parts = [
            f"[{index}:a]adelay={audio.start_ms}:all=1[a{index}]"
            for index, audio in enumerate(audio_assets, start=1)
        ]
        mixed_inputs = "".join(f"[a{index}]" for index in range(1, len(audio_assets) + 1))
        filter_parts.append(
            f"{mixed_inputs}amix=inputs={len(audio_assets)}:duration=longest:normalize=0[mix]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "0:v:0",
                "-map",
                "[mix]",
                "-c:v",
                "copy",
                "-c:a",
                str(profile.get("audio_codec") or "aac"),
                "-shortest",
                str(output_path),
            ]
        )
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    audio_log = completed.stderr[-1000:] if completed.stderr else ""
    return (
        "FFmpeg rendered the final timeline with character dialogue audio. "
        f"{video_log} {audio_log}"
    )[-2000:]


def export_profile(fps: int = 30, bitrate: str = "8M", embed_subtitles: bool = True) -> dict:
    return {
        "orientation": "vertical",
        "aspect_ratio": "9:16",
        "resolution": "1080x1920",
        "fps": fps,
        "video_codec": "h264",
        "audio_codec": "aac",
        "bitrate": bitrate,
        "embed_subtitles": embed_subtitles,
        "safe_area": safe_area_profile(),
    }


def export_profile_from_payload(
    fps: int = 30,
    bitrate: str = "8M",
    embed_subtitles: bool = True,
    resolution: str = "1080x1920",
    video_codec: str = "h264",
    audio_codec: str = "aac",
) -> dict:
    profile = export_profile(
        fps=fps,
        bitrate=bitrate,
        embed_subtitles=embed_subtitles,
    )
    profile["resolution"] = resolution
    profile["video_codec"] = video_codec
    profile["audio_codec"] = audio_codec
    return profile


def clip_compatibility_errors(clip_paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in clip_paths:
        if not path.exists():
            errors.append(f"Clipe não encontrado: {path.name}")
        elif path.stat().st_size <= 0:
            errors.append(f"Clipe vazio: {path.name}")
    return errors


def _normalized_speaker_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _voice_profile_for_key(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(DEFAULT_CHARACTER_VOICES)
    return DEFAULT_CHARACTER_VOICES[index]


def _profile_voice_id(profile: dict, fallback_key: str) -> str:
    for key in ("voice_profile_id", "voice_id", "speech_voice"):
        value = str(profile.get(key) or "").strip()
        if value:
            return value
    narrative_profile = profile.get("narrative_profile")
    if isinstance(narrative_profile, dict):
        for key in ("voice_profile_id", "voice_id", "speech_voice"):
            value = str(narrative_profile.get(key) or "").strip()
            if value:
                return value
    return _voice_profile_for_key(fallback_key)


def parse_dialogue_lines(dialogue_text: str) -> list[DialogueLine]:
    lines = [line.strip() for line in str(dialogue_text or "").splitlines() if line.strip()]
    parsed: list[DialogueLine] = []
    pending_speaker: str | None = None
    for line in lines:
        colon_match = re.match(r"^([A-Za-zÀ-ÖØ-öø-ÿ0-9 .'_-]{1,40})\s*:\s*(.+)$", line)
        if colon_match:
            parsed.append(
                DialogueLine(
                    speaker=colon_match.group(1).strip(),
                    text=colon_match.group(2).strip(),
                )
            )
            pending_speaker = None
            continue
        if re.fullmatch(r"[A-ZÀ-ÖØ-Þ0-9 .'_-]{2,40}", line):
            pending_speaker = line.title()
            continue
        if pending_speaker:
            parsed.append(DialogueLine(speaker=pending_speaker, text=line))
            pending_speaker = None
            continue
        parsed.append(DialogueLine(speaker="Personagem", text=line))
    return [line for line in parsed if line.text]


async def _character_voice_map(session: AsyncSession, project_id: UUID) -> dict[str, str]:
    result = await session.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    )
    voice_by_key: dict[str, str] = {}
    for character in result.scalars():
        profile = dict(character.canonical_profile or {})
        key = _normalized_speaker_key(
            profile.get("identity_base_name") or character.name or character.id
        )
        voice_profile_id = _profile_voice_id(profile, key)
        if profile.get("voice_profile_id") != voice_profile_id:
            profile["voice_profile_id"] = voice_profile_id
            narrative_profile = dict(profile.get("narrative_profile") or {})
            narrative_profile["voice_profile_id"] = voice_profile_id
            profile["narrative_profile"] = narrative_profile
            character.canonical_profile = profile
        names = {
            _normalized_speaker_key(character.name),
            _normalized_speaker_key(profile.get("name")),
            _normalized_speaker_key(profile.get("identity_base_name")),
        }
        for name in names:
            if name:
                voice_by_key[name] = voice_profile_id
    return voice_by_key


def _voice_for_speaker(speaker: str, voice_by_key: dict[str, str]) -> str:
    speaker_key = _normalized_speaker_key(speaker)
    if speaker_key in voice_by_key:
        return voice_by_key[speaker_key]
    for key, voice in voice_by_key.items():
        if key and (key in speaker_key or speaker_key in key):
            return voice
    return _voice_profile_for_key(speaker_key or "personagem")


def final_timeline_coverage_errors(
    frames: list[StoryboardFrame], selected_clips: list[VideoClip]
) -> list[str]:
    errors: list[str] = []
    if not frames:
        return ["storyboard sem frames"]
    selected_by_frame: dict[UUID, list[VideoClip]] = {}
    for clip in selected_clips:
        selected_by_frame.setdefault(clip.storyboard_frame_id, []).append(clip)
    missing = [frame for frame in frames if frame.id not in selected_by_frame]
    duplicated = [
        frame_id for frame_id, clips in selected_by_frame.items() if len(clips) > 1
    ]
    extra = [
        frame_id
        for frame_id in selected_by_frame
        if frame_id not in {frame.id for frame in frames}
    ]
    if missing:
        errors.append(f"{len(missing)} frame(s) sem clipe selecionado")
    if duplicated:
        errors.append(f"{len(duplicated)} frame(s) com mais de um clipe selecionado")
    if extra:
        errors.append(f"{len(extra)} clipe(s) selecionado(s) sem frame correspondente")
    return errors


def continuous_video_timeline_coverage_errors(
    segments: list[ContinuousVideoSegment],
    asset_by_id: dict[UUID, Asset],
) -> list[str]:
    errors: list[str] = []
    if not segments:
        return ["video continuo sem segmentos"]
    ordered = sorted(segments, key=lambda item: int(item.segment_number or 0))
    expected_numbers = list(range(1, len(ordered) + 1))
    actual_numbers = [int(segment.segment_number or 0) for segment in ordered]
    if actual_numbers != expected_numbers:
        errors.append("sequencia de segmentos incompleta")
    for segment in ordered:
        if segment.status != GenerationJobStatus.SUCCEEDED:
            errors.append(f"segmento {segment.segment_number} sem video gerado")
        if str(getattr(segment, "review_status", "") or "").lower() != "approved":
            errors.append(f"segmento {segment.segment_number} nao aprovado")
        if int(segment.duration_seconds or 0) <= 0:
            errors.append(f"segmento {segment.segment_number} com duracao invalida")
        asset_id = segment.generated_video_asset_id or segment.asset_id
        asset = asset_by_id.get(asset_id) if asset_id is not None else None
        if asset is None:
            errors.append(f"segmento {segment.segment_number} sem asset de video")
            continue
        if asset.kind != AssetKind.VIDEO or not str(asset.content_type or "").startswith("video/"):
            errors.append(f"segmento {segment.segment_number} sem asset de video valido")
            continue
        if _local_video_asset_path(str(asset.storage_uri or "")) is None:
            errors.append(f"segmento {segment.segment_number} sem arquivo local de video")
    return errors


def _local_video_asset_path(storage_uri: str) -> Path | None:
    if not storage_uri:
        return None
    storage_root = get_settings().local_storage_path.resolve()
    path = Path(storage_uri)
    candidate = path if path.is_absolute() else path.resolve()
    try:
        candidate.relative_to(storage_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


async def _timeline_video_asset_paths(session: AsyncSession, timeline_id: UUID) -> list[Path]:
    result = await session.execute(
        select(Asset)
        .join(TimelineItem, TimelineItem.source_asset_id == Asset.id)
        .where(TimelineItem.timeline_id == timeline_id, TimelineItem.layer == "video")
        .order_by(TimelineItem.order_index)
    )
    paths: list[Path] = []
    for asset in result.scalars():
        if asset.kind != AssetKind.VIDEO or not str(asset.content_type or "").startswith("video/"):
            return []
        path = _local_video_asset_path(asset.storage_uri)
        if path is None:
            return []
        paths.append(path)
    return paths


async def _timeline_audio_assets(
    session: AsyncSession, timeline_id: UUID
) -> list[TimelineAudioAsset]:
    result = await session.execute(
        select(Asset, TimelineItem)
        .join(TimelineItem, TimelineItem.source_asset_id == Asset.id)
        .where(TimelineItem.timeline_id == timeline_id, TimelineItem.layer == "audio")
        .order_by(TimelineItem.start_ms, TimelineItem.order_index)
    )
    assets: list[TimelineAudioAsset] = []
    for asset, item in result.all():
        if asset.kind != AssetKind.AUDIO or not str(asset.content_type or "").startswith(
            "audio/"
        ):
            return []
        candidate = _local_video_asset_path(asset.storage_uri)
        if candidate is None:
            return []
        assets.append(TimelineAudioAsset(path=candidate, start_ms=item.start_ms))
    return assets


async def _timeline_continuous_segment_manifest(
    session: AsyncSession,
    timeline_id: UUID,
) -> list[dict[str, object]]:
    result = await session.execute(
        select(TimelineItem)
        .where(TimelineItem.timeline_id == timeline_id, TimelineItem.layer == "video")
        .order_by(TimelineItem.order_index)
    )
    entries: list[dict[str, object]] = []
    for item in result.scalars():
        properties = item.properties if isinstance(item.properties, dict) else {}
        if properties.get("source") != "continuous_video":
            continue
        entries.append(
            {
                "segment_id": properties.get("segment_id"),
                "segment_number": properties.get("segment_number"),
                "source_asset_id": str(item.source_asset_id) if item.source_asset_id else None,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "review_status": properties.get("review_status"),
            }
        )
    return entries


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
            change_note="Generated by phase 7 finalization workflow",
        )
    )
    await session.flush()
    return artifact


async def _add_dependency(session: AsyncSession, upstream: UUID, downstream: UUID) -> None:
    session.add(
        ArtifactDependency(
            upstream_artifact_id=upstream,
            downstream_artifact_id=downstream,
            dependency_kind=DependencyKind.DERIVED_FROM,
        )
    )


async def _ensure_continuous_video_asset_artifact(
    session: AsyncSession,
    segment: ContinuousVideoSegment,
    asset: Asset,
) -> Artifact:
    if asset.artifact_id is not None:
        existing = await session.get(Artifact, asset.artifact_id)
        if existing is not None:
            return existing
    artifact = await _create_artifact(
        session,
        segment.project_id,
        ArtifactType.VIDEO_CLIP,
        f"Segmento continuo {int(segment.segment_number or 0):03d}",
        {
            "source": "continuous_video",
            "segment_id": str(segment.id),
            "segment_number": segment.segment_number,
            "asset_id": str(asset.id),
        },
    )
    asset.artifact_id = artifact.id
    await session.flush()
    return artifact


async def _add_dialogue_audio_items(
    session: AsyncSession,
    project_id: UUID,
    timeline: Timeline,
    timeline_artifact: Artifact,
    frame_by_id: dict[UUID, StoryboardFrame],
    clip_start_ms: dict[UUID, int],
    first_audio_order_index: int,
) -> int:
    dialogue_frames = [
        frame for frame in frame_by_id.values() if parse_dialogue_lines(frame.dialogue_text)
    ]
    if not dialogue_frames:
        return 0

    settings = get_settings()
    speech_ready, speech_message, _speech_details = speech_configuration_status(settings)
    if not speech_ready:
        raise ValueError(speech_message)
    provider = speech_provider_from_settings()
    speech_model = speech_model_from_settings(settings)
    output_dir = settings.local_storage_path / "dialogue" / str(project_id)
    voice_by_key = await _character_voice_map(session, project_id)
    order_index = first_audio_order_index
    created_count = 0

    for frame in sorted(dialogue_frames, key=lambda item: item.frame_number):
        frame_start_ms = clip_start_ms.get(frame.id)
        if frame_start_ms is None:
            continue
        frame_end_ms = frame_start_ms + frame.duration_seconds * 1000
        cursor_ms = frame_start_ms
        for dialogue in parse_dialogue_lines(frame.dialogue_text):
            voice_profile_id = _voice_for_speaker(dialogue.speaker, voice_by_key)
            speech_result = await provider.synthesize(
                SpeechRequest(
                    text=dialogue.text,
                    voice_profile_id=voice_profile_id,
                    output_dir=output_dir,
                    model=speech_model,
                )
            )
            duration_ms = max(1, speech_result.duration_seconds) * 1000
            start_ms = min(cursor_ms, max(frame_start_ms, frame_end_ms - 1))
            end_ms = min(frame_end_ms, start_ms + duration_ms)
            truncated_ms = max(0, (start_ms + duration_ms) - frame_end_ms)
            if truncated_ms:
                logger.warning(
                    "dialogue_truncated frame=%s speaker=%s truncated_ms=%s",
                    frame.frame_number,
                    dialogue.speaker,
                    truncated_ms,
                )
            alignment = speech_result.alignment or build_word_alignment(
                dialogue.text,
                speech_result.duration_seconds,
            )
            artifact = await _create_artifact(
                session,
                project_id,
                ArtifactType.AUDIO_TRACK,
                f"Diálogo {dialogue.speaker}",
                {
                    "speaker": dialogue.speaker,
                    "voice_profile_id": voice_profile_id,
                    "storyboard_frame_id": str(frame.id),
                    "text": dialogue.text,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "provider": speech_result.provider,
                    "model": speech_result.model,
                },
            )
            await _add_dependency(session, frame.artifact_id, artifact.id)
            await _add_dependency(session, artifact.id, timeline_artifact.id)
            asset = Asset(
                project_id=project_id,
                artifact_id=artifact.id,
                kind=AssetKind.AUDIO,
                name=f"Voz {dialogue.speaker}",
                storage_uri=speech_result.storage_uri,
                content_type=speech_result.content_type,
                sha256=speech_result.sha256,
                metadata_json={
                    "speaker": dialogue.speaker,
                    "voice_profile_id": voice_profile_id,
                    "provider": speech_result.provider,
                    "model": speech_result.model,
                    "storyboard_frame_id": str(frame.id),
                },
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
                    metadata_json=asset.metadata_json,
                )
            )
            audio_track = AudioTrack(
                project_id=project_id,
                artifact_id=artifact.id,
                name=f"Voz {dialogue.speaker}",
                track_type="character_dialogue",
                duration_seconds=speech_result.duration_seconds,
                transcript=dialogue.text,
                alignment=alignment,
            )
            session.add(audio_track)
            session.add(
                TimelineItem(
                    timeline_id=timeline.id,
                    project_id=project_id,
                    source_artifact_id=artifact.id,
                    source_asset_id=asset.id,
                    layer="audio",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    order_index=order_index,
                    properties={
                        "track_type": "character_dialogue",
                        "speaker": dialogue.speaker,
                        "voice_profile_id": voice_profile_id,
                        "storyboard_frame_id": str(frame.id),
                        **({"truncated_ms": truncated_ms} if truncated_ms else {}),
                    },
                )
            )
            cost_estimate = estimate_operation_cost(
                "speech_generation",
                Decimal(max(1, len(dialogue.text))) / Decimal("1000"),
                provider=speech_result.provider,
                model=speech_result.model,
            )
            session.add(
                CostEntry(
                    project_id=project_id,
                    artifact_id=artifact.id,
                    entry_type=CostEntryType.ESTIMATE,
                    provider=speech_result.provider,
                    model=speech_result.model,
                    operation="speech_generation",
                    quantity=cost_estimate.quantity,
                    unit=cost_estimate.unit,
                    unit_cost=cost_estimate.unit_cost,
                    total_cost=cost_estimate.estimated,
                    currency=cost_estimate.currency,
                    metadata_json=cost_audit_metadata(
                        estimated_cost=cost_estimate.estimated,
                        final_budget_cost=cost_estimate.estimated,
                        stage="dialogue",
                        extra={
                            "asset_id": str(asset.id),
                            "speaker": dialogue.speaker,
                            "voice_profile_id": voice_profile_id,
                        },
                    ),
                )
            )
            await emit_project_event(
                session,
                OperationalEventCreate(
                    project_id=project_id,
                    artifact_id=artifact.id,
                    event_type="speech_generation",
                    status="succeeded",
                    provider=speech_result.provider,
                    model=speech_result.model,
                    operation="speech_generation",
                    estimated_cost=cost_estimate.estimated,
                    message="Voz de personagem sintetizada",
                    details={
                        "asset_id": str(asset.id),
                        "speaker": dialogue.speaker,
                        "voice_profile_id": voice_profile_id,
                        "storyboard_frame_id": str(frame.id),
                        **({"truncated_ms": truncated_ms} if truncated_ms else {}),
                    },
                ),
            )
            created_count += 1
            order_index += 1
            cursor_ms = end_ms
    return created_count


async def create_final_timeline(
    session: AsyncSession,
    project_id: UUID,
    animatic_id: UUID | None = None,
) -> Timeline | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None
    if animatic_id is not None:
        animatic = await session.get(Animatic, animatic_id)
        if animatic is None or animatic.project_id != project_id:
            return None

    continuous_result = await session.execute(
        select(ContinuousVideoSegment)
        .where(ContinuousVideoSegment.project_id == project_id)
        .order_by(ContinuousVideoSegment.segment_number)
    )
    continuous_segments = list(continuous_result.scalars())
    if continuous_segments:
        asset_ids = {
            asset_id
            for segment in continuous_segments
            for asset_id in (segment.generated_video_asset_id, segment.asset_id)
            if asset_id is not None
        }
        asset_by_id: dict[UUID, Asset] = {}
        if asset_ids:
            asset_result = await session.execute(
                select(Asset).where(Asset.project_id == project_id, Asset.id.in_(asset_ids))
            )
            asset_by_id = {asset.id: asset for asset in asset_result.scalars()}
        coverage_errors = continuous_video_timeline_coverage_errors(
            continuous_segments,
            asset_by_id,
        )
        if coverage_errors:
            raise ValueError("Timeline final incompleta: " + "; ".join(coverage_errors))
        approved_segments = sorted(
            continuous_segments,
            key=lambda item: int(item.segment_number or 0),
        )
        duration_seconds = sum(int(segment.duration_seconds or 0) for segment in approved_segments)
        artifact = await _create_artifact(
            session,
            project_id,
            ArtifactType.TIMELINE,
            "Timeline final",
            {
                "source": "continuous_video",
                "segment_count": len(approved_segments),
                "duration_seconds": duration_seconds,
            },
        )
        timeline = Timeline(
            project_id=project_id,
            artifact_id=artifact.id,
            animatic_id=None,
            name="Timeline final",
            duration_seconds=duration_seconds,
            profile={
                **export_profile(),
                "source": "continuous_video",
            },
        )
        session.add(timeline)
        await session.flush()
        cursor_ms = 0
        for index, segment in enumerate(approved_segments, start=1):
            asset_id = segment.generated_video_asset_id or segment.asset_id
            asset = asset_by_id[asset_id] if asset_id is not None else None
            if asset is None:
                raise ValueError(f"Segmento {segment.segment_number} sem asset de video")
            source_artifact = await _ensure_continuous_video_asset_artifact(
                session,
                segment,
                asset,
            )
            duration_ms = int(segment.duration_seconds or 0) * 1000
            await _add_dependency(session, source_artifact.id, artifact.id)
            session.add(
                TimelineItem(
                    timeline_id=timeline.id,
                    project_id=project_id,
                    source_artifact_id=source_artifact.id,
                    source_asset_id=asset.id,
                    layer="video",
                    start_ms=cursor_ms,
                    end_ms=cursor_ms + duration_ms,
                    order_index=index,
                    properties={
                        "source": "continuous_video",
                        "segment_id": str(segment.id),
                        "segment_number": segment.segment_number,
                        "review_status": segment.review_status,
                    },
                )
            )
            cursor_ms += duration_ms
        advance_project_status(project, ProjectStatus.ASSEMBLY)
        await session.commit()
        await session.refresh(timeline)
        return timeline

    frame_result = await session.execute(
        select(StoryboardFrame)
        .where(StoryboardFrame.project_id == project_id)
        .order_by(StoryboardFrame.frame_number)
    )
    frames = list(frame_result.scalars())
    clip_result = await session.execute(
        select(VideoClip)
        .join(StoryboardFrame, VideoClip.storyboard_frame_id == StoryboardFrame.id)
        .where(VideoClip.project_id == project_id, VideoClip.selected.is_(True))
        .order_by(StoryboardFrame.frame_number, VideoClip.variant_index)
    )
    clips = list(clip_result.scalars())
    if not clips:
        return None
    coverage_errors = final_timeline_coverage_errors(frames, clips)
    if coverage_errors:
        raise ValueError("Timeline final incompleta: " + "; ".join(coverage_errors))

    frame_by_id = {frame.id: frame for frame in frames}
    duration_seconds = sum(clip.duration_seconds for clip in clips)
    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.TIMELINE,
        "Timeline final",
        {"clip_count": len(clips), "duration_seconds": duration_seconds},
    )
    timeline = Timeline(
        project_id=project_id,
        artifact_id=artifact.id,
        animatic_id=animatic_id,
        name="Timeline final",
        duration_seconds=duration_seconds,
        profile=export_profile(),
    )
    session.add(timeline)
    await session.flush()

    cursor_ms = 0
    clip_start_ms: dict[UUID, int] = {}
    for index, clip in enumerate(clips, start=1):
        duration_ms = clip.duration_seconds * 1000
        clip_start_ms[clip.storyboard_frame_id] = cursor_ms
        await _add_dependency(session, clip.artifact_id, artifact.id)
        session.add(
            TimelineItem(
                timeline_id=timeline.id,
                project_id=project_id,
                source_artifact_id=clip.artifact_id,
                source_asset_id=clip.asset_id,
                layer="video",
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
                order_index=index,
                properties={"clip_id": str(clip.id), "selected": clip.selected},
            )
        )
        cursor_ms += duration_ms
    dialogue_audio_count = await _add_dialogue_audio_items(
        session,
        project_id,
        timeline,
        artifact,
        frame_by_id,
        clip_start_ms,
        len(clips) + 1,
    )
    if dialogue_audio_count:
        timeline.profile = {
            **dict(timeline.profile or {}),
            "audio_mode": "dialogue_only",
            "dialogue_audio_count": dialogue_audio_count,
        }

    advance_project_status(project, ProjectStatus.ASSEMBLY)
    await session.commit()
    await session.refresh(timeline)
    return timeline


async def export_timeline(
    session: AsyncSession,
    project_id: UUID,
    timeline_id: UUID,
    subtitle_track_id: UUID | None = None,
    fps: int = 30,
    bitrate: str = "8M",
    embed_subtitles: bool = True,
    resolution: str = "1080x1920",
    video_codec: str = "h264",
    audio_codec: str = "aac",
) -> Export | None:
    project = await ProjectRepository(session).get_project(project_id)
    timeline = await session.get(Timeline, timeline_id)
    if project is None or timeline is None or timeline.project_id != project_id:
        return None

    subtitle = None
    if subtitle_track_id is not None:
        subtitle = await session.get(SubtitleTrack, subtitle_track_id)
        if subtitle is None or subtitle.project_id != project_id:
            return None

    profile = export_profile_from_payload(
        fps=fps,
        bitrate=bitrate,
        embed_subtitles=embed_subtitles,
        resolution=resolution,
        video_codec=video_codec,
        audio_codec=audio_codec,
    )
    settings = get_settings()
    export_dir = settings.local_storage_path / "exports" / str(project_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = resolve_ffmpeg_path(settings.ffmpeg_path)
    status = "MANIFEST_ONLY"
    output_path = export_dir / f"export_{uuid4().hex[:8]}.json"
    render_log = "FFmpeg not found; wrote structured export manifest."
    manifest: dict[str, object] = {
        "timeline_id": str(timeline.id),
        "subtitle_track_id": str(subtitle.id) if subtitle else None,
        "profile": profile,
        "duration_seconds": timeline.duration_seconds,
        "ffmpeg_path": ffmpeg_path,
    }
    continuous_segment_manifest = await _timeline_continuous_segment_manifest(session, timeline.id)
    if continuous_segment_manifest:
        manifest["source"] = "continuous_video"
        manifest["continuous_segments"] = continuous_segment_manifest
    asset_kind = AssetKind.DOCUMENT
    content_type = "application/json"
    if ffmpeg_path:
        clip_paths = await _timeline_video_asset_paths(session, timeline.id)
        audio_assets = await _timeline_audio_assets(session, timeline.id)
        manifest["clip_count"] = len(clip_paths)
        manifest["audio_track_count"] = len(audio_assets)
        compatibility_errors = clip_compatibility_errors(clip_paths)
        manifest["compatibility_errors"] = compatibility_errors
        if clip_paths:
            mp4_path = export_dir / f"export_{uuid4().hex[:8]}.mp4"
            try:
                ffmpeg_log = await asyncio.to_thread(
                    _render_timeline_video_with_audio,
                    ffmpeg_path,
                    clip_paths,
                    audio_assets,
                    mp4_path,
                    profile,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                render_log = (
                    "FFmpeg render failed; wrote structured export manifest. "
                    f"{redact_secrets(exc)}"
                )
                output_path.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8"
                )
            else:
                status = "RENDERED"
                output_path = mp4_path
                asset_kind = AssetKind.VIDEO
                content_type = "video/mp4"
                render_log = (
                    "FFmpeg rendered the final timeline with local video and dialogue assets."
                    if not ffmpeg_log
                    else (
                        "FFmpeg rendered the final timeline with local video and dialogue assets. "
                        f"{ffmpeg_log}"
                    )
                )
        else:
            render_log = (
                "FFmpeg found, but no local video clip assets were available; "
                "wrote structured export manifest."
            )
            output_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8"
            )
    else:
        output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    artifact = await _create_artifact(
        session,
        project_id,
        ArtifactType.EXPORT,
        "Exportacao final",
        manifest,
        ArtifactStatus.READY_FOR_REVIEW,
    )
    await _add_dependency(session, timeline.artifact_id, artifact.id)
    if subtitle is not None:
        await _add_dependency(session, subtitle.artifact_id, artifact.id)

    asset = Asset(
        project_id=project_id,
        artifact_id=artifact.id,
        kind=asset_kind,
        name="Exportacao final",
        storage_uri=output_path.as_posix(),
        content_type=content_type,
        sha256=None,
        metadata_json={"status": status, "ffmpeg_available": ffmpeg_path is not None},
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
            metadata_json=asset.metadata_json,
        )
    )
    export = Export(
        project_id=project_id,
        artifact_id=artifact.id,
        timeline_id=timeline.id,
        subtitle_track_id=subtitle.id if subtitle else None,
        asset_id=asset.id,
        status=status,
        profile=profile,
        duration_seconds=timeline.duration_seconds,
        output_uri=asset.storage_uri,
        render_log=render_log,
    )
    session.add(export)
    await emit_project_event(
        session,
        OperationalEventCreate(
            project_id=project_id,
            artifact_id=artifact.id,
            event_type="export",
            status="succeeded" if status == "RENDERED" else "degraded",
            operation="final_export",
            message=render_log,
            details={
                "asset_id": str(asset.id),
                "status": status,
                "ffmpeg_available": ffmpeg_path is not None,
            },
        ),
    )
    advance_project_status(project, ProjectStatus.FINAL_APPROVAL)
    await session.commit()
    await session.refresh(export)
    return export
