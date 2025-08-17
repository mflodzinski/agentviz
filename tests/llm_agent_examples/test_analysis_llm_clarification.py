from dataclasses import dataclass, field

from agentviz.agents import LLMAnalysisPlanner
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
    AnalysisPlanKind,
    AnalysisRequest,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
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


def sales_request(question: str) -> AnalysisRequest:
    return AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question=question,
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


def test_evaluation_analysis_llm_can_return_clarification_for_ambiguous_prompt(
) -> None:
    client = FakeLLMClient(
        responses=[
            {
                "kind": "clarification",
                "sql": None,
                "reasoning_summary": None,
                "message": "Which revenue time period should I use?",
            }
        ]
    )
    planner = LLMAnalysisPlanner(client=client)

    request = sales_request("Show revenue for the relevant period.")
    schema = sales_schema()

    plan = planner.plan(request=request, schema=schema)

    assert plan.kind == AnalysisPlanKind.CLARIFICATION
    assert plan.query is None
    assert plan.message == "Which revenue time period should I use?"
    llm_request = client.requests[0]
    assert llm_request.system_prompt == build_analysis_system_prompt()
    assert llm_request.user_prompt == build_analysis_user_prompt(
        request=request,
        schema=schema,
    )
