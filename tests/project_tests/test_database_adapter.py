from dataclasses import dataclass

from agentviz.database import DatabaseAdapter
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
)


@dataclass(frozen=True)
class FakeAdapter:
    name: str = "chinook"
    backend: DatabaseBackend = DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        return DatabaseMetadata(
            name=self.name,
            backend=self.backend,
            tables=[
                TableMetadata(
                    name="invoices",
                    columns=[
                        ColumnMetadata(name="InvoiceId", data_type="INTEGER"),
                        ColumnMetadata(name="Total", data_type="NUMERIC"),
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
        rows = [{"InvoiceId": 1, "Total": 1.98}]
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["InvoiceId", "Total"],
            rows=rows[:max_rows],
            row_count=len(rows[:max_rows]),
            truncated=max_rows < len(rows),
        )


def test_fake_adapter_satisfies_database_adapter_protocol() -> None:
    adapter = FakeAdapter()

    assert isinstance(adapter, DatabaseAdapter)


def test_database_adapter_contract_exposes_schema() -> None:
    adapter: DatabaseAdapter = FakeAdapter()

    schema = adapter.get_schema()

    assert schema.name == "chinook"
    assert schema.backend == DatabaseBackend.SQLITE
    assert schema.tables[0].name == "invoices"


def test_database_adapter_contract_executes_bounded_query() -> None:
    adapter: DatabaseAdapter = FakeAdapter()

    result = adapter.execute_query(
        "SELECT InvoiceId, Total FROM invoices",
        max_rows=1,
        timeout_seconds=1,
    )

    assert result.columns == ["InvoiceId", "Total"]
    assert result.rows == [{"InvoiceId": 1, "Total": 1.98}]
    assert result.truncated is False
