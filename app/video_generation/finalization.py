"""Serviço de finalização: concatenação dos vídeos dos segmentos em um único vídeo final.

Após todos os segmentos serem aprovados (status "done"), esta etapa permite:
1. Concatenar todos os vídeos em um único arquivo
2. Permitir o download do vídeo final pelo usuário
"""

import asyncio
import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetVersion
from app.config.settings import get_settings
from app.core.enums import AssetKind
from app.providers.media_utils import resolve_ffmpeg_path
from app.storage.service import apply_asset_storage_metadata, resolve_storage_path
from app.storytelling.models import Scene, Shot
from app.video_generation.continuous import (
    continuous_video_segment_is_done,
    list_continuous_video_segments,
)
from app.video_generation.models import ContinuousVideoSegment

logger = logging.getLogger(__name__)

MIN_SEGMENTS_FOR_FINALIZATION = 3


def _segment_has_completed_video(segment: ContinuousVideoSegment) -> bool:
    """Verifica se o segmento tem vídeo gerado ou aprovado."""
    return bool(
        getattr(segment, "generated_video_asset_id", None)
        or getattr(segment, "asset_id", None)
        or continuous_video_segment_is_done(segment)
        or (isinstance(segment.metadata_json, dict) and segment.metadata_json.get("video_asset_id"))
    )


async def check_all_segments_completed(
    session: AsyncSession,
    project_id: UUID,
) -> tuple[bool, int, int]:
    """Verifica se os requisitos de segmentos para finalização foram atingidos.

    Retorna (pode_finalizar, total_segmentos, segmentos_com_video).
    """
    segments = await list_continuous_video_segments(session, project_id)
    if not segments:
        return False, 0, 0

    total = len(segments)
    completed = sum(1 for seg in segments if _segment_has_completed_video(seg))

    # Exige pelo menos 3 vídeos de segmentos criados
    has_minimum = completed >= MIN_SEGMENTS_FOR_FINALIZATION
    is_ready = has_minimum and (completed == total or total < MIN_SEGMENTS_FOR_FINALIZATION)

    return is_ready, total, completed


async def get_finalization_status(
    session: AsyncSession,
    project_id: UUID,
) -> dict[str, Any]:
    """Retorna o status da finalização para um projeto."""
    all_completed, total, completed = await check_all_segments_completed(session, project_id)

    # Verificar se já existe um vídeo final
    result = await session.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.kind == AssetKind.VIDEO,
            Asset.metadata_json["technical_role"].astext == "final_video",
        )
    )
    existing_final = result.scalars().first()

    return {
        "all_segments_completed": all_completed,
        "total_segments": total,
        "completed_segments": completed,
        "min_required_segments": MIN_SEGMENTS_FOR_FINALIZATION,
        "has_min_segments": completed >= MIN_SEGMENTS_FOR_FINALIZATION,
        "has_final_video": existing_final is not None,
        "final_video_asset_id": str(existing_final.id) if existing_final else None,
        "final_video_storage_uri": (
            getattr(existing_final, "storage_uri", None) if existing_final else None
        ),
    }


async def concatenate_videos(
    session: AsyncSession,
    project_id: UUID,
) -> Asset:
    """Concatena todos os vídeos dos segmentos em um único vídeo final.

    Retorna o Asset do vídeo final criado.

    Raises:
        RuntimeError: Se não houver pelo menos 3 segmentos concluídos ou se o ffmpeg falhar
    """
    all_completed, total, completed = await check_all_segments_completed(session, project_id)
    if completed < MIN_SEGMENTS_FOR_FINALIZATION:
        raise RuntimeError(
            f"É necessário ter criado pelo menos {MIN_SEGMENTS_FOR_FINALIZATION} "
            f"vídeos de segmentos para finalizar "
            f"({completed}/{MIN_SEGMENTS_FOR_FINALIZATION} criados)."
        )
    if not all_completed:
        raise RuntimeError(
            "Todos os segmentos precisam ter vídeo antes da finalização "
            f"({completed}/{total} concluídos)."
        )

    # Obter todos os segmentos ordenados por Scene + Shot.
    segments = await list_continuous_video_segments(session, project_id)
    gaps = assembly_gaps(segments)
    if gaps:
        raise RuntimeError("Montagem bloqueada: " + "; ".join(gaps))
    ordered_segments = await order_segments_for_assembly(session, segments)

    # Obter caminhos dos vídeos
    video_paths: list[Path] = []
    for segment in ordered_segments:
        video_uri: str | None = None
        metadata = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
        if metadata.get("video_storage_uri"):
            video_uri = str(metadata["video_storage_uri"])
        elif segment.generated_video_asset_id or segment.asset_id:
            asset_id = segment.generated_video_asset_id or segment.asset_id
            asset = await session.get(Asset, asset_id)
            if asset and asset.storage_uri:
                video_uri = str(asset.storage_uri)

        if video_uri:
            video_path = resolve_storage_path(video_uri)
            if video_path is not None and video_path.is_file():  # noqa: ASYNC240
                video_paths.append(video_path)
            else:
                logger.warning(
                    f"Vídeo do segmento {segment.segment_number} não encontrado no disco: "
                    f"{video_uri}"
                )

    if len(video_paths) < MIN_SEGMENTS_FOR_FINALIZATION:
        raise RuntimeError(
            f"Nenhum ou poucos vídeos de segmento encontrados para concatenação "
            f"({len(video_paths)}/{MIN_SEGMENTS_FOR_FINALIZATION} disponíveis)."
        )

    # Concatenar vídeos usando ffmpeg
    final_video_path = await _concatenate_with_ffmpeg(video_paths, project_id)

    # Criar Asset do vídeo final
    final_asset = await _create_final_video_asset(
        session, project_id, final_video_path, len(video_paths)
    )

    logger.info(f"Vídeo final criado para projeto {project_id}: {final_video_path}")

    return final_asset


