import pytest
from pydantic import ValidationError

from agentviz.models import (
    AnalysisRequest,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    QueryExecutionResult,
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
