import unicodedata
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

type FieldGetter[T] = str | Callable[[T], object]

PROJECT_STATUS_FILTER_OPTIONS = {
    "all": "Todos",
    "draft": "Rascunho",
    "active": "Em andamento",
    "review": "Revisao",
    "done": "Concluido",
    "blocked": "Falha/arquivado",
}

PROJECT_STAGE_FILTER_OPTIONS = {
    "all": "Todas",
    "script": "Roteiro",
    "scenes": "Cenas",
    "visual": "Visual",
    "storyboard": "Storyboard",
    "video": "Video",
    "finalization": "Finalizacao",
    "quality": "QA",
}

PROJECT_UPDATED_FILTER_OPTIONS = {
    "any": "Qualquer periodo",
    "7": "Ultimos 7 dias",
    "30": "Ultimos 30 dias",
}

PROJECT_SORT_OPTIONS = {
    "updated_desc": "Atualizados recentemente",
    "created_desc": "Mais recentes",
    "title_asc": "Nome A-Z",
}

IDEA_COMPLEXITY_FILTER_OPTIONS = {
    "all": "Todas",
    "low": "Baixa",
    "medium": "Media",
    "high": "Alta",
}

IDEA_SORT_OPTIONS = {
    "created_desc": "Mais recentes",
    "retention_desc": "Melhor retencao",
    "cliche_asc": "Menor risco de cliche",
    "complexity_asc": "Menor complexidade",
    "title_asc": "Nome A-Z",
}

PROJECT_SEARCH_FIELDS: tuple[FieldGetter[object], ...] = (
    "title",
    "description",
    lambda project: _status_value(field_value(project, "status")),
)

IDEA_SEARCH_FIELDS: tuple[FieldGetter[dict[str, object]], ...] = (
    "title",
    "theme",
    "hook",
    "premise",
    "protagonist",
)

PROJECT_REVIEW_STATUSES = {
    "IDEA_APPROVAL",
    "STORY_APPROVAL",
    "SCRIPT_APPROVAL",
    "VISUAL_BIBLE_APPROVAL",
    "STORYBOARD_APPROVAL",
    "VIDEO_REVIEW",
    "FINAL_APPROVAL",
}

PROJECT_STAGE_BY_STATUS = {
    "DRAFT": "script",
    "IDEA_GENERATION": "script",
    "IDEA_APPROVAL": "script",
    "STORY_DESIGN": "scenes",
    "STORY_APPROVAL": "scenes",
    "SCRIPT_GENERATION": "script",
    "SCRIPT_APPROVAL": "script",
    "VISUAL_BIBLE_GENERATION": "visual",
    "VISUAL_BIBLE_APPROVAL": "visual",
    "STORYBOARD_GENERATION": "storyboard",
    "STORYBOARD_APPROVAL": "storyboard",
    "PRODUCTION_PLANNING": "video",
    "VIDEO_GENERATION": "video",
    "VIDEO_REVIEW": "video",
    "AUDIO_GENERATION": "finalization",
    "ASSEMBLY": "finalization",
    "QUALITY_CONTROL": "quality",
    "FINAL_APPROVAL": "finalization",
    "COMPLETED": "finalization",
    "FAILED": "quality",
    "ARCHIVED": "finalization",
}


def normalize_search_text(value: object) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def search_terms(query: object) -> list[str]:
    return [term for term in normalize_search_text(query).split(" ") if term]


def read_field(item: object, field_path: str) -> object:
    current: object = item
    for part in field_path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def field_value[T](item: T, getter: FieldGetter[T]) -> object:
    if isinstance(getter, str):
        return read_field(item, getter)
    return getter(item)


def searchable_text[T](item: T, fields: Sequence[FieldGetter[T]]) -> str:
    return " ".join(
        normalized
        for field in fields
        if (normalized := normalize_search_text(field_value(item, field)))
    )


def item_matches_query[T](item: T, query: object, fields: Sequence[FieldGetter[T]]) -> bool:
    terms = search_terms(query)
    if not terms:
        return True
    haystack = searchable_text(item, fields)
    return all(term in haystack for term in terms)


def filter_by_query[T](
    items: Iterable[T],
    query: object,
    fields: Sequence[FieldGetter[T]],
) -> list[T]:
    return [item for item in items if item_matches_query(item, query, fields)]


