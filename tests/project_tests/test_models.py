from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentviz.models import (
    AnalysisAgentResult,
    AnalysisAgentStatus,
    AnalysisArtifact,
    AnalysisPlan,
    AnalysisPlanKind,
    AnalysisQueryResult,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    ProposedQuery,
    QueryExecutionResult,
    QueryProvenance,
    TableMetadata,
    UserIdentity,
)


def test_user_identity_serializes_and_deserializes() -> None:
    user = UserIdentity(username=" alice ")

    payload = user.model_dump_json()
    restored = UserIdentity.model_validate_json(payload)

    assert restored == UserIdentity(username="alice")


def test_analysis_request_rejects_blank_question() -> None:
    with pytest.raises(ValidationError, match="question"):
        AnalysisRequest(
            user=UserIdentity(username="alice"),
            database="chinook",
            question="   ",
        )


def test_database_config_requires_supported_backend() -> None:
    config = DatabaseConfig(
        name="chinook",
        backend=DatabaseBackend.SQLITE,
        path="data/chinook.db",
    )

    assert config.backend == DatabaseBackend.SQLITE

    with pytest.raises(ValidationError, match="backend"):
        DatabaseConfig(name="warehouse", backend="postgres", path="unused")


def test_database_metadata_rejects_duplicate_table_names() -> None:
    table = TableMetadata(
        name="invoices",
        columns=[ColumnMetadata(name="InvoiceId", data_type="INTEGER")],
    )

    with pytest.raises(ValidationError, match="table names must be unique"):
        DatabaseMetadata(
            name="chinook",
            backend=DatabaseBackend.SQLITE,
            tables=[table, table],
        )


def test_table_metadata_rejects_duplicate_column_names() -> None:
    with pytest.raises(ValidationError, match="column names must be unique"):
        TableMetadata(
            name="invoices",
            columns=[
                ColumnMetadata(name="InvoiceId", data_type="INTEGER"),
                ColumnMetadata(name="InvoiceId", data_type="INTEGER"),
            ],
        )


def test_query_execution_result_validates_rows_against_columns() -> None:
    result = QueryExecutionResult(
        executed_sql="SELECT BillingCountry, Total FROM invoices",
        columns=["BillingCountry", "Total"],
        rows=[{"BillingCountry": "Germany", "Total": 1.98}],
        row_count=1,
    )

    restored = QueryExecutionResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_query_execution_result_rejects_mismatched_rows() -> None:
    with pytest.raises(ValidationError, match="row 0 keys"):
        QueryExecutionResult(
            executed_sql="SELECT BillingCountry, Total FROM invoices",
            columns=["BillingCountry", "Total"],
            rows=[{"BillingCountry": "Germany"}],
            row_count=1,
        )


def test_query_execution_result_rejects_wrong_row_count() -> None:
    with pytest.raises(ValidationError, match="row_count"):
        QueryExecutionResult(
            executed_sql="SELECT BillingCountry FROM invoices",
            columns=["BillingCountry"],
            rows=[{"BillingCountry": "Germany"}],
            row_count=2,
        )


