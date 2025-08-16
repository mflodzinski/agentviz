"""LLM-backed planners that satisfy the existing agent protocols."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from agentviz.errors import DatabaseExecutionError, LLMClientError
from agentviz.llm import LLMClient, StructuredLLMRequest
from agentviz.models import (
    AnalysisPlan,
    AnalysisPlanKind,
    AnalysisRequest,
    ChartSpec,
    DatabaseMetadata,
    ProposedQuery,
    VisualizationContext,
)
from agentviz.prompts import (
    DEFAULT_MAX_COLUMNS_PER_TABLE,
    DEFAULT_MAX_TABLES,
    analysis_plan_response_schema,
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    build_schema_context,
    build_visualization_system_prompt,
    build_visualization_user_prompt,
    chart_spec_response_schema,
)


class LLMAnalysisPlanner:
    """Analysis planner implemented through provider-neutral structured LLM calls."""

    def __init__(
        self,
        *,
        client: LLMClient,
        temperature: float = 0,
        max_tables: int = DEFAULT_MAX_TABLES,
        max_columns_per_table: int = DEFAULT_MAX_COLUMNS_PER_TABLE,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        if max_tables < 1:
            raise ValueError("max_tables must be at least 1")
        if max_columns_per_table < 1:
            raise ValueError("max_columns_per_table must be at least 1")

        self._client = client
        self._temperature = temperature
        self._max_tables = max_tables
        self._max_columns_per_table = max_columns_per_table
        self._metadata = dict(metadata or {})

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        response = self._client.complete_structured(
            StructuredLLMRequest(
                system_prompt=build_analysis_system_prompt(),
                user_prompt=build_analysis_user_prompt(
                    request=request,
                    schema=schema,
                    max_tables=self._max_tables,
                    max_columns_per_table=self._max_columns_per_table,
                ),
                response_schema_name="AnalysisPlan",
                response_schema=analysis_plan_response_schema(),
                temperature=self._temperature,
                metadata={**self._metadata, "agent": "analysis", "operation": "plan"},
            )
        )
        return _analysis_plan_from_content(response.content)

    def repair_query(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        failed_query: ProposedQuery,
        error: DatabaseExecutionError,
        attempt: int,
    ) -> ProposedQuery:
        response = self._client.complete_structured(
            StructuredLLMRequest(
                system_prompt=build_analysis_system_prompt(),
                user_prompt=_build_repair_user_prompt(
                    request=request,
                    schema=schema,
                    failed_query=failed_query,
                    error=error,
                    attempt=attempt,
                    max_tables=self._max_tables,
                    max_columns_per_table=self._max_columns_per_table,
                ),
                response_schema_name="AnalysisPlan",
                response_schema=analysis_plan_response_schema(),
                temperature=self._temperature,
                metadata={
                    **self._metadata,
                    "agent": "analysis",
                    "operation": "repair_query",
                    "attempt": str(attempt),
                },
            )
        )
        plan = _analysis_plan_from_content(response.content)
        if plan.kind != AnalysisPlanKind.QUERY or plan.query is None:
            raise LLMClientError("SQL repair must return a query plan")
        return plan.query


class LLMVisualizationPlanner:
    """Visualization planner implemented through structured LLM chart specs."""

    def __init__(
        self,
        *,
        client: LLMClient,
        temperature: float = 0,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self._client = client
        self._temperature = temperature
        self._metadata = dict(metadata or {})

    def propose_chart(self, *, context: VisualizationContext) -> ChartSpec:
        response = self._client.complete_structured(
            StructuredLLMRequest(
                system_prompt=build_visualization_system_prompt(),
                user_prompt=build_visualization_user_prompt(context),
                response_schema_name="ChartSpec",
                response_schema=chart_spec_response_schema(),
                temperature=self._temperature,
                metadata={
                    **self._metadata,
                    "agent": "visualization",
                    "operation": "propose_chart",
                },
            )
        )
        try:
            return ChartSpec.model_validate(response.content)
        except ValidationError as exc:
            raise LLMClientError("LLM returned malformed chart spec") from exc


def _analysis_plan_from_content(content: Mapping[str, Any]) -> AnalysisPlan:
    kind = content.get("kind")
    if kind == AnalysisPlanKind.QUERY:
        return _query_plan_from_content(content)
    if kind == AnalysisPlanKind.CLARIFICATION:
        return _message_plan_from_content(content, AnalysisPlan.clarification)
    if kind == AnalysisPlanKind.UNSUPPORTED:
        return _message_plan_from_content(content, AnalysisPlan.unsupported)

    raise LLMClientError("LLM returned unknown analysis plan kind")


def _query_plan_from_content(content: Mapping[str, Any]) -> AnalysisPlan:
    sql = content.get("sql")
    reasoning_summary = content.get("reasoning_summary")
    if not isinstance(sql, str):
        raise LLMClientError("query analysis plans require SQL")
    if reasoning_summary is not None and not isinstance(reasoning_summary, str):
        raise LLMClientError("query reasoning summary must be a string or null")

    try:
        return AnalysisPlan.query_plan(
            ProposedQuery(sql=sql, reasoning_summary=reasoning_summary)
        )
    except ValidationError as exc:
        raise LLMClientError("LLM returned malformed query plan") from exc


def _message_plan_from_content(
    content: Mapping[str, Any],
    factory: Callable[[str], AnalysisPlan],
) -> AnalysisPlan:
    message = content.get("message")
    if not isinstance(message, str):
        raise LLMClientError("non-query analysis plans require a message")

    try:
        return factory(message)
    except ValidationError as exc:
        raise LLMClientError("LLM returned malformed non-query plan") from exc


def _build_repair_user_prompt(
    *,
    request: AnalysisRequest,
    schema: DatabaseMetadata,
    failed_query: ProposedQuery,
    error: DatabaseExecutionError,
    attempt: int,
    max_tables: int,
    max_columns_per_table: int,
) -> str:
    return "\n\n".join(
        [
            f"User question:\n{request.question}",
            "Authorized schema:\n"
            + build_schema_context(
                schema,
                max_tables=max_tables,
                max_columns_per_table=max_columns_per_table,
            ),
            f"Failed SQL:\n{failed_query.sql}",
            f"Database error on repair attempt {attempt}:\n{error}",
            "Return a corrected query plan only.",
        ]
    )
