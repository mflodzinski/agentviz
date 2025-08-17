from datetime import UTC, datetime

import pytest

from agentviz.errors import ChartValidationError
from agentviz.models import (
    AnalysisArtifact,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    QueryProvenance,
    Row,
    UserIdentity,
)
from agentviz.visualization import ChartValidator


def artifact_with_rows(
    rows: list[Row],
    *,
    truncated: bool = False,
) -> AnalysisArtifact:
    columns = list(rows[0]) if rows else ["category", "value"]
    return AnalysisArtifact(
        request=AnalysisRequest(
            user=UserIdentity(username="alice"),
            database="chinook",
            question="Show values.",
        ),
        database="chinook",
        sql="SELECT category, value FROM metrics",
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        summary="Returned values.",
        provenance=QueryProvenance(
            user="alice",
            database="chinook",
            executed_sql="SELECT category, value FROM metrics",
            tables_used=frozenset({"metrics"}),
            row_count=len(rows),
            truncated=truncated,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )


def test_chart_validator_accepts_valid_bar_chart() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec


def test_chart_validator_rejects_missing_column() -> None:
    artifact = artifact_with_rows([{"category": "A", "value": 10}])
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="missing",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="missing column"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_rejects_empty_data_for_rendered_chart() -> None:
    artifact = artifact_with_rows([])
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="non-empty data"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_allows_none_chart_for_empty_data() -> None:
    artifact = artifact_with_rows([])
    spec = ChartSpec(chart_type=ChartType.NONE, title="No chart")

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec


def test_chart_validator_rejects_all_null_column() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": None},
            {"category": "B", "value": None},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="all null"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_rejects_partial_null_plotted_column() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": None},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="contains null"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_rejects_excessive_bar_categories() -> None:
    artifact = artifact_with_rows(
        [{"category": f"category-{index}", "value": index} for index in range(3)]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="too many categories"):
        ChartValidator(max_categories=2).validate(spec=spec, artifact=artifact)


def test_chart_validator_rejects_unreadable_category_labels() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "short", "value": 10},
            {
                "category": "this label is too long for the configured limit",
                "value": 12,
            },
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="labels are too long"):
        ChartValidator(max_category_label_length=20).validate(
            spec=spec,
            artifact=artifact,
        )


def test_chart_validator_rejects_line_chart_with_unordered_x() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="ordered or temporal"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_accepts_line_chart_with_temporal_x() -> None:
    artifact = artifact_with_rows(
        [
            {"month": "2026-01-01", "value": 10},
            {"month": "2026-02-01", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by month",
        x="month",
        y=["value"],
    )

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec


def test_chart_validator_accepts_line_chart_with_year_month_x() -> None:
    artifact = artifact_with_rows(
        [
            {"month": "2026-01", "value": 10},
            {"month": "2026-02", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by month",
        x="month",
        y=["value"],
    )

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec


def test_chart_validator_rejects_line_chart_with_unsorted_temporal_x() -> None:
    artifact = artifact_with_rows(
        [
            {"month": "2026-02-01", "value": 12},
            {"month": "2026-01-01", "value": 10},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by month",
        x="month",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="must be sorted"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_rejects_non_table_chart_for_truncated_data() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ],
        truncated=True,
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="non-truncated data"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_allows_table_for_truncated_data() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ],
        truncated=True,
    )
    spec = ChartSpec(chart_type=ChartType.TABLE, title="Partial result table")

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec


def test_chart_validator_rejects_scatter_with_non_numeric_x() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.SCATTER,
        title="Value by category",
        x="category",
        y=["value"],
    )

    with pytest.raises(ChartValidationError, match="numeric"):
        ChartValidator().validate(spec=spec, artifact=artifact)


def test_chart_validator_accepts_histogram_with_numeric_x() -> None:
    artifact = artifact_with_rows(
        [
            {"value": 10},
            {"value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.HISTOGRAM,
        title="Value distribution",
        x="value",
    )

    assert ChartValidator().validate(spec=spec, artifact=artifact) == spec
