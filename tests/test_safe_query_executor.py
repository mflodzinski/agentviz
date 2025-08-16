import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agentviz.database import DatabaseAdapter, SQLiteAdapter
from agentviz.errors import (
    DatabaseExecutionError,
    QueryTimeoutError,
    SQLValidationError,
)
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
)
from agentviz.sql import SafeQueryExecutor


@dataclass
class RecordingAdapter:
    executed: list[tuple[str, int]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "recording"

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        return DatabaseMetadata(
            name=self.name,
            backend=self.backend,
            tables=[
                TableMetadata(
                    name="invoices",
                    columns=[ColumnMetadata(name="InvoiceId", data_type="INTEGER")],
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
        self.executed.append((sql, max_rows))
        rows = [{"InvoiceId": 1}]
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["InvoiceId"],
            rows=rows[:max_rows],
            row_count=len(rows[:max_rows]),
            truncated=False,
        )


def test_safe_query_executor_validates_before_execution() -> None:
    adapter = RecordingAdapter()
    executor = SafeQueryExecutor()

    result = executor.execute(
        adapter,
        "  SELECT InvoiceId FROM invoices  ",
        max_rows=10,
        timeout_seconds=5,
    )

    assert result.rows == [{"InvoiceId": 1}]
    assert adapter.executed == [("SELECT InvoiceId FROM invoices", 10)]


def test_safe_query_executor_does_not_execute_invalid_sql() -> None:
    adapter = RecordingAdapter()
    executor = SafeQueryExecutor()

    with pytest.raises(SQLValidationError):
        executor.execute(
            adapter,
            "DROP TABLE invoices",
            max_rows=10,
        )

    assert adapter.executed == []


def test_safe_query_executor_rejects_invalid_row_limit_before_execution() -> None:
    adapter = RecordingAdapter()
    executor = SafeQueryExecutor()

    with pytest.raises(DatabaseExecutionError, match="max_rows"):
        executor.execute(
            adapter,
            "SELECT InvoiceId FROM invoices",
            max_rows=0,
        )

    assert adapter.executed == []


def test_safe_query_executor_rejects_invalid_timeout_before_execution() -> None:
    adapter = RecordingAdapter()
    executor = SafeQueryExecutor()

    with pytest.raises(DatabaseExecutionError, match="timeout_seconds"):
        executor.execute(
            adapter,
            "SELECT InvoiceId FROM invoices",
            max_rows=1,
            timeout_seconds=0,
        )

    assert adapter.executed == []


def test_recording_adapter_satisfies_database_adapter_protocol() -> None:
    assert isinstance(RecordingAdapter(), DatabaseAdapter)


def test_safe_query_executor_runs_against_read_only_sqlite_adapter(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sample.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total NUMERIC NOT NULL
        );
        INSERT INTO invoices (InvoiceId, Total)
        VALUES (1, 1.98), (2, 3.96);
        """
    )
    connection.close()

    adapter = SQLiteAdapter(name="sample", path=database_path)
    executor = SafeQueryExecutor()

    result = executor.execute(
        adapter,
        "SELECT InvoiceId, Total FROM invoices ORDER BY InvoiceId",
        max_rows=1,
        timeout_seconds=5,
    )

    assert result.rows == [{"InvoiceId": 1, "Total": 1.98}]
    assert result.truncated is True


def test_safe_query_executor_times_out_long_running_sqlite_query(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sample.db"
    sqlite3.connect(database_path).close()
    adapter = SQLiteAdapter(name="sample", path=database_path)
    executor = SafeQueryExecutor()

    with pytest.raises(QueryTimeoutError):
        executor.execute(
            adapter,
            """
            WITH RECURSIVE counter(value) AS (
                SELECT 1
                UNION ALL
                SELECT value + 1 FROM counter WHERE value < 100000000
            )
            SELECT max(value) FROM counter
            """,
            max_rows=1,
            timeout_seconds=0.001,
        )
