from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

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
    VisualizationColumnType,
    VisualizationContext,
)


@dataclass
class RecordingVisualizationPlanner:
    spec: ChartSpec
    contexts: list[VisualizationContext] = field(default_factory=list)

    def propose_chart(self, *, context: VisualizationContext) -> ChartSpec:
        self.contexts.append(context)
        return self.spec


@dataclass
class NoChartAwarePlanner:
    contexts: list[VisualizationContext] = field(default_factory=list)

    def propose_chart(self, *, context: VisualizationContext) -> ChartSpec:
        self.contexts.append(context)
        if context.row_count == 0:
            return ChartSpec(chart_type=ChartType.NONE, title="No rows returned")

        if all(
            column.inferred_type == VisualizationColumnType.CATEGORICAL
            for column in context.columns
        ):
            return ChartSpec(chart_type=ChartType.NONE, title="Text-only result")

        if len(context.columns) == 1 and context.row_count == 1:
            return ChartSpec(chart_type=ChartType.NONE, title="Single value result")

        return ChartSpec(
            chart_type=ChartType.BAR,
            title="Value by category",
            x="category",
            y=["value"],
        )


def artifact_with_rows(rows: list[Row]) -> AnalysisArtifact:
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
        truncated=False,
        summary="Returned values.",
        provenance=QueryProvenance(
            user="alice",
            database="chinook",
            executed_sql="SELECT category, value FROM metrics",
            tables_used=frozenset({"metrics"}),
            row_count=len(rows),
            truncated=False,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )


def test_visualization_agent_returns_validated_chart_spec() -> None:
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
    planner = RecordingVisualizationPlanner(spec=spec)
    agent = VisualizationAgent(planner=planner)

    result = agent.run(artifact=artifact)

    assert result == spec
    assert len(planner.contexts) == 1
    context = planner.contexts[0]
    assert context.question == "Show values."
    assert context.database == "chinook"
    assert context.row_count == 2
    assert [(column.name, column.inferred_type) for column in context.columns] == [
        ("category", VisualizationColumnType.CATEGORICAL),
        ("value", VisualizationColumnType.NUMERIC),
    ]


def test_visualization_agent_rejects_invalid_chart_spec() -> None:
    artifact = artifact_with_rows([{"category": "A", "value": 10}])
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="missing",
        y=["value"],
    )
    planner = RecordingVisualizationPlanner(spec=spec)
    agent = VisualizationAgent(planner=planner)

    with pytest.raises(ChartValidationError, match="missing column"):
        agent.run(artifact=artifact)

    assert len(planner.contexts) == 1


def test_visualization_agent_allows_none_chart_for_empty_artifact() -> None:
    artifact = artifact_with_rows([])
    spec = ChartSpec(chart_type=ChartType.NONE, title="No chart recommended")
    planner = RecordingVisualizationPlanner(spec=spec)
    agent = VisualizationAgent(planner=planner)

    result = agent.run(artifact=artifact)

    assert result == spec
    assert len(planner.contexts) == 1


def test_visualization_agent_can_choose_no_chart_for_empty_result() -> None:
    artifact = artifact_with_rows([])
    planner = NoChartAwarePlanner()
    agent = VisualizationAgent(planner=planner)

    result = agent.run(artifact=artifact)

    assert result.chart_type == ChartType.NONE
    assert result.title == "No rows returned"
    assert len(planner.contexts) == 1


def test_visualization_agent_can_choose_no_chart_for_single_scalar() -> None:
    artifact = artifact_with_rows([{"total_revenue": 523.06}])
    planner = NoChartAwarePlanner()
    agent = VisualizationAgent(planner=planner)

    result = agent.run(artifact=artifact)

    assert result.chart_type == ChartType.NONE
    assert result.title == "Single value result"
    assert len(planner.contexts) == 1
    assert planner.contexts[0].columns[0].name == "total_revenue"
    assert planner.contexts[0].columns[0].inferred_type == (
        VisualizationColumnType.NUMERIC
    )


def test_visualization_agent_can_choose_no_chart_for_short_text_result() -> None:
    artifact = artifact_with_rows([{"answer": "No matching invoices found."}])
    planner = NoChartAwarePlanner()
    agent = VisualizationAgent(planner=planner)

    result = agent.run(artifact=artifact)

    assert result.chart_type == ChartType.NONE
    assert result.title == "Text-only result"
    assert len(planner.contexts) == 1
    assert planner.contexts[0].columns[0].inferred_type == (
        VisualizationColumnType.CATEGORICAL
    )
