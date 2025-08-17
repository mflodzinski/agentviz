from dataclasses import dataclass, field

from agentviz.agents import LLMVisualizationPlanner
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
    ChartType,
    VisualizationColumnProfile,
    VisualizationColumnType,
    VisualizationContext,
)
from agentviz.prompts import (
    build_visualization_system_prompt,
    build_visualization_user_prompt,
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


def revenue_visualization_context() -> VisualizationContext:
    return VisualizationContext(
        question="Show total revenue by category.",
        database="sales",
        summary="Query returned category-level total revenue.",
        row_count=3,
        truncated=False,
        columns=[
            VisualizationColumnProfile(
                name="category",
                inferred_type=VisualizationColumnType.CATEGORICAL,
                null_count=0,
                non_null_count=3,
                distinct_count=3,
            ),
            VisualizationColumnProfile(
                name="total_revenue",
                inferred_type=VisualizationColumnType.NUMERIC,
                null_count=0,
                non_null_count=3,
                distinct_count=3,
                numeric_min=50,
                numeric_max=225,
            ),
        ],
    )


def test_evaluation_visualization_llm_turns_row_free_context_into_chart_spec() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "chart_type": "bar",
                "title": "Total Revenue by Category",
                "x": "category",
                "y": ["total_revenue"],
                "x_label": "Category",
                "y_label": "Total Revenue",
                "aggregation": None,
                "sort": "descending",
            }
        ]
    )
    planner = LLMVisualizationPlanner(
        client=client,
        metadata={"run_id": "eval-visualization-1"},
    )

    context = revenue_visualization_context()

    spec = planner.propose_chart(context=context)

    assert spec.chart_type == ChartType.BAR
    assert spec.x == "category"
    assert spec.y == ["total_revenue"]
    llm_request = client.requests[0]
    assert llm_request.response_schema_name == "ChartSpec"
    assert llm_request.metadata == {
        "run_id": "eval-visualization-1",
        "agent": "visualization",
        "operation": "propose_chart",
    }
    assert llm_request.system_prompt == build_visualization_system_prompt()
    assert llm_request.user_prompt == build_visualization_user_prompt(context)
