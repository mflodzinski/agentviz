"""Opt-in recording for provider-neutral LLM inputs and outputs."""

from __future__ import annotations

import json
from pathlib import Path

from agentviz.llm.client import (
    LLMClient,
    StructuredLLMRequest,
    StructuredLLMResponse,
)


class LLMIORecorder:
    """Collect structured LLM requests and responses for debugging."""

    def __init__(self) -> None:
        self._calls: list[dict] = []

    def record(
        self,
        *,
        request: StructuredLLMRequest,
        response: StructuredLLMResponse,
    ) -> None:
        self._calls.append(
            {
                "index": len(self._calls) + 1,
                "agent": request.metadata.get("agent"),
                "operation": request.metadata.get("operation"),
                "response_kind": _response_kind(response),
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        )

    def model_dump(self) -> dict:
        return {"calls": self._calls}


class RecordingLLMClient:
    """LLM client wrapper that records successful structured calls."""

    def __init__(self, client: LLMClient, recorder: LLMIORecorder) -> None:
        self._client = client
        self._recorder = recorder

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        response = self._client.complete_structured(request)
        self._recorder.record(request=request, response=response)
        return response


def write_llm_io_trace(recorder: LLMIORecorder, output_path: Path) -> Path:
    """Write readable JSON containing opt-in LLM call inputs and outputs."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(recorder.model_dump(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _response_kind(response: StructuredLLMResponse) -> str | None:
    kind = response.content.get("kind")
    return kind if isinstance(kind, str) else None
