"""Deterministic authorization policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from agentviz.config import UserAccessConfig
from agentviz.database import DatabaseAdapter
from agentviz.errors import AuthorizationError
from agentviz.models import DatabaseMetadata, UserIdentity


class DatabaseResolver(Protocol):
    """Minimal registry behavior required after authorization."""

    def get(self, database: str) -> DatabaseAdapter:
        """Return an adapter for a logical database name."""


class AclPolicyEngine:
    """Configuration-backed database access policy."""

    def __init__(
        self,
        users: Mapping[str, UserAccessConfig],
        *,
        all_databases: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._users = dict(users)
        self._all_databases = frozenset(all_databases or ())

    def can_access_database(self, user: UserIdentity, database: str) -> bool:
        if self._all_databases and database not in self._all_databases:
            return False

        access = self._users.get(user.username)
        if access is None:
            return bool(self._all_databases)

        if self._all_databases:
            return database not in access.denied_databases

        return False

    def authorize_database(self, user: UserIdentity, database: str) -> None:
        if not self.can_access_database(user, database):
            raise AuthorizationError(
                f"user '{user.username}' is not authorized for database '{database}'"
            )

    def authorized_databases(self, user: UserIdentity) -> tuple[str, ...]:
        access = self._users.get(user.username)
        if not self._all_databases:
            return ()

        denied = set(access.denied_databases) if access is not None else set()
        return tuple(sorted(self._all_databases - denied))


class AuthorizedSchemaService:
    """Fetch schema only after deterministic database authorization."""

    def __init__(self, policy: AclPolicyEngine, registry: DatabaseResolver) -> None:
        self._policy = policy
        self._registry = registry

    def get_schema(self, user: UserIdentity, database: str) -> DatabaseMetadata:
        self._policy.authorize_database(user, database)
        adapter = self._registry.get(database)
        return adapter.get_schema()
