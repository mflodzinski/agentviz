from dataclasses import dataclass
from pathlib import Path

import pytest

from agentviz.database import DatabaseAdapter, DatabaseRegistry, SQLiteAdapter
from agentviz.errors import (
    ConfigurationError,
    UnknownDatabaseError,
    UnsupportedDatabaseBackendError,
)
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
)


@dataclass(frozen=True)
class FakeAdapter:
    name: str
    backend: DatabaseBackend = DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        return DatabaseMetadata(
            name=self.name,
            backend=self.backend,
            tables=[
                TableMetadata(
                    name="example",
                    columns=[ColumnMetadata(name="id", data_type="INTEGER")],
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
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["id"],
            rows=[{"id": 1}][:max_rows],
            row_count=1 if max_rows else 0,
        )


def database_config(name: str) -> DatabaseConfig:
    return DatabaseConfig(
        name=name,
        backend=DatabaseBackend.SQLITE,
        path=Path(f"data/{name}.db"),
    )


def test_registry_resolves_known_database_to_sqlite_adapter() -> None:
    registry = DatabaseRegistry({"chinook": database_config("chinook")})

    adapter = registry.get("chinook")

    assert isinstance(adapter, SQLiteAdapter)
    assert adapter.name == "chinook"


def test_registry_lists_registered_database_names() -> None:
    registry = DatabaseRegistry(
        {
            "sakila": database_config("sakila"),
            "chinook": database_config("chinook"),
        }
    )

    assert registry.names() == ("chinook", "sakila")


def test_registry_rejects_unknown_database() -> None:
    registry = DatabaseRegistry({"chinook": database_config("chinook")})

    with pytest.raises(UnknownDatabaseError, match="unknown database: missing"):
        registry.get("missing")


def test_registry_creates_adapters_through_configured_factory() -> None:
    created: list[str] = []

    def create_fake_adapter(config: DatabaseConfig) -> DatabaseAdapter:
        created.append(config.name)
        return FakeAdapter(name=config.name)

    registry = DatabaseRegistry(
        {"chinook": database_config("chinook")},
        adapter_factories={DatabaseBackend.SQLITE: create_fake_adapter},
    )

    first = registry.get("chinook")
    second = registry.get("chinook")

    assert isinstance(first, FakeAdapter)
    assert first is second
    assert created == ["chinook"]


def test_registry_rejects_database_key_config_name_mismatch() -> None:
    with pytest.raises(ConfigurationError, match="must match configured name"):
        DatabaseRegistry({"logical": database_config("physical")})


def test_registry_rejects_backend_without_factory() -> None:
    registry = DatabaseRegistry(
        {"chinook": database_config("chinook")},
        adapter_factories={},
    )

    with pytest.raises(UnsupportedDatabaseBackendError, match="unsupported"):
        registry.get("chinook")
