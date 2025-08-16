import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentviz.auth import AclPolicyEngine, AuthorizedSchemaService
from agentviz.config import UserAccessConfig
from agentviz.database import DatabaseAdapter
from agentviz.errors import (
    AuthorizationError,
    ChartRenderingError,
    ChartValidationError,
    RequestSafetyError,
)
from agentviz.models import (
    AnalysisAgentResult,
    AnalysisArtifact,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    QueryProvenance,
    Row,
    TableMetadata,
    UserIdentity,
)
from agentviz.observability import LOGGER_NAME
from agentviz.orchestrator import ApplicationOrchestrator


@dataclass
class RecordingSchemaAdapter:
    schema_calls: int = 0

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
                    name="metrics",
                    columns=[ColumnMetadata(name="value", data_type="INTEGER")],
                )
            ],
        )

    def execute_query(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("orchestrator schema adapter should not execute queries")


class RecordingRegistry:
    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        self.get_calls: list[str] = []

    def get(self, database: str) -> DatabaseAdapter:
        self.get_calls.append(database)
        return self.adapter


@dataclass
class RecordingAnalysisAgent:
    result: AnalysisAgentResult
    calls: list[tuple[AnalysisRequest, DatabaseMetadata, str | None]] = field(
        default_factory=list
    )

    def run(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        run_id: str | None = None,
    ) -> AnalysisAgentResult:
        self.calls.append((request, schema, run_id))
        return self.result


@dataclass
class RecordingVisualizationAgent:
    spec: ChartSpec
    error: Exception | None = None
    artifacts: list[AnalysisArtifact] = field(default_factory=list)

    def run(self, *, artifact: AnalysisArtifact) -> ChartSpec:
        self.artifacts.append(artifact)
        if self.error is not None:
            raise self.error
        return self.spec


@dataclass
class RecordingRenderer:
    error: Exception | None = None
    calls: list[tuple[AnalysisArtifact, ChartSpec, Path]] = field(default_factory=list)

    def render(
        self,
        *,
        artifact: AnalysisArtifact,
        spec: ChartSpec,
        output_path: Path,
    ) -> Path:
        self.calls.append((artifact, spec, output_path))
        if self.error is not None:
            raise self.error
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"rendered")
        return output_path


def request(
    *,
    username: str = "alice",
    include_visualization: bool = True,
    question: str = "Show values.",
) -> AnalysisRequest:
    return AnalysisRequest(
        user=UserIdentity(username=username),
        database="chinook",
        question=question,
        include_visualization=include_visualization,
    )


def artifact(rows: list[Row] | None = None) -> AnalysisArtifact:
    rows = rows or [{"category": "A", "value": 10}]
    return AnalysisArtifact(
        request=request(),
        database="chinook",
        sql="SELECT category, value FROM metrics",
        columns=list(rows[0]),
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


def orchestrator(
    *,
    analysis_result: AnalysisAgentResult,
    chart_spec: ChartSpec | None = None,
    visualization_error: Exception | None = None,
    rendering_error: Exception | None = None,
    users: dict[str, UserAccessConfig] | None = None,
) -> tuple[
    ApplicationOrchestrator,
    RecordingSchemaAdapter,
    RecordingRegistry,
    RecordingAnalysisAgent,
    RecordingVisualizationAgent,
    RecordingRenderer,
]:
    adapter = RecordingSchemaAdapter()
    registry = RecordingRegistry(adapter)
    users = users or {}
    schema_service = AuthorizedSchemaService(
        policy=AclPolicyEngine(users, all_databases={"chinook", "other"}),
        registry=registry,
    )
    analysis_agent = RecordingAnalysisAgent(result=analysis_result)
    visualization_agent = RecordingVisualizationAgent(
        spec=chart_spec
        or ChartSpec(
            chart_type=ChartType.BAR,
            title="Value by category",
            x="category",
            y=["value"],
        )
    )
    renderer = RecordingRenderer()
    visualization_agent.error = visualization_error
    renderer.error = rendering_error
    app = ApplicationOrchestrator(
        schema_service=schema_service,
        analysis_agent=analysis_agent,
        visualization_agent=visualization_agent,
        renderer=renderer,
    )
    return app, adapter, registry, analysis_agent, visualization_agent, renderer


def test_orchestrator_runs_analysis_visualization_and_renderer(tmp_path) -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, adapter, registry, analysis_agent, visualization_agent, renderer = (
        orchestrator(analysis_result=analysis_result)
    )
    output_path = tmp_path / "chart.png"

    result = app.run(request=request(), chart_output_path=output_path)

    assert result.run_id
    assert result.analysis == analysis_result
    assert result.chart_spec is not None
    assert result.chart_path == output_path
    assert result.visualization_warning is None
    assert output_path.read_bytes() == b"rendered"
    assert registry.get_calls == ["chinook"]
    assert adapter.schema_calls == 1
    assert len(analysis_agent.calls) == 1
    assert analysis_agent.calls[0][2] == result.run_id
    assert visualization_agent.artifacts == [analysis_result.artifact]
    assert renderer.calls == [
        (analysis_result.artifact, result.chart_spec, output_path)
    ]


def test_orchestrator_authorizes_before_agent_invocation() -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, adapter, registry, analysis_agent, visualization_agent, renderer = (
        orchestrator(
            analysis_result=analysis_result,
            users={"bob": UserAccessConfig(denied_databases=["chinook"])},
        )
    )

    with pytest.raises(AuthorizationError):
        app.run(request=request(username="bob"))

    assert registry.get_calls == []
    assert adapter.schema_calls == 0
    assert analysis_agent.calls == []
    assert visualization_agent.artifacts == []
    assert renderer.calls == []


def test_orchestrator_rejects_malicious_request_before_schema_access() -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, adapter, registry, analysis_agent, visualization_agent, renderer = (
        orchestrator(analysis_result=analysis_result)
    )

    with pytest.raises(RequestSafetyError):
        app.run(request=request(question="Show invoices; then drop customers."))

    assert registry.get_calls == []
    assert adapter.schema_calls == 0
    assert analysis_agent.calls == []
    assert visualization_agent.artifacts == []
    assert renderer.calls == []


def test_orchestrator_skips_visualization_when_request_disables_it(tmp_path) -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result
    )

    result = app.run(
        request=request(include_visualization=False),
        chart_output_path=tmp_path / "chart.png",
        run_id="20260816_123456_a1b2c3d4",
    )

    assert result.run_id == "20260816_123456_a1b2c3d4"
    assert result.analysis == analysis_result
    assert result.chart_spec is None
    assert result.chart_path is None
    assert result.visualization_warning is None
    assert visualization_agent.artifacts == []
    assert renderer.calls == []


