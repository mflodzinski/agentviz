"""OpenAI implementation of the provider-neutral LLM client protocol."""

from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter
from typing import Any

from agentviz.config import LLMSettings
from agentviz.errors import LLMClientError
from agentviz.llm.client import StructuredLLMRequest, StructuredLLMResponse

type OpenAIClientFactory = Callable[..., Any]


class OpenAIClient:
    """Structured-output client using OpenAI's Responses API."""

    def __init__(
        self,
        *,
        settings: LLMSettings,
        api_key: str,
        client_factory: OpenAIClientFactory | None = None,
    ) -> None:
        if settings.provider != "openai":
            raise ValueError("OpenAIClient requires provider='openai'")

        self._settings = settings
        self._client = _create_client(
            api_key=api_key,
            timeout_seconds=settings.timeout_seconds,
            client_factory=client_factory,
        )

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        started = perf_counter()
        try:
            response = self._client.responses.create(
                **_structured_request_payload(
                    settings=self._settings,
                    request=request,
                )
            )
        except Exception as exc:
            raise LLMClientError(
                "OpenAI structured completion failed: "
                f"{_format_provider_error(exc)}"
            ) from exc

        content = _parse_output_text(_response_output_text(response))
        return StructuredLLMResponse(
            provider=self._settings.provider,
            model=self._settings.model,
            content=content,
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )


def _create_client(
    *,
    api_key: str,
    timeout_seconds: int,
    client_factory: OpenAIClientFactory | None,
) -> Any:
    if client_factory is None:
        try:
            from openai import OpenAI as client_factory
        except ImportError as exc:
            raise LLMClientError(
                "OpenAI SDK is not installed. Install the 'openai' package."
            ) from exc

    try:
        return client_factory(api_key=api_key, timeout=timeout_seconds)
    except Exception as exc:
        raise LLMClientError(
            f"OpenAI client initialization failed: {type(exc).__name__}"
        ) from exc


def _structured_request_payload(
    *,
    settings: LLMSettings,
    request: StructuredLLMRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.model,
        "input": [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": request.response_schema_name,
                "schema": request.response_schema,
                "strict": True,
            }
        },
        "metadata": request.metadata or None,
    }
    if _supports_temperature(settings.model):
        payload["temperature"] = request.temperature
    return payload


def _supports_temperature(model: str) -> bool:
    return not model.startswith("gpt-5")


def _response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise LLMClientError("OpenAI response did not include output_text")
    return output_text


def _parse_output_text(output_text: str) -> dict[str, Any]:
    try:
        content = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise LLMClientError("OpenAI response output_text was not valid JSON") from exc

    if not isinstance(content, dict):
        raise LLMClientError("OpenAI structured response must be a JSON object")
    return content


def _format_provider_error(exc: Exception) -> str:
    parts = [type(exc).__name__]
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        parts.append(f"status={status_code}")

    code = getattr(exc, "code", None)
    if code:
        parts.append(f"code={code}")

    message = getattr(exc, "message", None) or str(exc)
    if message:
        parts.append(str(message))

    return ": ".join(parts)
