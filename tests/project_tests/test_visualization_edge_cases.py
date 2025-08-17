from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentviz.agents import VisualizationAgent
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


def artifact_with_rows(rows: list[Row]) -> AnalysisArtifact:
    columns = list(rows[0]) if rows else ["category", "value"]
    return AnalysisArtifact(
        request=AnalysisRequest(
            user=UserIdentity(username="alice"),
            database="sales",
            question="Show values.",
        ),
        database="sales",
        sql="SELECT category, value FROM metrics",
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=False,
        summary="Returned values.",
        provenance=QueryProvenance(
            user="alice",
            database="sales",
            executed_sql="SELECT category, value FROM metrics",
            tables_used=frozenset({"metrics"}),
            row_count=len(rows),
            truncated=False,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )


class BadChartPlanner:
    def propose_chart(self, **kwargs) -> ChartSpec:
        return ChartSpec(
            chart_type=ChartType.BAR,
            title="Bad chart",
            x="missing",
            y=["value"],
        )


def test_evaluation_visualization_rejects_empty_data_for_rendered_chart() -> None:
    artifact = artifact_with_rows([])

    with pytest.raises(ChartValidationError, match="non-empty data"):
        ChartValidator().validate(
            artifact=artifact,
            spec=ChartSpec(
                chart_type=ChartType.BAR,
                title="Value by category",
                x="category",
                y=["value"],
            ),
        )


def test_evaluation_visualization_rejects_all_null_plotted_values() -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": None},
            {"category": "B", "value": None},
        ]
    )

    with pytest.raises(ChartValidationError, match="all null"):
        ChartValidator().validate(
            artifact=artifact,
            spec=ChartSpec(
                chart_type=ChartType.BAR,
                title="Value by category",
                x="category",
                y=["value"],
            ),
        )


def test_evaluation_visualization_allows_single_scalar_no_chart_decision() -> None:
    artifact = artifact_with_rows([{"total_revenue": 225.0}])
    spec = ChartSpec(chart_type=ChartType.NONE, title="Single scalar")

    assert ChartValidator().validate(artifact=artifact, spec=spec) == spec


def test_evaluation_visualization_rejects_too_many_categories() -> None:
    artifact = artifact_with_rows(
        [{"category": f"category-{index}", "value": index} for index in range(4)]
    )

    with pytest.raises(ChartValidationError, match="too many categories"):
        ChartValidator(max_categories=3).validate(
            artifact=artifact,
            spec=ChartSpec(
                chart_type=ChartType.BAR,
                title="Value by category",
                x="category",
                y=["value"],
            ),
        )


def test_evaluation_visualization_rejects_bad_chart_spec_from_agent() -> None:
    artifact = artifact_with_rows([{"category": "A", "value": 10}])
    agent = VisualizationAgent(planner=BadChartPlanner())

    with pytest.raises(ChartValidationError, match="missing column"):
        agent.run(artifact=artifact)


def test_evaluation_visualization_rejects_none_chart_with_encoding() -> None:
    with pytest.raises(ValidationError, match="none charts"):
        ChartSpec(chart_type=ChartType.NONE, title="Bad none chart", x="category")


def test_evaluation_visualization_rejects_non_numeric_scatter_y() -> None:
    artifact = artifact_with_rows(
        [
            {"x": 1, "label": "A"},
            {"x": 2, "label": "B"},
        ]
    )

    with pytest.raises(ChartValidationError, match="numeric"):
        ChartValidator().validate(
            artifact=artifact,
            spec=ChartSpec(
                chart_type=ChartType.SCATTER,
                title="Label by x",
                x="x",
                y=["label"],
            ),
        )
