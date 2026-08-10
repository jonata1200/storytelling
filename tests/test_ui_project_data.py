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


def test_dashboard_metrics_statement_has_five_unioned_selects() -> None:
    sql = str(dashboard_metrics_statement().compile(dialect=postgresql.dialect()))
    assert sql.lower().count("union all") == 4  # 5 selects -> 4 unions


def test_project_counts_statement_compiles_on_supported_dialects() -> None:
    statement = project_counts_statement(uuid4())
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect))
        assert "union all" in sql.lower()


def test_project_counts_statement_has_sixteen_unioned_selects() -> None:
    sql = str(project_counts_statement(uuid4()).compile(dialect=postgresql.dialect()))
    assert sql.lower().count("union all") == 15  # 16 selects -> 15 unions
