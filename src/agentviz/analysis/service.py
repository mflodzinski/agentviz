"""Trusted deterministic execution boundary for analysis queries."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from agentviz.auth import AclPolicyEngine
from agentviz.auth.policy import DatabaseResolver
from agentviz.config import QuerySettings
from agentviz.errors import SQLValidationError
from agentviz.models import (
    AnalysisQueryResult,
    DatabaseMetadata,
    QueryProvenance,
    UserIdentity,
)
from agentviz.observability import emit_event
from agentviz.sql import SafeQueryExecutor, SQLValidator


class AnalysisExecutionService:
    """Run authorized, validated, bounded SQL before introducing any LLM."""

    def __init__(
        self,
        *,
        policy: AclPolicyEngine,
        registry: DatabaseResolver,
        query_settings: QuerySettings | None = None,
        validator: SQLValidator | None = None,
        executor: SafeQueryExecutor | None = None,
    ) -> None:
        self._policy = policy
        self._registry = registry
        self._query_settings = query_settings or QuerySettings()
        self._validator = validator or SQLValidator()
        self._executor = executor or SafeQueryExecutor(validator=self._validator)

    def run_query(
        self,
        *,
        user: UserIdentity,
        database: str,
        sql: str,
        run_id: str | None = None,
    ) -> AnalysisQueryResult:
        emit_event(
            "authorization.started",
            run_id=run_id,
            user=user.username,
            database=database,
        )
        try:
            self._policy.authorize_database(user, database)
        except Exception as exc:
            emit_event(
                "authorization.failed",
                run_id=run_id,
                user=user.username,
                database=database,
                error_type=type(exc).__name__,
            )
            raise
        emit_event(
            "authorization.completed",
            run_id=run_id,
            user=user.username,
            database=database,
        )
        emit_event(
            "sql_validation.started",
            run_id=run_id,
            database=database,
            sql_length=len(sql),
        )
        try:
            validated = self._validator.validate(sql)
        except Exception as exc:
            emit_event(
                "sql_validation.failed",
                run_id=run_id,
                database=database,
                error_type=type(exc).__name__,
            )
            raise
        emit_event(
            "sql_validation.completed",
            run_id=run_id,
            database=database,
            referenced_tables=sorted(validated.referenced_tables),
        )
        adapter = self._registry.get(database)
        schema = adapter.get_schema()
        _validate_tables_in_schema(
            referenced_tables=validated.referenced_tables,
            schema=schema,
        )
        query_started = perf_counter()
        try:
            result = self._executor.execute_validated(
                adapter,
                validated,
                max_rows=self._query_settings.max_rows,
                timeout_seconds=self._query_settings.timeout_seconds,
            )
        except Exception as exc:
            query_duration_ms = round((perf_counter() - query_started) * 1000, 3)
            emit_event(
                "query_execution.failed",
                run_id=run_id,
                database=database,
                error_type=type(exc).__name__,
                duration_ms=query_duration_ms,
            )
            raise
        query_duration_ms = round((perf_counter() - query_started) * 1000, 3)
        emit_event(
            "query_execution.completed",
            run_id=run_id,
            database=database,
            row_count=result.row_count,
            truncated=result.truncated,
            max_rows=self._query_settings.max_rows,
            timeout_seconds=self._query_settings.timeout_seconds,
            duration_ms=query_duration_ms,
        )

        return AnalysisQueryResult(
            result=result,
            provenance=QueryProvenance(
                user=user.username,
                database=database,
                executed_sql=result.executed_sql,
                tables_used=validated.referenced_tables,
                row_count=result.row_count,
                truncated=result.truncated,
                executed_at=datetime.now(UTC),
            ),
        )


def _validate_tables_in_schema(
    *,
    referenced_tables: frozenset[str],
    schema: DatabaseMetadata,
) -> None:
    available_tables = {table.name for table in schema.tables}
    unknown_tables = referenced_tables - available_tables
    if unknown_tables:
        names = ", ".join(sorted(unknown_tables))
        raise SQLValidationError(
            f"SQL references table(s) outside authorized schema: {names}"
        )