def test_analysis_artifact_builds_from_query_result() -> None:
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show invoice totals.",
    )
    execution_result = QueryExecutionResult(
        executed_sql="SELECT InvoiceId, Total FROM invoices",
        columns=["InvoiceId", "Total"],
        rows=[{"InvoiceId": 1, "Total": 1.98}],
        row_count=1,
        truncated=False,
    )
    provenance = QueryProvenance(
        user="alice",
        database="chinook",
        executed_sql="SELECT InvoiceId, Total FROM invoices",
        tables_used=frozenset({"invoices"}),
        row_count=1,
        truncated=False,
        executed_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    artifact = AnalysisArtifact.from_query_result(
        request=request,
        query_result=AnalysisQueryResult(
            result=execution_result,
            provenance=provenance,
        ),
        summary="Returned one invoice total.",
    )

    assert artifact.request == request
    assert artifact.database == "chinook"
    assert artifact.sql == "SELECT InvoiceId, Total FROM invoices"
    assert artifact.columns == ["InvoiceId", "Total"]
    assert artifact.rows == [{"InvoiceId": 1, "Total": 1.98}]
    assert artifact.row_count == 1
    assert artifact.summary == "Returned one invoice total."
    assert artifact.provenance == provenance


def test_analysis_artifact_serializes_to_json() -> None:
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show invoice totals.",
    )
    provenance = QueryProvenance(
        user="alice",
        database="chinook",
        executed_sql="SELECT InvoiceId FROM invoices",
        tables_used=frozenset({"invoices"}),
        row_count=1,
        truncated=False,
        executed_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    artifact = AnalysisArtifact(
        request=request,
        database="chinook",
        sql="SELECT InvoiceId FROM invoices",
        columns=["InvoiceId"],
        rows=[{"InvoiceId": 1}],
        row_count=1,
        truncated=False,
        summary="Returned one invoice.",
        provenance=provenance,
    )

    restored = AnalysisArtifact.model_validate_json(artifact.model_dump_json())

    assert restored == artifact


def test_analysis_artifact_rejects_mismatched_provenance() -> None:
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show invoice totals.",
    )
    provenance = QueryProvenance(
        user="alice",
        database="sakila",
        executed_sql="SELECT InvoiceId FROM invoices",
        tables_used=frozenset({"invoices"}),
        row_count=1,
        truncated=False,
        executed_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    with pytest.raises(ValidationError, match="database"):
        AnalysisArtifact(
            request=request,
            database="chinook",
            sql="SELECT InvoiceId FROM invoices",
            columns=["InvoiceId"],
            rows=[{"InvoiceId": 1}],
            row_count=1,
            truncated=False,
            summary="Returned one invoice.",
            provenance=provenance,
        )


def test_proposed_query_serializes_and_deserializes() -> None:
    proposal = ProposedQuery(
        sql=" SELECT InvoiceId FROM invoices ",
        reasoning_summary="Invoices contains the requested identifier.",
    )

    restored = ProposedQuery.model_validate_json(proposal.model_dump_json())

    assert restored == ProposedQuery(
        sql="SELECT InvoiceId FROM invoices",
        reasoning_summary="Invoices contains the requested identifier.",
    )


def test_proposed_query_rejects_blank_sql() -> None:
    with pytest.raises(ValidationError, match="sql"):
        ProposedQuery(sql="   ")


def test_analysis_plan_accepts_query_plan() -> None:
    plan = AnalysisPlan.query_plan(
        ProposedQuery(sql="SELECT InvoiceId FROM invoices")
    )

    assert plan.kind == AnalysisPlanKind.QUERY
    assert plan.query == ProposedQuery(sql="SELECT InvoiceId FROM invoices")
    assert plan.message is None


def test_analysis_plan_accepts_clarification() -> None:
    plan = AnalysisPlan.clarification("Which performance metric?")

    assert plan.kind == AnalysisPlanKind.CLARIFICATION
    assert plan.query is None
    assert plan.message == "Which performance metric?"


def test_analysis_plan_rejects_inconsistent_payload() -> None:
    with pytest.raises(ValidationError, match="query plans require"):
        AnalysisPlan(kind=AnalysisPlanKind.QUERY)

    with pytest.raises(ValidationError, match="non-query plans require"):
        AnalysisPlan(kind=AnalysisPlanKind.UNSUPPORTED)

    with pytest.raises(ValidationError, match="non-query plans must not"):
        AnalysisPlan(
            kind=AnalysisPlanKind.CLARIFICATION,
            query=ProposedQuery(sql="SELECT InvoiceId FROM invoices"),
            message="Which metric?",
        )


def test_analysis_agent_result_accepts_completed_artifact() -> None:
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show invoice totals.",
    )
    provenance = QueryProvenance(
        user="alice",
        database="chinook",
        executed_sql="SELECT InvoiceId FROM invoices",
        tables_used=frozenset({"invoices"}),
        row_count=1,
        truncated=False,
        executed_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    artifact = AnalysisArtifact(
        request=request,
        database="chinook",
        sql="SELECT InvoiceId FROM invoices",
        columns=["InvoiceId"],
        rows=[{"InvoiceId": 1}],
        row_count=1,
        truncated=False,
        summary="Returned one invoice.",
        provenance=provenance,
    )

    result = AnalysisAgentResult.completed(artifact)

    assert result.status == AnalysisAgentStatus.COMPLETED
    assert result.artifact == artifact
    assert result.message is None


def test_analysis_agent_result_accepts_non_query_outcomes() -> None:
    clarification = AnalysisAgentResult.needs_clarification("Which metric?")
    unsupported = AnalysisAgentResult.unsupported("No forecast data is available.")

    assert clarification.status == AnalysisAgentStatus.NEEDS_CLARIFICATION
    assert clarification.message == "Which metric?"
    assert clarification.artifact is None
    assert unsupported.status == AnalysisAgentStatus.UNSUPPORTED
    assert unsupported.message == "No forecast data is available."
    assert unsupported.artifact is None


def test_analysis_agent_result_rejects_inconsistent_payload() -> None:
    with pytest.raises(ValidationError, match="completed analysis results require"):
        AnalysisAgentResult(status=AnalysisAgentStatus.COMPLETED)

    with pytest.raises(ValidationError, match="non-completed analysis results require"):
        AnalysisAgentResult(status=AnalysisAgentStatus.UNSUPPORTED)


def test_chart_spec_serializes_and_deserializes() -> None:
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Monthly trading volume",
        x="month",
        y=["volume"],
        x_label="Month",
        y_label="Volume",
        aggregation="sum",
        sort="x_ascending",
    )

    restored = ChartSpec.model_validate_json(spec.model_dump_json())

    assert restored == spec


def test_chart_spec_accepts_none_chart_without_encodings() -> None:
    spec = ChartSpec(chart_type=ChartType.NONE, title="No chart recommended")

    assert spec.chart_type == ChartType.NONE
    assert spec.x is None
    assert spec.y == []


def test_chart_spec_rejects_duplicate_y_columns() -> None:
    with pytest.raises(ValidationError, match="y columns must be unique"):
        ChartSpec(
            chart_type=ChartType.BAR,
            title="Revenue by country",
            x="country",
            y=["revenue", "revenue"],
        )


def test_chart_spec_rejects_none_chart_with_encodings() -> None:
    with pytest.raises(ValidationError, match="none charts"):
        ChartSpec(
            chart_type=ChartType.NONE,
            title="No chart recommended",
            x="country",
        )


def test_chart_spec_rejects_unknown_chart_type() -> None:
    with pytest.raises(ValidationError, match="chart_type"):
        ChartSpec(chart_type="pie", title="Revenue share")
