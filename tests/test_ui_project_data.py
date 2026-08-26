from uuid import uuid4

from sqlalchemy.dialects import postgresql, sqlite

from app.ui.project.data import (
    dashboard_metrics_statement,
    project_counts_statement,
)


def test_dashboard_metrics_statement_compiles_on_supported_dialects() -> None:
    statement = dashboard_metrics_statement()
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect))
        assert "union all" in sql.lower()


def test_dashboard_metrics_statement_has_three_unioned_selects() -> None:
    sql = str(dashboard_metrics_statement().compile(dialect=postgresql.dialect()))
    assert sql.lower().count("union all") == 2  # 3 selects -> 2 unions


def test_project_counts_statement_compiles_on_supported_dialects() -> None:
    statement = project_counts_statement(uuid4())
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect))
        assert "union all" in sql.lower()


def test_project_counts_statement_has_seventeen_unioned_selects() -> None:
    compiled = project_counts_statement(uuid4()).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.lower().count("union all") == 16  # 17 selects -> 16 unions
    assert "continuous_video_segments" in sql
    assert "continuous_video_segments.review_status" in sql
    labels = list(compiled.params.values())
    assert "storyboard_ready_segments" in labels
    assert "storyboard_approved_segments" in labels
    assert "continuous_video_selected_segments" in labels
