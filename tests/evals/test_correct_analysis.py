import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agentviz.agents import AnalysisAgent
from agentviz.analysis import AnalysisExecutionService
from agentviz.auth import AclPolicyEngine
from agentviz.database import DatabaseRegistry
from agentviz.models import (
    AnalysisAgentStatus,
    AnalysisPlan,
    AnalysisRequest,
    DatabaseBackend,
    DatabaseConfig,
    DatabaseMetadata,
    ProposedQuery,
    UserIdentity,
)


@dataclass
class RevenueCategoryPlanner:
    """Deterministic planner double for the required analysis evaluation."""

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        return AnalysisPlan.query_plan(
            ProposedQuery(
                sql=(
                    "SELECT category, SUM(revenue) AS total_revenue "
                    "FROM sales "
                    "GROUP BY category "
                    "ORDER BY total_revenue DESC "
                    "LIMIT 1"
                ),
                reasoning_summary=(
                    "The sales table contains category-level revenue records."
                ),
            )
        )

    def repair_query(self, **kwargs):  # pragma: no cover
        raise AssertionError("correct-analysis evaluation should not need SQL repair")


def create_sales_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "sales.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE sales (
            sale_id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            revenue REAL NOT NULL
        );

        INSERT INTO sales (sale_id, category, revenue)
        VALUES
            (1, 'Hardware', 125.00),
            (2, 'Software', 200.00),
            (3, 'Hardware', 75.00),
            (4, 'Services', 50.00),
            (5, 'Software', 25.00);
        """
    )
    connection.close()
    return database_path


def test_evaluation_correct_analysis_returns_expected_category(tmp_path: Path) -> None:
    database_path = create_sales_database(tmp_path)
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question="Which category has the largest total revenue?",
        include_visualization=False,
    )
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
    schema = registry.get("sales").get_schema()
    agent = AnalysisAgent(
        planner=RevenueCategoryPlanner(),
        execution_service=AnalysisExecutionService(
            policy=policy,
            registry=registry,
        ),
    )

    result = agent.run(
        request=request,
        schema=schema,
        run_id="20260816_123456_a1b2c3d4",
    )

    assert result.status == AnalysisAgentStatus.COMPLETED
    assert result.artifact is not None
    artifact = result.artifact
    assert artifact.rows == [{"category": "Software", "total_revenue": 225.0}]
    assert artifact.sql == (
        "SELECT category, SUM(revenue) AS total_revenue "
        "FROM sales "
        "GROUP BY category "
        "ORDER BY total_revenue DESC "
        "LIMIT 1"
    )
    assert artifact.provenance.database == "sales"
    assert artifact.provenance.user == "alice"
    assert artifact.provenance.executed_sql == artifact.sql
    assert artifact.provenance.tables_used == frozenset({"sales"})
