from dataclasses import dataclass, field

import pytest

from agentviz.agents import AnalysisAgent
from agentviz.analysis import AnalysisExecutionService
from agentviz.auth import AclPolicyEngine
from agentviz.database import DatabaseAdapter
from agentviz.errors import AgentInputError, SQLValidationError
from agentviz.models import (
    AnalysisAgentStatus,
    AnalysisPlan,
    AnalysisRequest,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    ProposedQuery,
    QueryExecutionResult,
    TableMetadata,
    UserIdentity,
)


@dataclass
class RecordingAdapter:
    executed: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "sales"

    @property
    def backend(self) -> DatabaseBackend:
        return DatabaseBackend.SQLITE

    def get_schema(self) -> DatabaseMetadata:
        return sales_schema()

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: float | None = None,
    ) -> QueryExecutionResult:
        self.executed.append(sql)
        return QueryExecutionResult(
            executed_sql=sql,
            columns=["category"],
            rows=[{"category": "Software"}],
            row_count=1,
            truncated=False,
        )


class RecordingRegistry:
    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        self.get_calls: list[str] = []

    def get(self, database: str) -> DatabaseAdapter:
        self.get_calls.append(database)
        return self.adapter


@dataclass
class StaticPlanner:
    plan_output: object

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> object:
        return self.plan_output

    def repair_query(self, **kwargs):  # pragma: no cover
        raise AssertionError("agent failure eval should not need SQL repair")


def sales_schema() -> DatabaseMetadata:
    return DatabaseMetadata(
        name="sales",
        backend=DatabaseBackend.SQLITE,
        tables=[
            TableMetadata(
                name="sales",
                columns=[
                    ColumnMetadata(name="category", data_type="TEXT"),
                    ColumnMetadata(name="revenue", data_type="REAL"),
                ],
            )
        ],
    )


def request(question: str = "Which category has the largest total revenue?"):
    return AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question=question,
        include_visualization=False,
    )


def agent_with(planner: StaticPlanner, registry: RecordingRegistry) -> AnalysisAgent:
    return AnalysisAgent(
        planner=planner,  # type: ignore[arg-type]
        execution_service=AnalysisExecutionService(
            policy=AclPolicyEngine({}, all_databases={"sales"}),
            registry=registry,
        ),
    )


def test_evaluation_agent_failure_rejects_malformed_structured_output() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    planner = StaticPlanner(plan_output={"sql": "SELECT category FROM sales"})
    agent = agent_with(planner, registry)

    with pytest.raises(AgentInputError, match="malformed plan"):
        agent.run(request=request(), schema=sales_schema())

    assert registry.get_calls == []
    assert adapter.executed == []


def test_evaluation_agent_failure_rejects_incorrect_sql_before_execution() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    planner = StaticPlanner(
        plan_output=AnalysisPlan.query_plan(ProposedQuery(sql="SELECT FROM"))
    )
    agent = agent_with(planner, registry)

    with pytest.raises(SQLValidationError, match="could not be parsed"):
        agent.run(request=request(), schema=sales_schema())

    assert registry.get_calls == []
    assert adapter.executed == []


def test_evaluation_agent_failure_rejects_hallucinated_table_before_execution() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    planner = StaticPlanner(
        plan_output=AnalysisPlan.query_plan(
            ProposedQuery(sql="SELECT category FROM imaginary_sales")
        )
    )
    agent = agent_with(planner, registry)

    with pytest.raises(SQLValidationError, match="outside authorized schema"):
        agent.run(request=request(), schema=sales_schema())

    assert registry.get_calls == ["sales"]
    assert adapter.executed == []


def test_evaluation_agent_failure_returns_unsupported_for_missing_data() -> None:
    adapter = RecordingAdapter()
    registry = RecordingRegistry(adapter)
    planner = StaticPlanner(
        plan_output=AnalysisPlan.unsupported(
            "The selected database does not contain refund data."
        )
    )
    agent = agent_with(planner, registry)

    result = agent.run(
        request=request("Which category has the most refunds?"),
        schema=sales_schema(),
    )

    assert result.status == AnalysisAgentStatus.UNSUPPORTED
    assert result.message == "The selected database does not contain refund data."
    assert result.artifact is None
    assert registry.get_calls == []
    assert adapter.executed == []
