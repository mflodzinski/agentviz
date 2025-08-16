"""Deterministic application workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Protocol

from agentviz.agents import AnalysisAgent, VisualizationAgent
from agentviz.analysis import validate_request_safety
from agentviz.auth import AuthorizedSchemaService
from agentviz.errors import ChartRenderingError, ChartValidationError
from agentviz.models import (
    AnalysisAgentStatus,
    AnalysisArtifact,
    AnalysisRequest,
    ApplicationRunResult,
    ChartSpec,
    ChartType,
)
from agentviz.observability import emit_event
from agentviz.runs import generate_run_id


class ChartRendererProtocol(Protocol):
    """Minimal renderer behavior required by the application orchestrator."""

    def render(
        self,
        *,
        artifact: AnalysisArtifact,
        spec: ChartSpec,
        output_path: Path,
    ) -> Path:
        """Render a chart spec for an artifact and return the written path."""


class ApplicationOrchestrator:
    """Coordinate deterministic services and the two agent boundaries."""

    def __init__(
        self,
        *,
        schema_service: AuthorizedSchemaService,
        analysis_agent: AnalysisAgent,
        visualization_agent: VisualizationAgent,
        renderer: ChartRendererProtocol,
    ) -> None:
        self._schema_service = schema_service
        self._analysis_agent = analysis_agent
        self._visualization_agent = visualization_agent
        self._renderer = renderer

    def run(
        self,
        *,
        request: AnalysisRequest,
        chart_output_path: Path | None = None,
        run_id: str | None = None,
    ) -> ApplicationRunResult:
        resolved_run_id = run_id or generate_run_id()
        emit_event(
            "workflow.started",
            run_id=resolved_run_id,
            user=request.user.username,
            database=request.database,
            include_visualization=request.include_visualization,
        )
        validate_request_safety(request)
        schema_started = perf_counter()
        emit_event(
            "schema_access.started",
            run_id=resolved_run_id,
            user=request.user.username,
            database=request.database,
        )
        try:
            schema = self._schema_service.get_schema(request.user, request.database)
        except Exception as exc:
            emit_event(
                "schema_access.failed",
                run_id=resolved_run_id,
                user=request.user.username,
                database=request.database,
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - schema_started) * 1000, 3),
            )
            raise
        emit_event(
            "schema_access.completed",
            run_id=resolved_run_id,
            user=request.user.username,
            database=request.database,
            table_count=len(schema.tables),
            duration_ms=round((perf_counter() - schema_started) * 1000, 3),
        )
        analysis_started = perf_counter()
        try:
            analysis = self._analysis_agent.run(
                request=request,
                schema=schema,
                run_id=resolved_run_id,
            )
        except Exception as exc:
            emit_event(
                "analysis.failed",
                run_id=resolved_run_id,
                user=request.user.username,
                database=request.database,
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - analysis_started) * 1000, 3),
            )
            raise
        emit_event(
            "analysis.completed",
            run_id=resolved_run_id,
            user=request.user.username,
            database=request.database,
            status=analysis.status,
            duration_ms=round((perf_counter() - analysis_started) * 1000, 3),
        )
        if analysis.status != AnalysisAgentStatus.COMPLETED:
            return ApplicationRunResult(run_id=resolved_run_id, analysis=analysis)

        if not request.include_visualization:
            return ApplicationRunResult(run_id=resolved_run_id, analysis=analysis)

        if analysis.artifact is None:
            raise RuntimeError("completed analysis result must include an artifact")

        if _is_single_value_result(analysis.artifact):
            chart_spec = ChartSpec(
                chart_type=ChartType.NONE,
                title="Single value result does not need a chart",
            )
            emit_event(
                "visualization_agent.skipped",
                run_id=resolved_run_id,
                database=request.database,
                reason="single_value_result",
            )
            return ApplicationRunResult(
                run_id=resolved_run_id,
                analysis=analysis,
                chart_spec=chart_spec,
            )

        try:
            emit_event(
                "visualization_agent.started",
                run_id=resolved_run_id,
                database=request.database,
            )
            visualization_started = perf_counter()
            chart_spec = self._visualization_agent.run(artifact=analysis.artifact)
            emit_event(
                "visualization_agent.completed",
                run_id=resolved_run_id,
                database=request.database,
                chart_type=chart_spec.chart_type,
                duration_ms=round(
                    (perf_counter() - visualization_started) * 1000,
                    3,
                ),
            )
        except (ChartRenderingError, ChartValidationError) as exc:
            emit_event(
                "visualization_agent.failed",
                run_id=resolved_run_id,
                database=request.database,
                error_type=type(exc).__name__,
            )
            return ApplicationRunResult(
                run_id=resolved_run_id,
                analysis=analysis,
                visualization_warning=str(exc),
            )

        if chart_spec.chart_type == ChartType.NONE:
            return ApplicationRunResult(
                run_id=resolved_run_id,
                analysis=analysis,
                chart_spec=chart_spec,
            )

        if chart_output_path is None:
            raise ValueError("chart_output_path is required when rendering a chart")

        try:
            emit_event(
                "rendering.started",
                run_id=resolved_run_id,
                database=request.database,
                chart_type=chart_spec.chart_type,
            )
            rendering_started = perf_counter()
            chart_path = self._renderer.render(
                artifact=analysis.artifact,
                spec=chart_spec,
                output_path=chart_output_path,
            )
            emit_event(
                "rendering.completed",
                run_id=resolved_run_id,
                database=request.database,
                chart_type=chart_spec.chart_type,
                chart_path=chart_path.as_posix(),
                duration_ms=round((perf_counter() - rendering_started) * 1000, 3),
            )
        except (ChartRenderingError, ChartValidationError) as exc:
            emit_event(
                "rendering.failed",
                run_id=resolved_run_id,
                database=request.database,
                chart_type=chart_spec.chart_type,
                error_type=type(exc).__name__,
            )
            return ApplicationRunResult(
                run_id=resolved_run_id,
                analysis=analysis,
                chart_spec=chart_spec,
                visualization_warning=str(exc),
            )

        return ApplicationRunResult(
            run_id=resolved_run_id,
            analysis=analysis,
            chart_spec=chart_spec,
            chart_path=chart_path,
        )


def _is_single_value_result(artifact: AnalysisArtifact) -> bool:
    return artifact.row_count == 1 and len(artifact.columns) == 1