def safe_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def sort_by_datetime[T](
    items: Iterable[T],
    getter: FieldGetter[T],
    *,
    descending: bool = True,
) -> list[T]:
    def key(pair: tuple[int, T]) -> tuple[bool, float, int]:
        index, item = pair
        parsed = safe_datetime(field_value(item, getter))
        if parsed is None:
            return (True, 0.0, index)
        timestamp = parsed.timestamp()
        return (False, -timestamp if descending else timestamp, index)

    return [item for _index, item in sorted(enumerate(items), key=key)]


def sort_by_text[T](
    items: Iterable[T],
    getter: FieldGetter[T],
    *,
    descending: bool = False,
) -> list[T]:
    def key(pair: tuple[int, T]) -> tuple[str, int]:
        index, item = pair
        value = normalize_search_text(field_value(item, getter))
        return (value, index)

    present: list[tuple[int, T]] = []
    missing: list[tuple[int, T]] = []
    for pair in enumerate(items):
        if normalize_search_text(field_value(pair[1], getter)):
            present.append(pair)
        else:
            missing.append(pair)
    return [
        item
        for _index, item in [*sorted(present, key=key, reverse=descending), *missing]
    ]


def sort_by_number[T](
    items: Iterable[T],
    getter: FieldGetter[T],
    *,
    descending: bool = False,
) -> list[T]:
    def key(pair: tuple[int, T]) -> tuple[bool, float, int]:
        index, item = pair
        raw_value = field_value(item, getter)
        try:
            value = None if raw_value is None or raw_value == "" else float(str(raw_value))
        except (TypeError, ValueError):
            value = None
        if value is None:
            return (True, 0.0, index)
        return (False, -value if descending else value, index)

    return [item for _index, item in sorted(enumerate(items), key=key)]


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def project_status_bucket(project: object) -> str:
    status = _status_value(field_value(project, "status"))
    if status == "DRAFT":
        return "draft"
    if status in PROJECT_REVIEW_STATUSES:
        return "review"
    if status in {"COMPLETED"}:
        return "done"
    if status in {"FAILED", "ARCHIVED"}:
        return "blocked"
    return "active"


def project_stage(project: object) -> str:
    return PROJECT_STAGE_BY_STATUS.get(_status_value(field_value(project, "status")), "script")


def project_matches_updated_period(
    project: object,
    updated_period: str,
    now: datetime | None = None,
) -> bool:
    if updated_period == "any":
        return True
    try:
        days = int(updated_period)
    except ValueError:
        return True
    updated_at = safe_datetime(field_value(project, "updated_at"))
    if updated_at is None:
        return False
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return (reference.astimezone(UTC) - updated_at).days <= days


def filter_projects(
    projects: Iterable[object],
    *,
    query: object = "",
    status_filter: str = "all",
    stage_filter: str = "all",
    updated_period: str = "any",
    sort: str = "updated_desc",
    now: datetime | None = None,
) -> list[object]:
    filtered = filter_by_query(projects, query, PROJECT_SEARCH_FIELDS)
    if status_filter != "all":
        filtered = [
            project for project in filtered if project_status_bucket(project) == status_filter
        ]
    if stage_filter != "all":
        filtered = [project for project in filtered if project_stage(project) == stage_filter]
    filtered = [
        project
        for project in filtered
        if project_matches_updated_period(project, updated_period, now)
    ]
    if sort == "created_desc":
        return sort_by_datetime(filtered, "created_at", descending=True)
    if sort == "title_asc":
        return sort_by_text(filtered, "title")
    return sort_by_datetime(filtered, "updated_at", descending=True)


def idea_complexity_bucket(idea: dict[str, object]) -> str:
    value = _safe_decimal(idea.get("production_complexity"))
    if value is None:
        return "medium"
    if value <= Decimal("3"):
        return "low"
    if value >= Decimal("8"):
        return "high"
    return "medium"


def _safe_decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _duration_filter_matches(idea: dict[str, object], duration_filter: object) -> bool:
    if duration_filter in {None, "", "all"}:
        return True
    idea_duration = _safe_decimal(idea.get("duration_minutes"))
    selected_duration = _safe_decimal(duration_filter)
    if idea_duration is None or selected_duration is None:
        return False
    return idea_duration == selected_duration


