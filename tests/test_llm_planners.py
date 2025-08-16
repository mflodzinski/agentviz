from dataclasses import dataclass, field

import pytest

from agentviz.agents import LLMAnalysisPlanner, LLMVisualizationPlanner
from agentviz.errors import DatabaseExecutionError, LLMClientError
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
    AnalysisPlanKind,
    AnalysisRequest,
    ChartType,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    ProposedQuery,
    TableMetadata,
    UserIdentity,
    VisualizationColumnProfile,
    VisualizationColumnType,
    VisualizationContext,
)


@dataclass
class FakeLLMClient:
    responses: list[dict]
    requests: list[StructuredLLMRequest] = field(default_factory=list)

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        self.requests.append(request)
        return StructuredLLMResponse(
            provider="test",
            model="fake-model",
            content=self.responses.pop(0),
        )


def request() -> AnalysisRequest:
    return AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="chinook",
        question="Show total revenue.",
    )


def schema() -> DatabaseMetadata:
    return DatabaseMetadata(
        name="chinook",
        backend=DatabaseBackend.SQLITE,
        tables=[
            TableMetadata(
                name="invoices",
                columns=[
                    ColumnMetadata(name="InvoiceId", data_type="INTEGER"),
                    ColumnMetadata(name="Total", data_type="NUMERIC"),
                    ColumnMetadata(name="BillingCountry", data_type="TEXT"),
                ],
            )
        ],
    )


def visualization_context() -> VisualizationContext:
    return VisualizationContext(
        question="Show revenue by country.",
        database="chinook",
        summary="Returned revenue by country.",
        row_count=2,
        truncated=False,
        columns=[
            VisualizationColumnProfile(
                name="BillingCountry",
                inferred_type=VisualizationColumnType.CATEGORICAL,
                null_count=0,
                non_null_count=2,
                distinct_count=2,
            ),
            VisualizationColumnProfile(
                name="revenue",
                inferred_type=VisualizationColumnType.NUMERIC,
                null_count=0,
                non_null_count=2,
                distinct_count=2,
                numeric_min=10,
                numeric_max=20,
            ),
        ],
    )


def test_llm_analysis_planner_returns_query_plan() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "query",
                "sql": "SELECT SUM(Total) AS total_revenue FROM invoices",
                "reasoning_summary": "Revenue is stored in invoice totals.",
                "message": None,
            }
        ]
    )
    planner = LLMAnalysisPlanner(
        client=client,
        temperature=0,
        metadata={"run_id": "run-1"},
    )

    plan = planner.plan(request=request(), schema=schema())

    assert plan.kind == AnalysisPlanKind.QUERY
    assert plan.query == ProposedQuery(
        sql="SELECT SUM(Total) AS total_revenue FROM invoices",
        reasoning_summary="Revenue is stored in invoice totals.",
    )
    llm_request = client.requests[0]
    assert llm_request.response_schema_name == "AnalysisPlan"
    assert llm_request.temperature == 0
    assert llm_request.metadata == {
        "run_id": "run-1",
        "agent": "analysis",
        "operation": "plan",
    }
    assert "Authorized schema:" in llm_request.user_prompt
    assert "invoices" in llm_request.user_prompt


def test_llm_analysis_planner_returns_clarification_plan() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "clarification",
                "sql": None,
                "reasoning_summary": None,
                "message": "Which time period should I use?",
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    plan = planner.plan(request=request(), schema=schema())

    assert plan.kind == AnalysisPlanKind.CLARIFICATION
    assert plan.message == "Which time period should I use?"


def test_llm_analysis_planner_repairs_query_with_error_context() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "query",
                "sql": "SELECT SUM(Total) AS total_revenue FROM invoices",
                "reasoning_summary": "Use the existing Total column.",
                "message": None,
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    repaired = planner.repair_query(
        request=request(),
        schema=schema(),
        failed_query=ProposedQuery(sql="SELECT SUM(amount) FROM invoices"),
        error=DatabaseExecutionError("no such column: amount"),
        attempt=1,
    )

    assert repaired.sql == "SELECT SUM(Total) AS total_revenue FROM invoices"
    llm_request = client.requests[0]
    assert llm_request.metadata["operation"] == "repair_query"
    assert "Failed SQL:" in llm_request.user_prompt
    assert "no such column: amount" in llm_request.user_prompt


def test_llm_analysis_repair_requires_query_plan() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "clarification",
                "sql": None,
                "reasoning_summary": None,
                "message": "Which metric?",
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    with pytest.raises(LLMClientError, match="repair must return a query plan"):
        planner.repair_query(
            request=request(),
            schema=schema(),
            failed_query=ProposedQuery(sql="SELECT bad FROM invoices"),
            error=DatabaseExecutionError("no such column: bad"),
            attempt=1,
        )


def test_llm_analysis_planner_rejects_malformed_query_plan() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "query",
                "sql": None,
                "reasoning_summary": None,
                "message": None,
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    with pytest.raises(LLMClientError, match="require SQL"):
        planner.plan(request=request(), schema=schema())


def test_llm_visualization_planner_returns_chart_spec() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "chart_type": "bar",
                "title": "Revenue by country",
                "x": "BillingCountry",
                "y": ["revenue"],
                "x_label": "Country",
                "y_label": "Revenue",
                "aggregation": None,
                "sort": "descending",
            }
        ]
    )
    planner = LLMVisualizationPlanner(
        client=client,
        metadata={"run_id": "run-1"},
    )

    spec = planner.propose_chart(context=visualization_context())

    assert spec.chart_type == ChartType.BAR
    assert spec.x == "BillingCountry"
    assert spec.y == ["revenue"]
    llm_request = client.requests[0]
    assert llm_request.response_schema_name == "ChartSpec"
    assert llm_request.metadata == {
        "run_id": "run-1",
        "agent": "visualization",
        "operation": "propose_chart",
    }
    assert "Visualization context:" in llm_request.user_prompt
    assert "rows" not in llm_request.user_prompt


def test_llm_visualization_planner_rejects_malformed_chart_spec() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "chart_type": "none",
                "title": "No useful chart",
                "x": "BillingCountry",
            }
        ]
    )
    planner = LLMVisualizationPlanner(client=client)

    with pytest.raises(LLMClientError, match="malformed chart spec"):
        planner.propose_chart(context=visualization_context())
