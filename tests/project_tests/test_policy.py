from dataclasses import dataclass

import pytest

from agentviz.auth import AclPolicyEngine, AuthorizedSchemaService
from agentviz.config import UserAccessConfig
from agentviz.database import DatabaseAdapter
from agentviz.errors import AuthorizationError
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
    UserIdentity,
)


@dataclass
class RecordingAdapter:
    schema_calls: int = 0
    query_calls: int = 0

    @property
    def name(self) -> str:
        return "chinook"

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        self.schema_calls += 1
        return DatabaseMetadata(
            name="chinook",
            backend=DatabaseBackend.SQLITE,
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
        self.query_calls += 1
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["InvoiceId"],
            rows=[{"InvoiceId": 1}][:max_rows],
            row_count=1,
        )


class RecordingRegistry:
    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        self.get_calls: list[str] = []

    def get(self, database: str) -> DatabaseAdapter:
        self.get_calls.append(database)
        return self.adapter


def test_policy_allows_known_database_by_default() -> None:
    policy = AclPolicyEngine(
        {},
        all_databases={"chinook", "sakila"},
    )

    assert policy.can_access_database(UserIdentity(username="alice"), "chinook")


def test_policy_denies_explicitly_denied_database() -> None:
    policy = AclPolicyEngine(
        {"bob": UserAccessConfig(denied_databases=["sakila"])},
        all_databases={"chinook", "sakila"},
    )

    assert not policy.can_access_database(UserIdentity(username="bob"), "sakila")


def test_policy_denies_unknown_database() -> None:
    policy = AclPolicyEngine({}, all_databases={"chinook"})

    assert not policy.can_access_database(UserIdentity(username="carol"), "sakila")


def test_policy_lists_authorized_databases() -> None:
    policy = AclPolicyEngine(
        {"alice": UserAccessConfig(denied_databases=["sakila"])},
        all_databases={"sakila", "chinook", "northwind"},
    )

    assert policy.authorized_databases(UserIdentity(username="alice")) == (
        "chinook",
        "northwind",
    )


def test_authorize_database_raises_clear_error() -> None:
    policy = AclPolicyEngine(
        {"bob": UserAccessConfig(denied_databases=["sakila"])},
        all_databases={"chinook", "sakila"},
    )

    with pytest.raises(AuthorizationError, match="not authorized"):
        policy.authorize_database(UserIdentity(username="bob"), "sakila")


def test_authorized_schema_service_authorizes_before_registry_access() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    policy = AclPolicyEngine(
        {"bob": UserAccessConfig(denied_databases=["sakila"])},
        all_databases={"chinook", "sakila"},
    )
    service = AuthorizedSchemaService(policy=policy, registry=registry)

    with pytest.raises(AuthorizationError):
        service.get_schema(UserIdentity(username="bob"), "sakila")

    assert registry.get_calls == []
    assert adapter.schema_calls == 0
    assert adapter.query_calls == 0


def test_authorized_schema_service_fetches_schema_after_authorization() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    policy = AclPolicyEngine({}, all_databases={"chinook"})
    service = AuthorizedSchemaService(policy=policy, registry=registry)

    schema = service.get_schema(UserIdentity(username="alice"), "chinook")

    assert schema.name == "chinook"
    assert registry.get_calls == ["chinook"]
    assert adapter.schema_calls == 1