def assembly_gaps(segments: list[ContinuousVideoSegment]) -> list[str]:
    gaps: list[str] = []
    for segment in segments:
        is_legacy = not hasattr(segment, "shot_id")
        if not is_legacy and segment.shot_id is None:
            gaps.append(f"segmento {segment.segment_number} sem Shot")
        review_status = str(segment.review_status or "").casefold()
        if review_status not in {"approved", "done"}:
            gaps.append(
                f"shot/segmento {segment.segment_number} sem clip aprovado "
                f"({segment.review_status})"
            )
        if not _segment_has_completed_video(segment):
            gaps.append(f"shot/segmento {segment.segment_number} sem vídeo")
    return gaps


async def order_segments_for_assembly(
    session: AsyncSession,
    segments: list[ContinuousVideoSegment],
) -> list[ContinuousVideoSegment]:
    order: dict[UUID, tuple[int, int]] = {}
    for segment in segments:
        shot_id = getattr(segment, "shot_id", None)
        if shot_id is None:
            continue
        shot = await session.get(Shot, shot_id)
        scene = await session.get(Scene, shot.scene_id) if shot else None
        if shot and scene:
            order[segment.id] = (int(scene.scene_number), int(shot.shot_number))
    return sorted(
        segments,
        key=lambda item: (
            *order.get(getattr(item, "id", UUID(int=0)), (2**31 - 1, 2**31 - 1)),
            item.segment_number,
        ),
    )


async def _concatenate_with_ffmpeg(
    video_paths: list[Path],
    project_id: UUID,
) -> Path:
    """Concatena vídeos usando ffmpeg.

    Usa o método concat demuxer para melhor compatibilidade.
    """
    ffmpeg_path = resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg não encontrado. Instale o ffmpeg para usar esta funcionalidade.")

    # Criar diretório de saída
    settings = get_settings()
    output_dir = settings.local_storage_path / "final_videos" / str(project_id)
    output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    output_path = output_dir / "video_final.mp4"

    # Criar arquivo de lista para o concat demuxer
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as list_file:
        for video_path in video_paths:
            # Usar caminho absoluto com barras normais para o ffmpeg
            absolute_path = video_path.resolve().as_posix()
            list_file.write(f"file '{absolute_path}'\n")
        list_file_path = Path(list_file.name)

    try:
        # Comando ffmpeg para concatenar
        cmd = [
            ffmpeg_path,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file_path),
            "-c",
            "copy",  # Copiar sem re-encoding para manter qualidade
            "-y",  # Sobrescrever se existir
            str(output_path),
        ]

        logger.info(f"Executando ffmpeg: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=300)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("ffmpeg excedeu o limite de 5 minutos") from exc
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode != 0:
            logger.error("ffmpeg falhou: %s", stderr)
            raise RuntimeError(f"ffmpeg falhou ao concatenar vídeos: {stderr[:500]}")

        if not output_path.exists():  # noqa: ASYNC240
            raise RuntimeError("ffmpeg não criou o arquivo de vídeo final")

        # Verificar tamanho do arquivo
        file_size = output_path.stat().st_size  # noqa: ASYNC240
        logger.info(f"Vídeo final criado: {output_path} ({file_size} bytes)")

        return output_path

    finally:
        # Limpar arquivo temporário da lista
        if list_file_path.exists():  # noqa: ASYNC240
            list_file_path.unlink()  # noqa: ASYNC240


async def _create_final_video_asset(
    session: AsyncSession,
    project_id: UUID,
    video_path: Path,
    segment_count: int,
) -> Asset:
    """Cria o Asset do vídeo final."""
    video_sha256 = await asyncio.to_thread(_sha256_file, video_path)

    asset = Asset(
        project_id=project_id,
        artifact_id=None,
        kind=AssetKind.VIDEO,
        name="Vídeo Final",
        storage_uri=video_path.as_posix(),
        content_type="video/mp4",
        sha256=video_sha256,
        metadata_json={
            "provider": "ffmpeg",
            "model": "concatenation",
            "technical_role": "final_video",
            "segment_count": segment_count,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    apply_asset_storage_metadata(asset)
    session.add(asset)
    await session.flush()

    # Registrar versão
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version_number=1,
            storage_uri=asset.storage_uri,
            sha256=asset.sha256,
            metadata_json=asset.metadata_json,
        )
    )

    await session.flush()

    return asset


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def get_final_video_asset(
    session: AsyncSession,
    project_id: UUID,
) -> Asset | None:
    """Retorna o asset do vídeo final se existir."""
    result = await session.execute(
        select(Asset)
        .where(
            Asset.project_id == project_id,
            Asset.kind == AssetKind.VIDEO,
            Asset.metadata_json["technical_role"].astext == "final_video",
        )
        .order_by(Asset.created_at.desc())
    )
    return result.scalars().first()


async def delete_final_video(
    session: AsyncSession,
    project_id: UUID,
) -> bool:
    """Deleta o vídeo final existente (para regenerar)."""
    asset = await get_final_video_asset(session, project_id)
    if asset is None:
        return False

    # Deletar arquivo físico
    storage_uri = getattr(asset, "storage_uri", None)
    if storage_uri:
        file_path = resolve_storage_path(storage_uri)
        if file_path is not None and file_path.is_file():  # noqa: ASYNC240
            file_path.unlink()  # noqa: ASYNC240

    # Deletar registros
    await session.execute(delete(AssetVersion).where(AssetVersion.asset_id == asset.id))
    await session.delete(asset)
    await session.flush()

    return True
