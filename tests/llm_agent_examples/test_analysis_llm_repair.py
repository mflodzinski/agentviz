from dataclasses import dataclass, field

from agentviz.agents import LLMAnalysisPlanner
from agentviz.errors import DatabaseExecutionError
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
    AnalysisRequest,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    ProposedQuery,
    TableMetadata,
    UserIdentity,
)
from agentviz.prompts import build_analysis_system_prompt, build_schema_context


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
                    ColumnMetadata(name="category", data_type="TEXT"),
                    ColumnMetadata(name="revenue", data_type="REAL"),
                ],
            )
        ],
    )


def test_evaluation_analysis_llm_repair_prompt_includes_failed_sql_and_error() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "query",
                "sql": (
                    "SELECT category, SUM(revenue) AS total_revenue "
                    "FROM sales GROUP BY category"
                ),
                "reasoning_summary": "Use the existing revenue column.",
                "message": None,
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    request = sales_request()
    schema = sales_schema()
    failed_query = ProposedQuery(sql="SELECT category, SUM(amount) FROM sales")
    error = DatabaseExecutionError("no such column: amount")

    repaired = planner.repair_query(
        request=request,
        schema=schema,
        failed_query=failed_query,
        error=error,
        attempt=1,
    )

    assert repaired == ProposedQuery(
        sql=(
            "SELECT category, SUM(revenue) AS total_revenue "
            "FROM sales GROUP BY category"
        ),
        reasoning_summary="Use the existing revenue column.",
    )
    llm_request = client.requests[0]
    assert llm_request.metadata == {
        "agent": "analysis",
        "operation": "repair_query",
        "attempt": "1",
    }
    assert llm_request.system_prompt == build_analysis_system_prompt()
    assert llm_request.user_prompt == "\n\n".join(
        [
            f"User question:\n{request.question}",
            "Authorized schema:\n" + build_schema_context(schema),
            f"Failed SQL:\n{failed_query.sql}",
            f"Database error on repair attempt 1:\n{error}",
            "Return a corrected query plan only.",
        ]
    )
