"""Database registry for logical database names."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from agentviz.errors import (
    ConfigurationError,
    UnknownDatabaseError,
    UnsupportedDatabaseBackendError,
)
from agentviz.models import DatabaseBackend, DatabaseConfig

from .adapter import DatabaseAdapter
from .sqlite import SQLiteAdapter

type AdapterFactory = Callable[[DatabaseConfig], DatabaseAdapter]

DEFAULT_ADAPTER_FACTORIES: Mapping[DatabaseBackend, AdapterFactory] = {
    DatabaseBackend.SQLITE: SQLiteAdapter.from_config,
}


class DatabaseRegistry:
    """Resolve logical database names to concrete adapters."""

    def __init__(
        self,
        databases: Mapping[str, DatabaseConfig],
        *,
        adapter_factories: Mapping[DatabaseBackend, AdapterFactory] | None = None,
    ) -> None:
        self._databases = dict(databases)
        factories = (
            DEFAULT_ADAPTER_FACTORIES
            if adapter_factories is None
            else adapter_factories
        )
        self._adapter_factories = dict(factories)
        self._adapters: dict[str, DatabaseAdapter] = {}

        for database_name, database in self._databases.items():
            if database.name != database_name:
                raise ConfigurationError(
                    f"database key '{database_name}' must match configured "
                    f"name '{database.name}'"
                )

    def names(self) -> tuple[str, ...]:
        """Return registered logical database names."""

        return tuple(sorted(self._databases))

    def get(self, database_name: str) -> DatabaseAdapter:
        """Return an adapter for a registered logical database."""

        database = self._databases.get(database_name)
        if database is None:
            raise UnknownDatabaseError(f"unknown database: {database_name}")

        adapter = self._adapters.get(database_name)
        if adapter is None:
            adapter = self._create_adapter(database)
            self._adapters[database_name] = adapter

        return adapter

    def _create_adapter(self, database: DatabaseConfig) -> DatabaseAdapter:
        factory = self._adapter_factories.get(database.backend)
        if factory is None:
            raise UnsupportedDatabaseBackendError(
                f"unsupported database backend for '{database.name}': "
                f"{database.backend}"
            )

        return factory(database)
