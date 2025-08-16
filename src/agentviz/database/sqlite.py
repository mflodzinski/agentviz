"""SQLite database adapter."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from agentviz.errors import (
    DatabaseConnectionError,
    DatabaseExecutionError,
    DatabaseSchemaError,
    QueryTimeoutError,
)
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    ForeignKeyMetadata,
    QueryExecutionResult,
    TableMetadata,
)


class SQLiteAdapter:
    """Read-only SQLite implementation of the database adapter contract."""

    def __init__(self, name: str, path: Path) -> None:
        self._name = name
        self._path = Path(path)
        self._engine: Engine | None = None

    @classmethod
    def from_config(cls, config: DatabaseConfig) -> SQLiteAdapter:
        if config.backend != DatabaseBackend.SQLITE:
            raise DatabaseConnectionError(
                f"SQLiteAdapter cannot open backend '{config.backend}'"
            )

        return cls(name=config.name, path=config.path)

    @property
    def name(self) -> str:
        return self._name

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        try:
            engine = self._get_engine()
            inspector = inspect(engine)
            table_names = inspector.get_table_names()
            view_names = inspector.get_view_names()
            relation_names = sorted({*table_names, *view_names})

            tables = [
                self._inspect_relation(engine, inspector, relation_name)
                for relation_name in relation_names
            ]

            return DatabaseMetadata(
                name=self.name,
                backend=self.backend,
                tables=tables,
            )
        except DatabaseConnectionError:
            raise
        except SQLAlchemyError as exc:
            raise DatabaseSchemaError(
                f"failed to inspect SQLite schema for '{self.name}': {exc}"
            ) from exc

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        if max_rows < 1:
            raise DatabaseExecutionError("max_rows must be at least 1")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise DatabaseExecutionError("timeout_seconds must be greater than 0")

        try:
            with self._get_engine().connect() as connection:
                with _sqlite_timeout(connection, timeout_seconds):
                    result = connection.execute(text(sql))
                    if not result.returns_rows:
                        raise DatabaseExecutionError("query did not return rows")

                    columns = list(result.keys())
                    fetched_rows = result.fetchmany(max_rows + 1)
                    returned_rows = fetched_rows[:max_rows]
                    rows = [
                        {
                            key: _normalize_sqlite_value(value)
                            for key, value in row._mapping.items()
                        }
                        for row in returned_rows
                    ]

                return QueryExecutionResult(
                    executed_sql=sql,
                    columns=columns,
                    rows=rows,
                    row_count=len(rows),
                    truncated=len(fetched_rows) > max_rows,
                )
        except DatabaseConnectionError:
            raise
        except DatabaseExecutionError:
            raise
        except SQLAlchemyError as exc:
            if _is_sqlite_interrupted(exc):
                raise QueryTimeoutError(
                    f"SQLite query for '{self.name}' exceeded "
                    f"{timeout_seconds} second(s)"
                ) from exc
            raise DatabaseExecutionError(
                f"failed to execute SQLite query for '{self.name}': {exc}"
            ) from exc

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    def _create_engine(self) -> Engine:
        if not self._path.exists():
            raise DatabaseConnectionError(f"SQLite database not found: {self._path}")

        database_uri = f"file:{self._path.resolve().as_posix()}?mode=ro"

        def connect_read_only() -> sqlite3.Connection:
            return sqlite3.connect(database_uri, uri=True)

        engine = create_engine("sqlite://", creator=connect_read_only)

        @event.listens_for(engine, "connect")
        def set_query_only(
            dbapi_connection: sqlite3.Connection,
            _connection_record: object,
        ) -> None:
            dbapi_connection.execute("PRAGMA query_only = ON")

        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise DatabaseConnectionError(
                f"failed to open SQLite database '{self._path}': {exc}"
            ) from exc

        return engine

    def _inspect_relation(
        self,
        engine: Engine,
        inspector: Any,
        relation_name: str,
    ) -> TableMetadata:
        primary_key_columns = set(
            inspector.get_pk_constraint(relation_name).get("constrained_columns", [])
        )
        columns = [
            ColumnMetadata(
                name=column["name"],
                data_type=str(column["type"]),
                nullable=column.get("nullable", True),
                primary_key=column["name"] in primary_key_columns,
            )
            for column in inspector.get_columns(relation_name)
        ]

        foreign_keys = []
        for foreign_key in inspector.get_foreign_keys(relation_name):
            constrained_columns = foreign_key.get("constrained_columns", [])
            referred_columns = foreign_key.get("referred_columns", [])
            referred_table = foreign_key.get("referred_table")
            if not referred_table:
                continue

            foreign_keys.extend(
                ForeignKeyMetadata(
                    column=column,
                    referenced_table=referred_table,
                    referenced_column=referenced_column,
                )
                for column, referenced_column in zip(
                    constrained_columns,
                    referred_columns,
                    strict=False,
                )
            )

        return TableMetadata(
            name=relation_name,
            columns=columns,
            foreign_keys=foreign_keys,
            row_count=self._count_rows(engine, relation_name),
        )

    def _count_rows(self, engine: Engine, relation_name: str) -> int | None:
        try:
            with engine.connect() as connection:
                count = connection.execute(
                    text(f"SELECT COUNT(*) FROM {_quote_identifier(relation_name)}")
                ).scalar_one()
                return int(count)
        except SQLAlchemyError:
            return None


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_sqlite_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bytes):
        return f"<BLOB {len(value)} bytes>"
    return value


@contextmanager
def _sqlite_timeout(
    connection: Connection,
    timeout_seconds: float | None,
) -> Iterator[None]:
    if timeout_seconds is None:
        yield
        return

    raw_connection = connection.connection.driver_connection
    if not isinstance(raw_connection, sqlite3.Connection):
        yield
        return

    deadline = monotonic() + timeout_seconds

    def interrupt_when_expired() -> int:
        return int(monotonic() >= deadline)

    raw_connection.set_progress_handler(interrupt_when_expired, 1000)
    try:
        yield
    finally:
        raw_connection.set_progress_handler(None, 0)


def _is_sqlite_interrupted(exc: SQLAlchemyError) -> bool:
    return "interrupted" in str(exc).lower()
