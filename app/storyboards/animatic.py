import json
import sys
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.core.enums import ArtifactType, AssetKind, ProjectStatus
from app.projects.repository import ProjectRepository
from app.storyboards.models import Animatic, AudioTrack, StoryboardFrame, Timeline, TimelineItem
from app.storyboards.prompts import _prompt_hash
from app.storyboards.timeline import build_visual_timeline_items, build_word_alignment
from app.storytelling.models import Script
from app.workflows.state_machine import advance_project_status


def _service_attr(name: str) -> Any:
    service = sys.modules["app.storyboards.service"]
    return getattr(service, name)


async def _create_provisional_narration(
    session: AsyncSession, project_id: UUID, frames: list[StoryboardFrame]
) -> AudioTrack:
    transcript = " ".join(
        frame.narration_text for frame in frames if frame.narration_text.strip()
    ).strip()
    duration_seconds = sum(frame.duration_seconds for frame in frames)
    alignment = build_word_alignment(transcript, duration_seconds)
    artifact = await _service_attr("_create_artifact")(
        session,
        project_id,
        ArtifactType.AUDIO_TRACK,
        "Narracao provisoria",
        {"transcript": transcript, "alignment": alignment, "duration_seconds": duration_seconds},
    )
    track = AudioTrack(
        project_id=project_id,
        artifact_id=artifact.id,
        name="Narracao provisoria",
        track_type="provisional_narration",
        duration_seconds=duration_seconds,
        transcript=transcript,
        alignment=alignment,
    )
    session.add(track)
    return track


def _animatic_frame_signature(frames: list[StoryboardFrame]) -> list[dict]:
    return [
        {
            "frame_id": str(frame.id),
            "asset_id": str(frame.asset_id),
            "duration_seconds": frame.duration_seconds,
            "frame_fingerprint": (frame.metadata_json or {}).get("frame_fingerprint")
            or _prompt_hash(
                json.dumps(
                    {
                        "shot_id": str(frame.shot_id),
                        "duration_seconds": frame.duration_seconds,
                        "narration_text": frame.narration_text,
                        "dialogue_text": frame.dialogue_text,
                        "prompt": frame.prompt,
                    },
                    sort_keys=True,
                    ensure_ascii=True,
                )
            ),
        }
        for frame in sorted(frames, key=lambda item: item.frame_number)
    ]


def _animatic_fingerprint(frames: list[StoryboardFrame]) -> str:
    return _prompt_hash(
        json.dumps(_animatic_frame_signature(frames), sort_keys=True, ensure_ascii=True)
    )


async def _existing_animatic_bundle(
    session: AsyncSession, project_id: UUID, fingerprint: str
) -> tuple[AudioTrack, Animatic, Timeline, list[TimelineItem]] | None:
    result = await session.execute(
        select(Animatic)
        .where(Animatic.project_id == project_id)
        .order_by(Animatic.created_at.desc())
    )
    for animatic in result.scalars():
        if (animatic.manifest or {}).get("frames_fingerprint") != fingerprint:
            continue
        if animatic.audio_track_id is None:
            continue
        audio_track = await session.get(AudioTrack, animatic.audio_track_id)
        timeline_result = await session.execute(
            select(Timeline)
            .where(Timeline.project_id == project_id, Timeline.animatic_id == animatic.id)
            .order_by(Timeline.created_at.desc())
            .limit(1)
        )
        timeline = timeline_result.scalars().first()
        if audio_track is None or timeline is None:
            continue
        item_result = await session.execute(
            select(TimelineItem)
            .where(TimelineItem.timeline_id == timeline.id)
            .order_by(TimelineItem.order_index)
        )
        return audio_track, animatic, timeline, list(item_result.scalars())
    return None


