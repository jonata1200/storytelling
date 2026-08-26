from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ProjectStatus
from app.projects.models import Project
from app.search_filters import PROJECT_REVIEW_STATUSES, PROJECT_STAGE_BY_STATUS, search_terms

PROJECT_STATUS_BUCKETS: dict[str, set[str]] = {
    "draft": {"DRAFT"},
    "review": set(PROJECT_REVIEW_STATUSES),
    "done": {"COMPLETED"},
    "blocked": {"FAILED", "ARCHIVED"},
}
PROJECT_STATUS_BUCKETS["active"] = {
    status.value
    for status in ProjectStatus
    if status.value
    not in (
        PROJECT_STATUS_BUCKETS["draft"]
        | PROJECT_STATUS_BUCKETS["review"]
        | PROJECT_STATUS_BUCKETS["done"]
        | PROJECT_STATUS_BUCKETS["blocked"]
    )
}

PROJECT_STAGE_STATUSES: dict[str, set[str]] = {}
for status_name, stage_name in PROJECT_STAGE_BY_STATUS.items():
    PROJECT_STAGE_STATUSES.setdefault(stage_name, set()).add(status_name)


def _project_status_enums(status_names: set[str]) -> list[ProjectStatus]:
    statuses: list[ProjectStatus] = []
    for status_name in sorted(status_names):
        try:
            statuses.append(ProjectStatus(status_name))
        except ValueError:
            continue
    return statuses


async def search_projects(
    session: AsyncSession,
    *,
    query: str | None = None,
    status_filter: str = "all",
    stage_filter: str = "all",
    updated_period: str = "any",
    sort: str = "updated_desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Project], int]:
    statement = select(Project).where(Project.deleted_at.is_(None))
    for term in search_terms(query):
        pattern = f"%{term}%"
        statement = statement.where(
            or_(
                func.lower(Project.title).like(pattern),
                func.lower(func.coalesce(Project.description, "")).like(pattern),
                func.lower(cast(Project.status, String)).like(pattern),
            )
        )
    if status_filter != "all":
        statuses = _project_status_enums(PROJECT_STATUS_BUCKETS.get(status_filter, set()))
        if statuses:
            statement = statement.where(Project.status.in_(statuses))
    if stage_filter != "all":
        statuses = _project_status_enums(PROJECT_STAGE_STATUSES.get(stage_filter, set()))
        if statuses:
            statement = statement.where(Project.status.in_(statuses))
    if updated_period != "any":
        try:
            days = int(updated_period)
        except ValueError:
            days = 0
        if days > 0:
            statement = statement.where(
                Project.updated_at >= datetime.now(UTC) - timedelta(days=days)
            )

    total_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = int(await session.scalar(total_statement) or 0)
    if sort == "created_desc":
        statement = statement.order_by(Project.created_at.desc(), Project.id.desc())
    elif sort == "title_asc":
        statement = statement.order_by(func.lower(Project.title), Project.id)
    else:
        statement = statement.order_by(Project.updated_at.desc(), Project.id.desc())
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    result = await session.execute(statement.offset(safe_offset).limit(safe_limit))
    return list(result.scalars()), total
