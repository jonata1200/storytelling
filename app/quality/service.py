from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ProjectStatus
from app.costs.models import CostEntry
from app.projects.models import Artifact, Project
from app.projects.repository import ProjectRepository
from app.quality.continuity import (
    build_initial_shot_state,
    check_timeline_integrity,
    compare_continuity_states,
    inherit_persistent_details,
)
from app.quality.models import ContinuityIssue, ContinuityState, QualityCheck
from app.quality.security import security_scan_text
from app.storyboards.models import Timeline, TimelineItem
from app.storytelling.models import Briefing, Scene, Script, Shot, StoryBible
from app.video_generation.models import GenerationJob
from app.workflows.state_machine import advance_project_status


async def _latest_story_bible(session: AsyncSession, project_id: UUID) -> StoryBible | None:
    result = await session.execute(
        select(StoryBible)
        .where(StoryBible.project_id == project_id)
        .order_by(StoryBible.created_at.desc())
    )
    return result.scalars().first()


async def _ordered_shots(session: AsyncSession, project_id: UUID) -> list[tuple[Shot, Scene]]:
    result = await session.execute(
        select(Shot, Scene)
        .join(Scene, Shot.scene_id == Scene.id)
        .where(Shot.project_id == project_id)
        .order_by(Scene.scene_number, Shot.shot_number)
    )
    return [(row[0], row[1]) for row in result.all()]


async def _upsert_continuity_state(
    session: AsyncSession,
    project_id: UUID,
    shot: Shot,
    scene: Scene,
    state_payload: dict,
    previous_state_id: UUID | None,
) -> ContinuityState:
    result = await session.execute(
        select(ContinuityState).where(
            ContinuityState.project_id == project_id,
            ContinuityState.source_artifact_id == shot.artifact_id,
        )
    )
    state = result.scalars().first()
    if state is None:
        state = ContinuityState(
            project_id=project_id,
            shot_id=shot.id,
            source_artifact_id=shot.artifact_id,
            previous_state_id=previous_state_id,
            scene_number=scene.scene_number,
            shot_number=shot.shot_number,
            state=state_payload,
        )
        session.add(state)
    else:
        state.previous_state_id = previous_state_id
        state.scene_number = scene.scene_number
        state.shot_number = shot.shot_number
        state.state = state_payload
    await session.flush()
    return state


async def _create_issue_if_new(
    session: AsyncSession,
    project_id: UUID,
    state: ContinuityState | None,
    issue_payload: dict,
) -> ContinuityIssue:
    result = await session.execute(
        select(ContinuityIssue).where(
            ContinuityIssue.project_id == project_id,
            ContinuityIssue.continuity_state_id == (state.id if state else None),
            ContinuityIssue.issue_code == issue_payload["issue_code"],
            ContinuityIssue.message == issue_payload["message"],
        )
    )
    issue = result.scalars().first()
    if issue is not None:
        issue.expected = issue_payload["expected"]
        issue.actual = issue_payload["actual"]
        issue.severity = issue_payload["severity"]
        return issue

    issue = ContinuityIssue(
        project_id=project_id,
        continuity_state_id=state.id if state else None,
        source_artifact_id=state.source_artifact_id if state else None,
        issue_code=issue_payload["issue_code"],
        severity=issue_payload["severity"],
        message=issue_payload["message"],
        expected=issue_payload["expected"],
        actual=issue_payload["actual"],
    )
    session.add(issue)
    await session.flush()
    return issue


async def build_continuity_ledger(
    session: AsyncSession, project_id: UUID
) -> tuple[list[ContinuityState], list[ContinuityIssue]] | None:
    project = await ProjectRepository(session).get_project(project_id)
    story_bible = await _latest_story_bible(session, project_id)
    if project is None or story_bible is None:
        return None

    states: list[ContinuityState] = []
    issues: list[ContinuityIssue] = []
    previous_state_payload: dict | None = None
    previous_state_id: UUID | None = None
    for shot, scene in await _ordered_shots(session, project_id):
        state_payload = build_initial_shot_state(shot, story_bible.payload)
        state_payload = inherit_persistent_details(previous_state_payload, state_payload)
        state = await _upsert_continuity_state(
            session, project_id, shot, scene, state_payload, previous_state_id
        )
        states.append(state)
        for issue_payload in compare_continuity_states(previous_state_payload, state_payload):
            issues.append(await _create_issue_if_new(session, project_id, state, issue_payload))
        previous_state_payload = state_payload
        previous_state_id = state.id

    await session.commit()
    for item in [*states, *issues]:
        await session.refresh(item)
    return states, issues


async def list_open_continuity_issues(
    session: AsyncSession, project_id: UUID
) -> list[ContinuityIssue]:
    result = await session.execute(
        select(ContinuityIssue)
        .where(ContinuityIssue.project_id == project_id, ContinuityIssue.accepted.is_(False))
        .order_by(ContinuityIssue.created_at)
    )
    return list(result.scalars())


async def accept_continuity_issue(
    session: AsyncSession, project_id: UUID, issue_id: UUID, reason: str
) -> ContinuityIssue | None:
    issue = await session.get(ContinuityIssue, issue_id)
    if issue is None or issue.project_id != project_id:
        return None
    issue.accepted = True
    issue.accepted_reason = reason
    await session.commit()
    await session.refresh(issue)
    return issue