def unique_idea_filter_options(ideas: Iterable[dict[str, object]], key: str) -> list[str]:
    values = {
        str(value).strip()
        for idea in ideas
        if (value := idea.get(key)) not in {None, ""}
    }
    return sorted(values, key=normalize_search_text)


def unique_idea_duration_options(ideas: Iterable[dict[str, object]]) -> list[float]:
    values: set[Decimal] = set()
    for idea in ideas:
        value = _safe_decimal(idea.get("duration_minutes"))
        if value is not None:
            values.add(value)
    return [float(value) for value in sorted(values)]


def filter_ideas(
    ideas: Iterable[dict[str, object]],
    *,
    query: object = "",
    genre_filter: str = "all",
    emotion_filter: str = "all",
    duration_filter: object = "all",
    complexity_filter: str = "all",
    sort: str = "created_desc",
) -> list[dict[str, object]]:
    filtered = filter_by_query(ideas, query, IDEA_SEARCH_FIELDS)
    if genre_filter != "all":
        filtered = [
            idea
            for idea in filtered
            if normalize_search_text(idea.get("genre")) == normalize_search_text(genre_filter)
        ]
    if emotion_filter != "all":
        filtered = [
            idea
            for idea in filtered
            if normalize_search_text(idea.get("primary_emotion"))
            == normalize_search_text(emotion_filter)
        ]
    if duration_filter not in {None, "", "all"}:
        filtered = [idea for idea in filtered if _duration_filter_matches(idea, duration_filter)]
    if complexity_filter != "all":
        filtered = [
            idea for idea in filtered if idea_complexity_bucket(idea) == complexity_filter
        ]
    if sort == "retention_desc":
        return sort_by_number(filtered, "retention_potential", descending=True)
    if sort == "cliche_asc":
        return sort_by_number(filtered, "cliche_risk")
    if sort == "complexity_asc":
        return sort_by_number(filtered, "production_complexity")
    if sort == "title_asc":
        return sort_by_text(filtered, "title")
    return sort_by_datetime(filtered, "created_at", descending=True)


def has_project_filters(
    query: object,
    status_filter: str,
    stage_filter: str,
    updated_period: str,
    sort: str,
) -> bool:
    return bool(search_terms(query)) or any(
        [
            status_filter != "all",
            stage_filter != "all",
            updated_period != "any",
            sort != "updated_desc",
        ]
    )


def has_idea_filters(
    query: object,
    genre_filter: str,
    emotion_filter: str,
    duration_filter: object,
    complexity_filter: str,
    sort: str,
) -> bool:
    return bool(search_terms(query)) or any(
        [
            genre_filter != "all",
            emotion_filter != "all",
            duration_filter not in {None, "", "all"},
            complexity_filter != "all",
            sort != "created_desc",
        ]
    )


def project_active_filter_labels(
    query: object,
    status_filter: str,
    stage_filter: str,
    updated_period: str,
    sort: str,
) -> list[str]:
    labels: list[str] = []
    if search_terms(query):
        labels.append("Busca")
    if status_filter != "all":
        labels.append(PROJECT_STATUS_FILTER_OPTIONS.get(status_filter, status_filter))
    if stage_filter != "all":
        labels.append(PROJECT_STAGE_FILTER_OPTIONS.get(stage_filter, stage_filter))
    if updated_period != "any":
        labels.append(PROJECT_UPDATED_FILTER_OPTIONS.get(updated_period, updated_period))
    if sort != "updated_desc":
        labels.append(PROJECT_SORT_OPTIONS.get(sort, sort))
    return labels


def idea_active_filter_labels(
    query: object,
    genre_filter: str,
    emotion_filter: str,
    duration_filter: object,
    complexity_filter: str,
    sort: str,
) -> list[str]:
    labels: list[str] = []
    if search_terms(query):
        labels.append("Busca")
    if genre_filter != "all":
        labels.append(str(genre_filter))
    if emotion_filter != "all":
        labels.append(str(emotion_filter))
    if duration_filter not in {None, "", "all"}:
        labels.append(f"{duration_filter} min")
    if complexity_filter != "all":
        labels.append(IDEA_COMPLEXITY_FILTER_OPTIONS.get(complexity_filter, complexity_filter))
    if sort != "created_desc":
        labels.append(IDEA_SORT_OPTIONS.get(sort, sort))
    return labels
