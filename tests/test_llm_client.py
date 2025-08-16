from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from agentviz.llm import LLMClient, StructuredLLMRequest, StructuredLLMResponse


@dataclass
class FakeLLMClient:
    response: StructuredLLMResponse
    requests: list[StructuredLLMRequest] = field(default_factory=list)

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        self.requests.append(request)
        return self.response


def test_structured_llm_request_serializes_without_provider_details() -> None:
    request = StructuredLLMRequest(
        system_prompt="Return a query plan.",
        user_prompt="Show revenue by country.",
        response_schema_name="AnalysisPlan",
        response_schema={"type": "object"},
        metadata={"run_id": "20260816_123456_a1b2c3d4"},
    )

    restored = StructuredLLMRequest.model_validate_json(request.model_dump_json())

    assert restored == request


def test_structured_llm_request_validates_temperature_range() -> None:
    with pytest.raises(ValidationError, match="temperature"):
        StructuredLLMRequest(
            system_prompt="Return a query plan.",
            user_prompt="Show revenue by country.",
            response_schema_name="AnalysisPlan",
            response_schema={"type": "object"},
            temperature=3,
        )


def test_fake_client_satisfies_llm_client_protocol() -> None:
    response = StructuredLLMResponse(
        provider="test",
        model="fake-model",
        content={"kind": "unsupported", "message": "No matching data."},
        latency_ms=1.5,
    )
    client: LLMClient = FakeLLMClient(response=response)
    request = StructuredLLMRequest(
        system_prompt="Return a query plan.",
        user_prompt="Show refunds.",
        response_schema_name="AnalysisPlan",
        response_schema={"type": "object"},
    )

    result = client.complete_structured(request)

    assert result == response
    assert isinstance(client, FakeLLMClient)
    assert client.requests == [request]
