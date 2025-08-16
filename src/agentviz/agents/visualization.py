"""Minimal VisualizationAgent boundary."""

from __future__ import annotations

from typing import Protocol

from agentviz.models import AnalysisArtifact, ChartSpec, VisualizationContext
from agentviz.visualization import ChartValidator, build_visualization_context


class VisualizationPlanner(Protocol):
    """Semantic chart-selection interface a real LLM implementation can satisfy."""

    def propose_chart(self, *, context: VisualizationContext) -> ChartSpec:
        """Choose a chart intent from compact, row-free analysis context."""


class VisualizationAgent:
    """Small visualization coordinator with no rendering or database access."""

    def __init__(
        self,
        *,
        planner: VisualizationPlanner,
        validator: ChartValidator | None = None,
    ) -> None:
        self._planner = planner
        self._validator = validator or ChartValidator()

    def run(self, *, artifact: AnalysisArtifact) -> ChartSpec:
        context = build_visualization_context(artifact)
        spec = self._planner.propose_chart(context=context)
        return self._validator.validate(spec=spec, artifact=artifact)
