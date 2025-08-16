from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agentviz.agents import AnalysisAgent, VisualizationAgent
from agentviz.auth import AclPolicyEngine, AuthorizedSchemaService
from agentviz.config import UserAccessConfig
from agentviz.database import DatabaseAdapter
from agentviz.errors import AuthorizationError
from agentviz.models import (
    AnalysisPlan,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    DatabaseBackend,
    DatabaseMetadata,
    ProposedQuery,
    QueryExecutionResult,
    UserIdentity,
)
from agentviz.orchestrator import ApplicationOrchestrator


@dataclass
class RecordingAdapter:
    schema_calls: int = 0
    execution_calls: int = 0

    @property
    def name(self) -> str:
        return "finance"

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        self.schema_calls += 1
        raise AssertionError("unauthorized evaluation must not inspect schema")

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        self.execution_calls += 1
        raise AssertionError("unauthorized evaluation must not execute SQL")


class RecordingRegistry:
    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        self.get_calls: list[str] = []

    def get(self, database: str) -> DatabaseAdapter:
        self.get_calls.append(database)
        return self.adapter


@dataclass
class RecordingAnalysisPlanner:
    calls: int = 0

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        self.calls += 1
        return AnalysisPlan.query_plan(
            ProposedQuery(sql="SELECT SUM(amount) AS total_expenses FROM expenses")
        )

    def repair_query(self, **kwargs):  # pragma: no cover
        raise AssertionError("unauthorized evaluation must not repair SQL")


@dataclass
class RecordingVisualizationPlanner:
    calls: int = 0

    def propose_chart(self, **kwargs) -> ChartSpec:
        self.calls += 1
        return ChartSpec(chart_type=ChartType.NONE, title="No chart")


@dataclass
class RecordingRenderer:
    calls: list[Path] = field(default_factory=list)

    def render(self, **kwargs) -> Path:
        output_path = kwargs["output_path"]
        self.calls.append(output_path)
        raise AssertionError("unauthorized evaluation must not render a chart")


def test_evaluation_user_restriction_blocks_before_database_or_agent_access() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    policy = AclPolicyEngine(
        {
            "alice": UserAccessConfig(denied_databases=[]),
            "bob": UserAccessConfig(denied_databases=["finance"]),
        },
        all_databases={"sales", "finance"},
    )
    analysis_planner = RecordingAnalysisPlanner()
    visualization_planner = RecordingVisualizationPlanner()
    renderer = RecordingRenderer()
    orchestrator = ApplicationOrchestrator(
        schema_service=AuthorizedSchemaService(policy=policy, registry=registry),
        analysis_agent=AnalysisAgent(
            planner=analysis_planner,
            execution_service=object(),  # type: ignore[arg-type]
        ),
        visualization_agent=VisualizationAgent(planner=visualization_planner),
        renderer=renderer,
    )
    request = AnalysisRequest(
        user=UserIdentity(username="bob"),
        database="finance",
        question="Show total expenses",
        include_visualization=True,
    )

    with pytest.raises(AuthorizationError):
        orchestrator.run(
            request=request,
            chart_output_path=Path("runs/blocked/chart.png"),
            run_id="20260816_123456_a1b2c3d4",
        )

    assert registry.get_calls == []
    assert adapter.schema_calls == 0
    assert adapter.execution_calls == 0
    assert analysis_planner.calls == 0
    assert visualization_planner.calls == 0
    assert renderer.calls == []