async def generate_animatic_bundle(
    session: AsyncSession, project_id: UUID, script_id: UUID
) -> tuple[AudioTrack, Animatic, Timeline, list[TimelineItem]] | None:
    project = await ProjectRepository(session).get_project(project_id)
    script = await session.get(Script, script_id)
    if project is None or script is None or script.project_id != project_id:
        return None

    frames = await _service_attr("list_storyboard_frames")(session, project_id, script_id)
    if not frames:
        frames = (
            await _service_attr("generate_storyboard_frames")(session, project_id, script_id)
            or []
        )
    if not frames:
        return None

    frames_fingerprint = _animatic_fingerprint(frames)
    existing_bundle = await _existing_animatic_bundle(session, project_id, frames_fingerprint)
    if existing_bundle is not None:
        return existing_bundle

    audio_track = await _create_provisional_narration(session, project_id, frames)
    await session.flush()

    visual_inputs = [
        (
            frame.artifact_id,
            frame.asset_id,
            frame.duration_seconds,
            {"frame_id": str(frame.id), "motion": "slow_push_in"},
        )
        for frame in frames
    ]
    draft_items = build_visual_timeline_items(visual_inputs)
    duration_seconds = max(item.end_ms for item in draft_items) // 1000
    manifest = {
        "version": 1,
        "duration_seconds": duration_seconds,
        "frames_fingerprint": frames_fingerprint,
        "frames": [
            {
                "frame_id": str(frame.id),
                "asset_id": str(frame.asset_id),
                "duration_seconds": frame.duration_seconds,
                "narration_text": frame.narration_text,
                "frame_fingerprint": (frame.metadata_json or {}).get("frame_fingerprint"),
            }
            for frame in frames
        ],
        "audio_track_id": str(audio_track.id),
    }

    settings_factory = _service_attr("get_settings")
    settings = settings_factory()
    manifest_dir = settings.local_storage_path / "animatics" / str(project_id)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"animatic_{uuid4().hex[:8]}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    animatic_artifact = await _service_attr("_create_artifact")(
        session,
        project_id,
        ArtifactType.ANIMATIC,
        "Animatic preliminar",
        manifest,
    )
    await _service_attr("_add_dependency")(session, audio_track.artifact_id, animatic_artifact.id)
    for frame in frames:
        await _service_attr("_add_dependency")(session, frame.artifact_id, animatic_artifact.id)

    manifest_asset = Asset(
        project_id=project_id,
        artifact_id=animatic_artifact.id,
        kind=AssetKind.DOCUMENT,
        name="Animatic manifest",
        storage_uri=manifest_path.as_posix(),
        content_type="application/json",
        sha256=None,
        metadata_json={"kind": "animatic_manifest"},
    )
    session.add(manifest_asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=manifest_asset.id,
            version_number=1,
            storage_uri=manifest_asset.storage_uri,
            sha256=manifest_asset.sha256,
            metadata_json=manifest_asset.metadata_json,
        )
    )

    animatic = Animatic(
        project_id=project_id,
        artifact_id=animatic_artifact.id,
        audio_track_id=audio_track.id,
        name="Animatic preliminar",
        duration_seconds=duration_seconds,
        manifest=manifest,
    )
    session.add(animatic)
    await session.flush()

    timeline_artifact = await _service_attr("_create_artifact")(
        session,
        project_id,
        ArtifactType.TIMELINE,
        "Timeline preliminar",
        {"animatic_id": str(animatic.id), "duration_seconds": duration_seconds},
    )
    await _service_attr("_add_dependency")(session, animatic_artifact.id, timeline_artifact.id)
    timeline = Timeline(
        project_id=project_id,
        artifact_id=timeline_artifact.id,
        animatic_id=animatic.id,
        name="Timeline preliminar",
        duration_seconds=duration_seconds,
        profile={"aspect_ratio": "9:16", "resolution": "1080x1920", "fps": 30},
    )
    session.add(timeline)
    await session.flush()

    items: list[TimelineItem] = []
    for draft in draft_items:
        item = TimelineItem(
            timeline_id=timeline.id,
            project_id=project_id,
            source_artifact_id=draft.source_artifact_id,
            source_asset_id=draft.source_asset_id,
            layer=draft.layer,
            start_ms=draft.start_ms,
            end_ms=draft.end_ms,
            order_index=draft.order_index,
            properties=draft.properties,
        )
        session.add(item)
        items.append(item)

    audio_item = TimelineItem(
        timeline_id=timeline.id,
        project_id=project_id,
        source_artifact_id=audio_track.artifact_id,
        source_asset_id=None,
        layer="audio",
        start_ms=0,
        end_ms=duration_seconds * 1000,
        order_index=len(items) + 1,
        properties={"track_type": audio_track.track_type},
    )
    session.add(audio_item)
    items.append(audio_item)

    advance_project_status(project, ProjectStatus.PRODUCTION_PLANNING)
    await session.commit()
    await session.refresh(audio_track)
    await session.refresh(animatic)
    await session.refresh(timeline)
    for item in items:
        await session.refresh(item)
    return audio_track, animatic, timeline, items
