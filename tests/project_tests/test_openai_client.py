from dataclasses import dataclass, field

import pytest

from agentviz.config import LLMSettings
from agentviz.errors import LLMClientError
from agentviz.llm import OpenAIClient, StructuredLLMRequest


@dataclass
class FakeOpenAIResponse:
    output_text: str


@dataclass
class FakeResponses:
    output_text: str = '{"kind": "unsupported", "message": "No matching data."}'
    calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeOpenAIResponse(output_text=self.output_text)


class FakePermissionDeniedError(Exception):
    status_code = 403
    code = "model_not_found"
    message = "Project does not have access to this model."


@dataclass
class FailingResponses:
    calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise FakePermissionDeniedError


@dataclass
class FakeSDKClient:
    responses: FakeResponses | FailingResponses


@dataclass
class FakeOpenAIClientFactory:
    responses: FakeResponses = field(default_factory=FakeResponses)
    calls: list[dict] = field(default_factory=list)

    def __call__(self, **kwargs) -> FakeSDKClient:
        self.calls.append(kwargs)
        return FakeSDKClient(responses=self.responses)


def structured_request() -> StructuredLLMRequest:
    return StructuredLLMRequest(
        system_prompt="Return an analysis plan.",
        user_prompt="Show revenue by country.",
        response_schema_name="AnalysisPlan",
        response_schema={
            "type": "object",
            "properties": {"kind": {"type": "string"}},
            "required": ["kind"],
            "additionalProperties": False,
        },
        temperature=0,
        metadata={"run_id": "20260816_123456_a1b2c3d4"},
    )


def test_openai_client_sends_structured_responses_request() -> None:
    factory = FakeOpenAIClientFactory()
    client = OpenAIClient(
        settings=LLMSettings(provider="openai", model="gpt-4.1-mini"),
        api_key="test-key",
        client_factory=factory,
    )

    response = client.complete_structured(structured_request())

    assert response.provider == "openai"
    assert response.model == "gpt-4.1-mini"
    assert response.content == {
        "kind": "unsupported",
        "message": "No matching data.",
    }
    assert response.latency_ms is not None
    assert factory.calls == [{"api_key": "test-key", "timeout": 30}]
    request_payload = factory.responses.calls[0]
    assert request_payload["model"] == "gpt-4.1-mini"
    assert request_payload["input"] == [
        {"role": "system", "content": "Return an analysis plan."},
        {"role": "user", "content": "Show revenue by country."},
    ]
    assert request_payload["text"]["format"] == {
        "type": "json_schema",
        "name": "AnalysisPlan",
        "schema": structured_request().response_schema,
        "strict": True,
    }
    assert request_payload["temperature"] == 0
    assert request_payload["metadata"] == {
        "run_id": "20260816_123456_a1b2c3d4"
    }


def test_openai_client_omits_temperature_for_gpt_5_models() -> None:
    factory = FakeOpenAIClientFactory()
    client = OpenAIClient(
        settings=LLMSettings(provider="openai", model="gpt-5"),
        api_key="test-key",
        client_factory=factory,
    )

    response = client.complete_structured(structured_request())

    assert response.model == "gpt-5"
    request_payload = factory.responses.calls[0]
    assert request_payload["model"] == "gpt-5"
    assert "temperature" not in request_payload


def test_openai_client_requires_openai_provider() -> None:
    with pytest.raises(ValueError, match="provider='openai'"):
        OpenAIClient(
            settings=LLMSettings(provider="anthropic", model="claude-example"),
            api_key="test-key",
            client_factory=FakeOpenAIClientFactory(),
        )


def test_openai_client_rejects_non_json_output() -> None:
    factory = FakeOpenAIClientFactory(responses=FakeResponses(output_text="not json"))
    client = OpenAIClient(
        settings=LLMSettings(provider="openai", model="gpt-4.1-mini"),
        api_key="test-key",
        client_factory=factory,
    )

    with pytest.raises(LLMClientError, match="valid JSON"):
        client.complete_structured(structured_request())


def test_openai_client_rejects_non_object_json_output() -> None:
    factory = FakeOpenAIClientFactory(responses=FakeResponses(output_text='["bad"]'))
    client = OpenAIClient(
        settings=LLMSettings(provider="openai", model="gpt-4.1-mini"),
        api_key="test-key",
        client_factory=factory,
    )

    with pytest.raises(LLMClientError, match="JSON object"):
        client.complete_structured(structured_request())


def test_openai_client_includes_request_error_details() -> None:
    factory = FakeOpenAIClientFactory(responses=FailingResponses())
    client = OpenAIClient(
        settings=LLMSettings(provider="openai", model="gpt-4.1-mini"),
        api_key="test-key",
        client_factory=factory,
    )

    with pytest.raises(LLMClientError) as exc_info:
        client.complete_structured(structured_request())

    message = str(exc_info.value)
    assert "FakePermissionDeniedError" in message
    assert "status=403" in message
    assert "code=model_not_found" in message
    assert "does not have access" in message


def test_openai_client_wraps_provider_errors() -> None:
    def failing_factory(**kwargs):
        raise RuntimeError("boom")

    with pytest.raises(LLMClientError, match="initialization failed"):
        OpenAIClient(
            settings=LLMSettings(provider="openai", model="gpt-4.1-mini"),
            api_key="test-key",
            client_factory=failing_factory,
        )
