"""Minimal AnalysisAgent boundary.

The agent is allowed to make semantic choices through its planner, but SQL
execution still goes through the deterministic analysis execution service.
"""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

from agentviz.analysis import AnalysisExecutionService, build_analysis_summary
from agentviz.errors import AgentInputError, DatabaseExecutionError, QueryTimeoutError
from agentviz.models import (
    AnalysisAgentResult,
    AnalysisArtifact,
    AnalysisPlan,
    AnalysisPlanKind,
    AnalysisQueryResult,
    AnalysisRequest,
    DatabaseMetadata,
    ProposedQuery,
)
from agentviz.observability import emit_event


class AnalysisPlanner(Protocol):
    """Semantic planning interface that a real LLM implementation can satisfy."""

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        """Choose whether to query, clarify, or reject an unsupported request."""

    def repair_query(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        failed_query: ProposedQuery,
        error: DatabaseExecutionError,
        attempt: int,
    ) -> ProposedQuery:
        """Repair a proposal after a recoverable database execution error."""


class AnalysisAgent:
    """Small agent coordinator with no direct database access."""

    def __init__(
        self,
        *,
        planner: AnalysisPlanner,
        execution_service: AnalysisExecutionService,
        max_sql_retries: int = 1,
    ) -> None:
        if max_sql_retries < 0:
            raise ValueError("max_sql_retries must be non-negative")

        self._planner = planner
        self._execution_service = execution_service
        self._max_sql_retries = max_sql_retries

    def run(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        run_id: str | None = None,
    ) -> AnalysisAgentResult:
        if schema.name != request.database:
            raise AgentInputError("authorized schema must match requested database")

        emit_event(
            "agent_call.started",
            run_id=run_id,
            agent="analysis",
            database=request.database,
        )
        plan_started = perf_counter()
        plan = self._planner.plan(request=request, schema=schema)
        if not isinstance(plan, AnalysisPlan):
            raise AgentInputError("analysis planner returned malformed plan")
        emit_event(
            "agent_call.completed",
            run_id=run_id,
            agent="analysis",
            database=request.database,
            plan_kind=plan.kind,
            duration_ms=round((perf_counter() - plan_started) * 1000, 3),
        )
        if plan.kind == AnalysisPlanKind.CLARIFICATION:
            return AnalysisAgentResult.needs_clarification(plan.message or "")
        if plan.kind == AnalysisPlanKind.UNSUPPORTED:
            return AnalysisAgentResult.unsupported(plan.message or "")

        if plan.query is None:
            raise AgentInputError("query plan must include a proposed query")

        query_result = self._run_query_with_repair(
            request=request,
            schema=schema,
            proposal=plan.query,
            run_id=run_id,
        )
        summary = build_analysis_summary(
            request=request,
            query_result=query_result,
        )

        return AnalysisAgentResult.completed(
            AnalysisArtifact.from_query_result(
                request=request,
                query_result=query_result,
                summary=summary,
            )
        )

    def _run_query_with_repair(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        proposal: ProposedQuery,
        run_id: str | None,
    ) -> AnalysisQueryResult:
        current_proposal = proposal
        for attempt in range(self._max_sql_retries + 1):
            try:
                return self._execution_service.run_query(
                    user=request.user,
                    database=request.database,
                    sql=current_proposal.sql,
                    run_id=run_id,
                )
            except QueryTimeoutError:
                raise
            except DatabaseExecutionError as exc:
                if attempt >= self._max_sql_retries:
                    raise
                emit_event(
                    "sql_repair.started",
                    run_id=run_id,
                    agent="analysis",
                    database=request.database,
                    attempt=attempt + 1,
                )
                repair_started = perf_counter()
                current_proposal = self._planner.repair_query(
                    request=request,
                    schema=schema,
                    failed_query=current_proposal,
                    error=exc,
                    attempt=attempt + 1,
                )
                if not isinstance(current_proposal, ProposedQuery):
                    raise AgentInputError(
                        "analysis planner returned malformed repaired query"
                    ) from None
                emit_event(
                    "sql_repair.completed",
                    run_id=run_id,
                    agent="analysis",
                    database=request.database,
                    attempt=attempt + 1,
                    duration_ms=round((perf_counter() - repair_started) * 1000, 3),
                )

        raise RuntimeError("unreachable SQL repair loop state")
