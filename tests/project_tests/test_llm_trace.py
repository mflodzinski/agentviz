from agentviz.llm import (
    LLMIORecorder,
    RecordingLLMClient,
    StructuredLLMRequest,
    StructuredLLMResponse,
    write_llm_io_trace,
)


class FakeLLMClient:
    def __init__(self, response: StructuredLLMResponse) -> None:
        self.response = response
        self.requests: list[StructuredLLMRequest] = []

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        self.requests.append(request)
        return self.response


def test_recording_llm_client_records_request_and_response() -> None:
    request = StructuredLLMRequest(
        system_prompt="Return a query plan.",
        user_prompt="Show revenue by country.",
        response_schema_name="AnalysisPlan",
        response_schema={"type": "object"},
        metadata={"agent": "analysis", "operation": "plan"},
    )
    response = StructuredLLMResponse(
        provider="test",
        model="fake-model",
        content={
            "kind": "query",
            "sql": "SELECT 1",
            "reasoning_summary": "Use a constant.",
            "message": None,
        },
    )
    recorder = LLMIORecorder()
    client = RecordingLLMClient(FakeLLMClient(response), recorder)

    result = client.complete_structured(request)

    assert result == response
    assert recorder.model_dump() == {
        "calls": [
            {
                "index": 1,
                "agent": "analysis",
                "operation": "plan",
                "response_kind": "query",
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        ]
    }


def test_write_llm_io_trace_writes_readable_json(tmp_path) -> None:
    request = StructuredLLMRequest(
        system_prompt="Return a chart spec.",
        user_prompt="Visualization context: {}",
        response_schema_name="ChartSpec",
        response_schema={"type": "object"},
        metadata={"agent": "visualization", "operation": "propose_chart"},
    )
    response = StructuredLLMResponse(
        provider="test",
        model="fake-model",
        content={"chart_type": "none", "title": "No chart", "y": []},
    )
    recorder = LLMIORecorder()
    recorder.record(request=request, response=response)

    output_path = write_llm_io_trace(recorder, tmp_path / "trace" / "llm_io.json")

    assert output_path.read_text(encoding="utf-8").startswith('{\n  "calls": [')
