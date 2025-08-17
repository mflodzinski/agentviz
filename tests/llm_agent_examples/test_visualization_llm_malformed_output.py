from dataclasses import dataclass, field

import pytest

from agentviz.agents import LLMVisualizationPlanner
from agentviz.errors import LLMClientError
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse
from agentviz.models import (
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


def test_evaluation_visualization_llm_rejects_malformed_chart_spec() -> None:
    client = FakeLLMClient(
        responses=[
            {
                "chart_type": "bar",
                "title": "Broken chart",
                "x": "category",
                "y": "total_revenue",
                "x_label": "Category",
                "y_label": "Revenue",
                "aggregation": None,
                "sort": None,
            }
        ]
    )
    planner = LLMVisualizationPlanner(client=client)

    context = revenue_visualization_context()

    with pytest.raises(LLMClientError, match="malformed chart spec"):
        planner.propose_chart(context=context)

    llm_request = client.requests[0]
    assert llm_request.metadata == {
        "agent": "visualization",
        "operation": "propose_chart",
    }
    assert llm_request.system_prompt == build_visualization_system_prompt()
    assert llm_request.user_prompt == build_visualization_user_prompt(context)
