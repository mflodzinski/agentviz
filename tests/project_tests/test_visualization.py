import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agentviz.agents import AnalysisAgent, DemoVisualizationPlanner, VisualizationAgent
from agentviz.analysis import AnalysisExecutionService
from agentviz.auth import AclPolicyEngine, AuthorizedSchemaService
from agentviz.database import DatabaseRegistry
from agentviz.models import (
    AnalysisPlan,
    AnalysisRequest,
    ChartType,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    ProposedQuery,
    UserIdentity,
)
from agentviz.orchestrator import ApplicationOrchestrator
from agentviz.visualization import ChartRenderer


@dataclass
class MonthlyRevenuePlanner:
    """Deterministic planner double for the required visualization evaluation."""

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        return AnalysisPlan.query_plan(
            ProposedQuery(
                sql=(
                    "SELECT month, SUM(revenue) AS revenue "
                    "FROM monthly_revenue "
                    "GROUP BY month "
                    "ORDER BY month"
                ),
                reasoning_summary=(
                    "The monthly_revenue table contains time-series revenue rows."
                ),
            )
        )

    def repair_query(self, **kwargs):  # pragma: no cover
        raise AssertionError("visualization evaluation should not need SQL repair")


def create_monthly_revenue_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "revenue.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE monthly_revenue (
            month TEXT NOT NULL,
            revenue REAL NOT NULL
        );

        INSERT INTO monthly_revenue (month, revenue)
        VALUES
            ('2026-01-01', 100.00),
            ('2026-02-01', 120.00),
            ('2026-03-01', 90.00),
            ('2026-04-01', 140.00);
        """
    )
    connection.close()
    return database_path


def test_evaluation_visualization_selects_line_chart_and_renders_png(
    tmp_path: Path,
) -> None:
    database_path = create_monthly_revenue_database(tmp_path)
    registry = DatabaseRegistry(
        {
            "sales": DatabaseConfig(
                name="sales",
                backend=DatabaseBackend.SQLITE,
                path=database_path,
            )
        }
    )
    policy = AclPolicyEngine({}, all_databases={"sales"})
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question="Show monthly revenue over time.",
        include_visualization=True,
    )
    orchestrator = ApplicationOrchestrator(
        schema_service=AuthorizedSchemaService(policy=policy, registry=registry),
        analysis_agent=AnalysisAgent(
            planner=MonthlyRevenuePlanner(),
            execution_service=AnalysisExecutionService(
                policy=policy,
                registry=registry,
            ),
        ),
        visualization_agent=VisualizationAgent(planner=DemoVisualizationPlanner()),
        renderer=ChartRenderer(),
    )
    output_path = tmp_path / "runs/visualization/chart.png"

    result = orchestrator.run(
        request=request,
        chart_output_path=output_path,
        run_id="20260816_123456_a1b2c3d4",
    )

    assert result.analysis.artifact is not None
    assert result.analysis.artifact.rows == [
        {"month": "2026-01-01", "revenue": 100.0},
        {"month": "2026-02-01", "revenue": 120.0},
        {"month": "2026-03-01", "revenue": 90.0},
        {"month": "2026-04-01", "revenue": 140.0},
    ]
    assert result.chart_spec is not None
    assert result.chart_spec.chart_type == ChartType.LINE
    assert result.chart_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert output_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
