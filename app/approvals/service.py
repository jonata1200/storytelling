from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ApprovalDecision, ArtifactStatus
from app.projects.models import Approval, Artifact, ArtifactVersion


async def record_approval(
    session: AsyncSession,
    artifact: Artifact,
    artifact_version: ArtifactVersion,
    decision: ApprovalDecision,
    notes: str | None = None,
) -> Approval:
    """Record an approval decision.

    Does NOT commit — the caller owns the transaction boundary. This allows
    routers/orchestrators to wrap multi-step operations (e.g. approve + generate
    views) in a single atomic transaction.
    """
    if artifact_version.artifact_id != artifact.id:
        raise ValueError("Artifact version does not belong to artifact")

    # Idempotência: não cria um segundo registro para a mesma decisão sobre a
    # mesma versão do artefato.
    existing = await session.scalar(
        select(Approval).where(
            Approval.artifact_id == artifact.id,
            Approval.artifact_version_id == artifact_version.id,
            Approval.decision == decision,
        )
    )
    if existing is not None:
        return existing

    # Não permite regredir a versão corrente: aprovar uma versão antiga
    # sobrescreveria artifact.current_version com um número menor.
    if decision == ApprovalDecision.APPROVED and (
        artifact_version.version_number < artifact.current_version
    ):
        raise ValueError(
            "Não é possível aprovar uma versão anterior à versão corrente do artefato."
        )

    approval = Approval(
        artifact_id=artifact.id,
        artifact_version_id=artifact_version.id,
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

    await session.flush()
    return approval
