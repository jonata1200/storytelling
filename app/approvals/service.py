from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ApprovalDecision, ArtifactStatus
from app.projects.models import Approval, Artifact, ArtifactVersion


async def record_approval(
    session: AsyncSession,
    artifact: Artifact,
    artifact_version: ArtifactVersion,
    decision: ApprovalDecision,
    notes: str | None = None,
    reviewer_user_id: UUID | None = None,
) -> Approval:
    if artifact_version.artifact_id != artifact.id:
        raise ValueError("Artifact version does not belong to artifact")

    approval = Approval(
        artifact_id=artifact.id,
        artifact_version_id=artifact_version.id,
        reviewer_user_id=reviewer_user_id,
        decision=decision,
        notes=notes,
    )
    session.add(approval)

    if decision == ApprovalDecision.APPROVED:
        artifact.status = ArtifactStatus.APPROVED
        artifact.current_version = artifact_version.version_number
    elif decision == ApprovalDecision.BLOCKED:
        artifact.locked = True
        artifact.status = ArtifactStatus.REJECTED
    elif decision in {ApprovalDecision.REJECTED, ApprovalDecision.CHANGES_REQUESTED}:
        artifact.status = ArtifactStatus.REJECTED

    await session.commit()
    return approval
