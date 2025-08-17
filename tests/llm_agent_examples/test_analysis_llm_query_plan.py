from dataclasses import dataclass, field

from agentviz.agents import LLMAnalysisPlanner
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
    AnalysisPlanKind,
    AnalysisRequest,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    ProposedQuery,
    TableMetadata,
    UserIdentity,
)
from agentviz.prompts import build_analysis_system_prompt, build_analysis_user_prompt


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


def sales_request() -> AnalysisRequest:
    return AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question="Which category has the largest total revenue?",
        include_visualization=True,
    )


def sales_schema() -> DatabaseMetadata:
    return DatabaseMetadata(
        name="sales",
        backend=DatabaseBackend.SQLITE,
        tables=[
            TableMetadata(
                name="sales",
                columns=[
                    ColumnMetadata(name="sale_id", data_type="INTEGER"),
                    ColumnMetadata(name="category", data_type="TEXT"),
                    ColumnMetadata(name="revenue", data_type="REAL"),
                ],
            )
        ],
    )


def test_evaluation_analysis_llm_turns_prompt_and_schema_into_query_plan() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "query",
                "sql": (
                    "SELECT category, SUM(revenue) AS total_revenue "
                    "FROM sales GROUP BY category ORDER BY total_revenue DESC"
                ),
                "reasoning_summary": (
                    "The sales table has category and revenue columns."
                ),
                "message": None,
            }
        ]
    )
    planner = LLMAnalysisPlanner(
        client=client,
        metadata={"run_id": "eval-analysis-1"},
    )

    request = sales_request()
    schema = sales_schema()

    plan = planner.plan(request=request, schema=schema)

    assert plan.kind == AnalysisPlanKind.QUERY
    assert plan.query == ProposedQuery(
        sql=(
            "SELECT category, SUM(revenue) AS total_revenue "
            "FROM sales GROUP BY category ORDER BY total_revenue DESC"
        ),
        reasoning_summary="The sales table has category and revenue columns.",
    )
    llm_request = client.requests[0]
    assert llm_request.response_schema_name == "AnalysisPlan"
    assert llm_request.metadata == {
        "run_id": "eval-analysis-1",
        "agent": "analysis",
        "operation": "plan",
    }
    assert llm_request.system_prompt == build_analysis_system_prompt()
    assert llm_request.user_prompt == build_analysis_user_prompt(
        request=request,
        schema=schema,
    )
