"""Safe SQL execution pipeline."""

from __future__ import annotations

from agentviz.database import DatabaseAdapter
from agentviz.errors import DatabaseExecutionError
from agentviz.models import QueryExecutionResult
from agentviz.sql.validator import SQLValidator, ValidatedSql


class SafeQueryExecutor:
    """Validate SQL before delegating to a read-only database adapter."""

    def __init__(self, validator: SQLValidator | None = None) -> None:
        self._validator = validator or SQLValidator()

    def execute(
        self,
        adapter: DatabaseAdapter,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        self._validate_limits(max_rows=max_rows, timeout_seconds=timeout_seconds)
        validated = self._validator.validate(sql)
        return self.execute_validated(
            adapter,
            validated,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )

    def execute_validated(
        self,
        adapter: DatabaseAdapter,
        validated: ValidatedSql,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        self._validate_limits(max_rows=max_rows, timeout_seconds=timeout_seconds)
        return adapter.execute_query(
            validated.sql,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )

    def _validate_limits(
        self,
        *,
        max_rows: int,
        timeout_seconds: float | None,
    ) -> None:
        if max_rows < 1:
            raise DatabaseExecutionError("max_rows must be at least 1")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise DatabaseExecutionError("timeout_seconds must be greater than 0")
