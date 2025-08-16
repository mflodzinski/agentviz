"""Provider-neutral protocol for structured LLM calls."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from agentviz.models.core import AgentVizModel


class StructuredLLMRequest(AgentVizModel):
    """One structured-output model request, independent of any provider SDK."""

    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    response_schema_name: str = Field(min_length=1)
    response_schema: dict[str, Any]
    temperature: float = Field(default=0, ge=0, le=2)
    metadata: dict[str, str] = Field(default_factory=dict)


class StructuredLLMResponse(AgentVizModel):
    """Structured content returned by an LLM provider adapter."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    content: dict[str, Any]
    latency_ms: float | None = Field(default=None, ge=0)


class LLMClient(Protocol):
    """Minimal behavior required by future LLM-backed planners."""

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        """Return provider-normalized structured output for a request."""
