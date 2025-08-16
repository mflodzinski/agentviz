"""Database adapter interface.

Adapters hide backend-specific connection and reflection details from agents
and orchestration code. They do not make authorization decisions, and future
query execution still has to sit behind deterministic SQL validation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentviz.models import DatabaseBackend, DatabaseMetadata, QueryExecutionResult


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Contract implemented by concrete database backends."""

    @property
    def name(self) -> str:
        """Logical database name from configuration."""

    @property
    def backend(self) -> DatabaseBackend:
        """Backend type, such as SQLite."""

    def get_schema(self) -> DatabaseMetadata:
        """Return discovered database schema metadata."""

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        """Execute already-authorized, already-validated read-only SQL."""