async def _timeline_quality_issues(session: AsyncSession, project_id: UUID) -> list[dict]:
    result = await session.execute(
        select(Timeline)
        .where(Timeline.project_id == project_id)
        .order_by(Timeline.created_at.desc())
    )
    timeline = result.scalars().first()
    if timeline is None:
        return []

    item_result = await session.execute(
        select(TimelineItem)
        .where(TimelineItem.timeline_id == timeline.id)
        .order_by(TimelineItem.order_index)
    )
    items = [
        (item.start_ms, item.end_ms, item.layer)
        for item in item_result.scalars()
        if item.layer == "video"
    ]
    return check_timeline_integrity(items)


async def _security_findings(session: AsyncSession, project_id: UUID) -> list[dict]:
    findings: list[dict] = []
    briefing_result = await session.execute(
        select(Briefing).where(Briefing.project_id == project_id)
    )
    for briefing in briefing_result.scalars():
        text = " ".join(
            [
                briefing.theme,
                briefing.audience,
                briefing.genre,
                briefing.primary_emotion,
                briefing.visual_style,
                briefing.content_objective,
                briefing.call_to_action or "",
                " ".join(briefing.constraints),
            ]
        )
        scan = security_scan_text(text)
        if scan["prompt_injection_detected"] or scan["secret_detected"]:
            findings.append({"source": "briefing", "scan": scan})

    script_result = await session.execute(select(Script).where(Script.project_id == project_id))
    for script in script_result.scalars():
        scan = security_scan_text(script.content)
        if scan["prompt_injection_detected"] or scan["secret_detected"]:
            findings.append({"source": "script", "scan": scan})
    return findings


async def run_quality_check(session: AsyncSession, project_id: UUID) -> QualityCheck | None:
    project = await ProjectRepository(session).get_project(project_id)
    if project is None:
        return None

    started_at = datetime.now(UTC)
    continuity = await build_continuity_ledger(session, project_id)
    continuity_issues = continuity[1] if continuity else []
    timeline_issues = await _timeline_quality_issues(session, project_id)
    security_findings = await _security_findings(session, project_id)

    open_issue_count = len([issue for issue in continuity_issues if not issue.accepted])
    penalty = open_issue_count * 12 + len(timeline_issues) * 10 + len(security_findings) * 25
    score = max(0, 100 - penalty)
    status = "PASSED" if score >= 85 else "NEEDS_REVIEW"
    metrics = {
        "continuity_states": len(continuity[0]) if continuity else 0,
        "continuity_issues": open_issue_count,
        "timeline_issues": len(timeline_issues),
        "security_findings": len(security_findings),
        "timeline_issue_details": timeline_issues,
    }
    summary = (
        f"Quality score {score}. "
        f"{open_issue_count} continuity issue(s), "
        f"{len(timeline_issues)} timeline issue(s), "
        f"{len(security_findings)} security finding(s)."
    )
    check = QualityCheck(
        project_id=project_id,
        check_type="phase8_quality_gate",
        status=status,
        score=score,
        summary=summary,
        metrics=metrics,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    session.add(check)
    if project.status in {ProjectStatus.ASSEMBLY, ProjectStatus.FINAL_APPROVAL}:
        advance_project_status(project, ProjectStatus.QUALITY_CONTROL)
    await session.commit()
    await session.refresh(check)
    return check


async def observability_summary(session: AsyncSession, project_id: UUID) -> dict | None:
    project = await session.get(Project, project_id)
    if project is None:
        return None

    jobs_result = await session.execute(
        select(GenerationJob.status, func.count())
        .where(GenerationJob.project_id == project_id)
        .group_by(GenerationJob.status)
    )
    jobs = {str(status): count for status, count in jobs_result.all()}

    quality_count = await session.scalar(
        select(func.count()).select_from(QualityCheck).where(QualityCheck.project_id == project_id)
    )
    issue_count = await session.scalar(
        select(func.count())
        .select_from(ContinuityIssue)
        .where(ContinuityIssue.project_id == project_id, ContinuityIssue.accepted.is_(False))
    )
    stale_count = await session.scalar(
        select(func.count())
        .select_from(Artifact)
        .where(Artifact.project_id == project_id, Artifact.status == ArtifactStatus.STALE)
    )
    score_result = await session.execute(
        select(QualityCheck.score)
        .where(QualityCheck.project_id == project_id)
        .order_by(QualityCheck.created_at.desc())
    )
    latest_score = score_result.scalars().first()
    cost_total = await session.scalar(
        select(func.coalesce(func.sum(CostEntry.total_cost), Decimal("0.000000"))).where(
            CostEntry.project_id == project_id
        )
    )
    return {
        "project_id": project_id,
        "project_status": project.status.value,
        "generation_jobs": jobs,
        "quality_checks": quality_count or 0,
        "open_continuity_issues": issue_count or 0,
        "stale_artifacts": stale_count or 0,
        "latest_quality_score": latest_score,
        "cost_total_usd": str(cost_total or Decimal("0.000000")),
    }