def test_orchestrator_skips_visualization_for_non_completed_analysis() -> None:
    analysis_result = AnalysisAgentResult.needs_clarification("Which metric?")
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result
    )

    result = app.run(request=request())

    assert result.run_id
    assert result.analysis == analysis_result
    assert result.chart_spec is None
    assert result.chart_path is None
    assert result.visualization_warning is None
    assert visualization_agent.artifacts == []
    assert renderer.calls == []


def test_orchestrator_does_not_render_none_chart(tmp_path) -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    none_spec = ChartSpec(chart_type=ChartType.NONE, title="No chart")
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result,
        chart_spec=none_spec,
    )

    result = app.run(request=request(), chart_output_path=tmp_path / "chart.png")

    assert result.run_id
    assert result.chart_spec == none_spec
    assert result.chart_path is None
    assert result.visualization_warning is None
    assert visualization_agent.artifacts == [analysis_result.artifact]
    assert renderer.calls == []


def test_orchestrator_skips_visualization_for_single_value_result(tmp_path) -> None:
    analysis_result = AnalysisAgentResult.completed(
        artifact([{"distinct_billing_countries": 24}])
    )
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result
    )

    result = app.run(request=request(), chart_output_path=tmp_path / "chart.png")

    assert result.run_id
    assert result.analysis == analysis_result
    assert result.chart_spec == ChartSpec(
        chart_type=ChartType.NONE,
        title="Single value result does not need a chart",
    )
    assert result.chart_path is None
    assert result.visualization_warning is None
    assert visualization_agent.artifacts == []
    assert renderer.calls == []


def test_orchestrator_returns_warning_when_visualization_agent_fails() -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result,
        visualization_error=ChartValidationError("chart references missing column"),
    )

    result = app.run(request=request())

    assert result.run_id
    assert result.analysis == analysis_result
    assert result.chart_spec is None
    assert result.chart_path is None
    assert result.visualization_warning == "chart references missing column"
    assert visualization_agent.artifacts == [analysis_result.artifact]
    assert renderer.calls == []


def test_orchestrator_returns_warning_when_renderer_fails(tmp_path) -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result,
        rendering_error=ChartRenderingError("could not write chart"),
    )
    output_path = tmp_path / "chart.png"

    result = app.run(request=request(), chart_output_path=output_path)

    assert result.run_id
    assert result.analysis == analysis_result
    assert result.chart_spec is not None
    assert result.chart_path is None
    assert result.visualization_warning == "could not write chart"
    assert visualization_agent.artifacts == [analysis_result.artifact]
    assert renderer.calls == [
        (analysis_result.artifact, result.chart_spec, output_path)
    ]
    assert not output_path.exists()


def test_orchestrator_requires_output_path_for_rendered_chart() -> None:
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, _, _, _, visualization_agent, renderer = orchestrator(
        analysis_result=analysis_result
    )

    with pytest.raises(ValueError, match="chart_output_path"):
        app.run(request=request())

    assert visualization_agent.artifacts == [analysis_result.artifact]
    assert renderer.calls == []


def test_orchestrator_emits_structured_workflow_logs(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    analysis_result = AnalysisAgentResult.completed(artifact())
    app, _, _, _, _, _ = orchestrator(analysis_result=analysis_result)

    result = app.run(
        request=request(),
        chart_output_path=tmp_path / "chart.png",
        run_id="20260816_123456_a1b2c3d4",
    )

    events = [json.loads(record.message) for record in caplog.records]
    event_names = [event["event"] for event in events]
    assert result.run_id == "20260816_123456_a1b2c3d4"
    assert "workflow.started" in event_names
    assert "schema_access.completed" in event_names
    assert "analysis.completed" in event_names
    assert "visualization_agent.completed" in event_names
    assert "rendering.completed" in event_names
    assert all(event["run_id"] == "20260816_123456_a1b2c3d4" for event in events)
    rendering_event = next(
        event for event in events if event["event"] == "rendering.completed"
    )
    assert rendering_event["chart_type"] == "bar"
    assert rendering_event["chart_path"].endswith("chart.png")
