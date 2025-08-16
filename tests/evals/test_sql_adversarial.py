from dataclasses import dataclass, field

import pytest

from agentviz.analysis import AnalysisExecutionService
from agentviz.auth import AclPolicyEngine
from agentviz.errors import SQLValidationError
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
    UserIdentity,
)
from agentviz.sql import SQLValidator


@dataclass
class RecordingAdapter:
    executed: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "sales"

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        return DatabaseMetadata(
            name="sales",
            backend=DatabaseBackend.SQLITE,
            tables=[
                TableMetadata(
                    name="sales",
                    columns=[
                        ColumnMetadata(name="category", data_type="TEXT"),
                        ColumnMetadata(name="revenue", data_type="REAL"),
                    ],
                )
            ],
        )

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        self.executed.append(sql)
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["category", "revenue"],
            rows=[{"category": "Software", "revenue": 225.0}],
            row_count=1,
            truncated=False,
        )


class RecordingRegistry:
    def __init__(self, adapter: RecordingAdapter) -> None:
        self.adapter = adapter

    def get(self, database: str) -> RecordingAdapter:
        return self.adapter


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "DELETE FROM sales",
        "ATTACH DATABASE 'private.db' AS private",
        "SELECT * FROM sales; DROP TABLE sales",
        "PRAGMA table_info(sales)",
        "SELECT * FROM pragma_table_info('sales')",
    ],
)
def test_evaluation_sql_adversarial_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(SQLValidationError):
        SQLValidator(dialect="sqlite").validate(sql)


def test_evaluation_sql_adversarial_allows_safe_cte() -> None:
    result = SQLValidator(dialect="sqlite").validate(
        """
        WITH category_totals AS (
            SELECT category, SUM(revenue) AS revenue
            FROM sales
            GROUP BY category
        )
        SELECT category, revenue
        FROM category_totals
        ORDER BY revenue DESC
        """
    )

    assert result.referenced_tables == frozenset({"sales"})


def test_evaluation_sql_adversarial_rejects_nested_unauthorized_table() -> None:
    adapter = RecordingAdapter()
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"sales"}),
        registry=RecordingRegistry(adapter),
    )

    with pytest.raises(SQLValidationError, match="outside authorized schema"):
        service.run_query(
            user=UserIdentity(username="alice"),
            database="sales",
            sql="""
            SELECT category
            FROM (
                SELECT category
                FROM private_sales
            ) AS hidden
            """,
        )

    assert adapter.executed == []
