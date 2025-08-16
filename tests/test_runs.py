import json
from datetime import UTC, datetime

import pytest

from agentviz.models import (
    AnalysisAgentResult,
    AnalysisArtifact,
    AnalysisRequest,
    ApplicationRunResult,
    ChartSpec,
    ChartType,
    QueryProvenance,
    UserIdentity,
)
from agentviz.runs import (
    build_run_manifest,
    default_chart_output_path,
    default_manifest_output_path,
    generate_run_id,
    is_valid_run_id,
    write_run_manifest,
)


def request() -> AnalysisRequest:
    return AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show revenue by country.",
    )


def application_result() -> ApplicationRunResult:
    analysis_request = request()
    artifact = AnalysisArtifact(
        request=analysis_request,
        database="chinook",
        sql="SELECT BillingCountry, SUM(Total) AS revenue FROM invoices",
        columns=["BillingCountry", "revenue"],
        rows=[{"BillingCountry": "USA", "revenue": 15.0}],
        row_count=1,
        truncated=False,
        summary="Returned revenue by country.",
        provenance=QueryProvenance(
            user="alice",
            database="chinook",
            executed_sql="SELECT BillingCountry, SUM(Total) AS revenue FROM invoices",
            tables_used=frozenset({"invoices"}),
            row_count=1,
            truncated=False,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )
    return ApplicationRunResult(
        run_id="20260816_123456_a1b2c3d4",
        analysis=AnalysisAgentResult.completed(artifact),
        chart_spec=ChartSpec(
            chart_type=ChartType.BAR,
            title="Revenue by country",
            x="BillingCountry",
            y=["revenue"],
        ),
        chart_path="runs/20260816_123456_a1b2c3d4/chart.png",
    )


def test_generate_run_id_uses_utc_timestamp_and_hex_suffix() -> None:
    run_id = generate_run_id(
        now=datetime(2026, 8, 16, 12, 34, 56, tzinfo=UTC),
        suffix="a1b2c3d4",
    )

    assert run_id == "20260816_123456_a1b2c3d4"
    assert is_valid_run_id(run_id)


def test_generate_run_id_normalizes_timezone_to_utc() -> None:
    run_id = generate_run_id(
        now=datetime.fromisoformat("2026-08-16T14:34:56+02:00"),
        suffix="a1b2c3d4",
    )

    assert run_id == "20260816_123456_a1b2c3d4"


def test_generate_run_id_rejects_invalid_suffix() -> None:
    with pytest.raises(ValueError, match="suffix"):
        generate_run_id(
            now=datetime(2026, 8, 16, tzinfo=UTC),
            suffix="not-valid",
        )


def test_default_chart_output_path_uses_run_directory() -> None:
    path = default_chart_output_path("20260816_123456_a1b2c3d4")

    assert path.as_posix() == "runs/20260816_123456_a1b2c3d4/chart.png"


def test_default_chart_output_path_rejects_invalid_run_id() -> None:
    with pytest.raises(ValueError, match="invalid run id"):
        default_chart_output_path("../escape")


def test_default_manifest_output_path_uses_run_directory() -> None:
    path = default_manifest_output_path("20260816_123456_a1b2c3d4")

    assert path.as_posix() == "runs/20260816_123456_a1b2c3d4/manifest.json"


def test_build_run_manifest_contains_row_free_reproducibility_metadata() -> None:
    manifest = build_run_manifest(request=request(), result=application_result())

    assert manifest == {
        "run_id": "20260816_123456_a1b2c3d4",
        "user": "alice",
        "database": "chinook",
        "request": "Show revenue by country.",
        "analysis_status": "completed",
        "analysis_message": None,
        "sql": "SELECT BillingCountry, SUM(Total) AS revenue FROM invoices",
        "columns": ["BillingCountry", "revenue"],
        "row_count": 1,
        "truncated": False,
        "chart_type": "bar",
        "chart_path": "runs/20260816_123456_a1b2c3d4/chart.png",
        "visualization_warning": None,
    }
    assert "rows" not in manifest
    assert "USA" not in json.dumps(manifest)


def test_build_run_manifest_handles_unsupported_analysis() -> None:
    analysis_request = request()
    result = ApplicationRunResult(
        run_id="20260816_123456_a1b2c3d4",
        analysis=AnalysisAgentResult.unsupported("No matching query."),
    )

    manifest = build_run_manifest(request=analysis_request, result=result)

    assert manifest["analysis_status"] == "unsupported"
    assert manifest["analysis_message"] == "No matching query."
    assert manifest["sql"] is None
    assert manifest["columns"] == []
    assert manifest["row_count"] == 0
    assert manifest["chart_type"] is None
    assert manifest["chart_path"] is None


def test_write_run_manifest_writes_sorted_json(tmp_path) -> None:
    output_path = tmp_path / "runs/20260816_123456_a1b2c3d4/manifest.json"

    result = write_run_manifest(
        request=request(),
        result=application_result(),
        output_path=output_path,
    )

    assert result == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "20260816_123456_a1b2c3d4"
    assert payload["row_count"] == 1
