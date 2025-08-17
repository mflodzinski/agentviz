import json
import logging
from dataclasses import dataclass, field

import pytest

from agentviz.analysis import AnalysisExecutionService
from agentviz.auth import AclPolicyEngine
from agentviz.config import QuerySettings, UserAccessConfig
from agentviz.database import DatabaseAdapter
from agentviz.errors import AuthorizationError, SQLValidationError
from agentviz.models import (
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryExecutionResult,
    TableMetadata,
    UserIdentity,
)
from agentviz.observability import LOGGER_NAME


@dataclass
class RecordingAdapter:
    executed: list[tuple[str, int, float | None]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "chinook"

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
        self.executed.append((sql, max_rows, timeout_seconds))
        rows = [{"InvoiceId": 1}, {"InvoiceId": 2}]
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["InvoiceId"],
            rows=rows[:max_rows],
            row_count=len(rows[:max_rows]),
            truncated=max_rows < len(rows),
        )


class RecordingRegistry:
    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        self.get_calls: list[str] = []

    def get(self, database: str) -> DatabaseAdapter:
        self.get_calls.append(database)
        return self.adapter


def test_analysis_execution_service_runs_authorized_validated_query() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"chinook"}),
        registry=registry,
        query_settings=QuerySettings(max_rows=1, timeout_seconds=7),
    )

    execution = service.run_query(
        user=UserIdentity(username="alice"),
        database="chinook",
        sql=" SELECT InvoiceId FROM invoices ORDER BY InvoiceId ",
    )

    assert execution.result.rows == [{"InvoiceId": 1}]
    assert execution.result.truncated is True
    assert execution.provenance.user == "alice"
    assert execution.provenance.database == "chinook"
    assert execution.provenance.executed_sql == (
        "SELECT InvoiceId FROM invoices ORDER BY InvoiceId"
    )
    assert execution.provenance.tables_used == frozenset({"invoices"})
    assert execution.provenance.row_count == 1
    assert execution.provenance.truncated is True
    assert registry.get_calls == ["chinook"]
    assert adapter.executed == [
        ("SELECT InvoiceId FROM invoices ORDER BY InvoiceId", 1, 7)
    ]


def test_analysis_execution_service_emits_row_free_structured_logs(caplog) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"chinook"}),
        registry=registry,
    )

    service.run_query(
        user=UserIdentity(username="alice"),
        database="chinook",
        sql="SELECT InvoiceId FROM invoices",
        run_id="20260816_123456_a1b2c3d4",
    )

    payloads = [json.loads(record.message) for record in caplog.records]
    event_names = [payload["event"] for payload in payloads]
    assert event_names == [
        "authorization.started",
        "authorization.completed",
        "sql_validation.started",
        "sql_validation.completed",
        "query_execution.completed",
    ]
    assert all(
        payload["run_id"] == "20260816_123456_a1b2c3d4" for payload in payloads
    )
    validation_event = payloads[3]
    assert validation_event["referenced_tables"] == ["invoices"]
    query_event = payloads[4]
    assert query_event["row_count"] == 2
    assert query_event["truncated"] is False
    serialized_logs = "\n".join(record.message for record in caplog.records)
    assert "SELECT InvoiceId FROM invoices" not in serialized_logs
    assert "InvoiceId" not in serialized_logs


def test_analysis_execution_service_authorizes_before_registry_access() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine(
            {"bob": UserAccessConfig(denied_databases=["sakila"])},
            all_databases={"chinook", "sakila"},
        ),
        registry=registry,
    )

    with pytest.raises(AuthorizationError):
        service.run_query(
            user=UserIdentity(username="bob"),
            database="sakila",
            sql="SELECT InvoiceId FROM invoices",
        )

    assert registry.get_calls == []
    assert adapter.executed == []


def test_analysis_execution_service_validates_before_registry_access() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"chinook"}),
        registry=registry,
    )

    with pytest.raises(SQLValidationError):
        service.run_query(
            user=UserIdentity(username="alice"),
            database="chinook",
            sql="DROP TABLE invoices",
        )

    assert registry.get_calls == []
    assert adapter.executed == []


def test_analysis_execution_service_rejects_tables_outside_schema() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"chinook"}),
        registry=registry,
    )

    with pytest.raises(SQLValidationError, match="outside authorized schema"):
        service.run_query(
            user=UserIdentity(username="alice"),
            database="chinook",
            sql="SELECT InvoiceId FROM private_invoices",
        )

    assert registry.get_calls == ["chinook"]
    assert adapter.executed == []


def test_analysis_query_result_serializes_to_json() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    service = AnalysisExecutionService(
        policy=AclPolicyEngine({}, all_databases={"chinook"}),
        registry=registry,
    )

    execution = service.run_query(
        user=UserIdentity(username="alice"),
        database="chinook",
        sql="SELECT InvoiceId FROM invoices",
    )

    restored = type(execution).model_validate_json(execution.model_dump_json())

    assert restored == execution
