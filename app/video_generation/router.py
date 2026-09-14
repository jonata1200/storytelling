from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset
from app.core.auth import verify_api_token
from app.database.session import get_session
from app.storage.service import resolve_storage_path
from app.video_generation.continuous import (
    approve_continuous_video_segment,
    delete_all_continuous_video_segments,
    delete_continuous_video_segment,
    list_continuous_video_segments,
    plan_continuous_video_segments,
    prepare_continuous_video_package,
    reject_continuous_video_segment,
    update_continuous_video_segment_prompt,
)
from app.video_generation.continuous_review import (
    select_continuous_video_segment_variant,
)
from app.video_generation.schemas import (
    ContinuousVideoPlanningRead,
    ContinuousVideoPlanRead,
    ContinuousVideoPlanSegmentsRequest,
    ContinuousVideoPreparationRead,
    ContinuousVideoPrepareRequest,
    ContinuousVideoReviewRequest,
    ContinuousVideoSegmentPromptUpdate,
    ContinuousVideoSegmentRead,
    ContinuousVideoVariantSelectRequest,
    GenerationJobRead,
    VideoClipRead,
)
from app.video_generation.service import (
    get_job_status,
    list_video_clips,
)

router = APIRouter(prefix="/video/projects", tags=["video"])


@router.post("/{project_id}/continuous/plan", response_model=ContinuousVideoPlanningRead)
async def post_plan_continuous_video_segments(
    project_id: UUID,
    payload: ContinuousVideoPlanSegmentsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoPlanningRead:
    try:
        plan, segments, validation_errors = await plan_continuous_video_segments(
            session,
            project_id,
            segment_duration_seconds=payload.segment_duration_seconds,
            provider=payload.provider,
            model=payload.model,
            replace_existing=payload.replace_existing,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContinuousVideoPlanningRead(
        plan=ContinuousVideoPlanRead.model_validate(plan),
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
        validation_errors=validation_errors,
    )


@router.post("/{project_id}/continuous/prepare", response_model=ContinuousVideoPreparationRead)
async def post_prepare_continuous_video_package(
    project_id: UUID,
    payload: ContinuousVideoPrepareRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoPreparationRead:
    """Prepara o pacote (prompt + frame inicial + frame final) de vídeo."""
    try:
        segments, validation_errors = await prepare_continuous_video_package(
            session,
            project_id,
            segment_ids=payload.segment_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContinuousVideoPreparationRead(
        segments=[ContinuousVideoSegmentRead.model_validate(segment) for segment in segments],
        validation_errors=validation_errors,
    )


@router.get("/{project_id}/continuous/segments", response_model=list[ContinuousVideoSegmentRead])
async def get_continuous_video_segments(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContinuousVideoSegmentRead]:
    segments = await list_continuous_video_segments(session, project_id)
    return [ContinuousVideoSegmentRead.model_validate(segment) for segment in segments]


@router.get(
    "/{project_id}/continuous/segments/download",
    include_in_schema=False,
)
async def get_continuous_video_segments_download(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Baixa todos os frames do storyboard em um único ZIP, na ordem dos segmentos.

    Cada arquivo é nomeado com o número e o título do segmento, dentro de uma
    pasta com o nome do projeto (ex.: ``meu-projeto/segmento-01-abertura.webp``).
    """
    import io
    import zipfile

    from app.projects.repository import ProjectRepository
    from app.video_generation.storyboard_export import storyboard_zip_entry_name

    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projeto não encontrado.",
        )
    project_title = str(project.title or "").strip()

    segments = await list_continuous_video_segments(session, project_id)
    selected: list[tuple[int, str]] = []
    for segment in segments:
        asset_id = segment.source_frame_asset_id
        if not asset_id:
            continue
        asset = await session.get(Asset, asset_id)
        if asset is not None and asset.storage_uri:
            selected.append((segment.segment_number, str(asset.storage_uri)))

    if not selected:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum frame gerado para download.",
        )

    # Mapeia número do segmento -> título para nomear os arquivos do ZIP.
    title_by_number = {
        int(segment.segment_number): str(segment.title or "").strip() for segment in segments
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for segment_number, storage_uri in selected:
            path = resolve_storage_path(storage_uri)
            if path is None or not path.is_file():
                continue
            arcname = storyboard_zip_entry_name(
                project_title,
                segment_number,
                title_by_number.get(segment_number, ""),
                path.suffix,
            )
            archive.write(path, arcname=arcname)

    if not buffer.getvalue():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Os arquivos dos frames selecionados não estão disponíveis.",
        )

    from app.video_generation.storyboard_export import storyboard_zip_filename

    zip_filename = storyboard_zip_filename(project_title)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
        },
    )


@router.delete(
    "/{project_id}/continuous/segments",
    # SEC-01.3: endpoint destrutivo em massa exige token mesmo em local.
    dependencies=[Depends(verify_api_token)],
)
async def delete_continuous_video_segments(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, int]:
    """Deleta todos os segmentos, prompts e conteudos de producao de video."""
    count = await delete_all_continuous_video_segments(session, project_id)
    await session.commit()
    return {"deleted": count}


@router.delete(
    "/{project_id}/continuous/segments/{segment_id}",
    # SEC-01.3: endpoint destrutivo exige token mesmo em local.
    dependencies=[Depends(verify_api_token)],
)
async def delete_continuous_video_segment_endpoint(
    project_id: UUID,
    segment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Deleta um único segmento (e seus assets) sem tocar nos demais."""
    deleted = await delete_continuous_video_segment(session, project_id, segment_id)
    await session.commit()
    return {"deleted": deleted}


@router.patch(
    "/{project_id}/continuous/segments/{segment_id}",
    response_model=ContinuousVideoSegmentRead,
)
async def patch_continuous_video_segment_prompt(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoSegmentPromptUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    try:
        segment = await update_continuous_video_segment_prompt(
            session,
            project_id,
            segment_id,
            prompt=payload.prompt,
            title=payload.title,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)




@router.post(
    "/{project_id}/continuous/segments/{segment_id}/done",
    response_model=ContinuousVideoSegmentRead,
)
@router.post(
    "/{project_id}/continuous/segments/{segment_id}/approve",
    response_model=ContinuousVideoSegmentRead,
    include_in_schema=False,
)
async def post_approve_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    """Conclui o segmento: o usuário criou o vídeo manualmente e marcou como feito."""
    try:
        segment = await approve_continuous_video_segment(
            session,
            project_id,
            segment_id,
            note=payload.note,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/reject",
    response_model=ContinuousVideoSegmentRead,
)
async def post_reject_continuous_video_segment(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    try:
        segment = await reject_continuous_video_segment(
            session,
            project_id,
            segment_id,
            note=payload.note,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.post(
    "/{project_id}/continuous/segments/{segment_id}/variants/select",
    response_model=ContinuousVideoSegmentRead,
)
async def post_select_continuous_video_segment_variant(
    project_id: UUID,
    segment_id: UUID,
    payload: ContinuousVideoVariantSelectRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContinuousVideoSegmentRead:
    try:
        segment = await select_continuous_video_segment_variant(
            session, project_id, segment_id, payload.asset_id
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    return ContinuousVideoSegmentRead.model_validate(segment)


@router.get("/{project_id}/clips", response_model=list[VideoClipRead])
async def get_video_clips(
    project_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VideoClipRead]:
    clips = await list_video_clips(session, project_id)
    return [VideoClipRead.model_validate(clip) for clip in clips]


@router.get("/{project_id}/jobs/{job_id}", response_model=GenerationJobRead)
async def get_video_job(
    project_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GenerationJobRead:
    job = await get_job_status(session, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return GenerationJobRead.model_validate(job)
