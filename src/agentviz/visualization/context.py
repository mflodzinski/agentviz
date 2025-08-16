"""Build compact, row-free context for visualization planning."""

from __future__ import annotations

from agentviz.models import (
    AnalysisArtifact,
    ScalarValue,
    VisualizationColumnProfile,
    VisualizationColumnType,
    VisualizationContext,
)
from agentviz.visualization.temporal import is_temporal_value


def build_visualization_context(artifact: AnalysisArtifact) -> VisualizationContext:
    """Create visualization-planning context without copying row values."""

    return VisualizationContext(
        question=artifact.request.question,
        database=artifact.database,
        summary=artifact.summary,
        row_count=artifact.row_count,
        truncated=artifact.truncated,
        columns=[_profile_column(artifact, column) for column in artifact.columns],
    )


def _profile_column(
    artifact: AnalysisArtifact,
    column: str,
) -> VisualizationColumnProfile:
    values = [row[column] for row in artifact.rows]
    non_null_values = [value for value in values if value is not None]
    inferred_type = _infer_column_type(non_null_values)
    numeric_values = [
        float(value)
        for value in non_null_values
        if isinstance(value, int | float) and not isinstance(value, bool)
    ]

    return VisualizationColumnProfile(
        name=column,
        inferred_type=inferred_type,
        null_count=len(values) - len(non_null_values),
        non_null_count=len(non_null_values),
        distinct_count=len(set(non_null_values)),
        numeric_min=min(numeric_values) if numeric_values else None,
        numeric_max=max(numeric_values) if numeric_values else None,
    )


def _infer_column_type(values: list[ScalarValue]) -> VisualizationColumnType:
    if not values:
        return VisualizationColumnType.EMPTY
    if all(isinstance(value, bool) for value in values):
        return VisualizationColumnType.BOOLEAN
    if all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in values
    ):
        return VisualizationColumnType.NUMERIC
    if all(_is_temporal(value) for value in values):
        return VisualizationColumnType.TEMPORAL
    return VisualizationColumnType.CATEGORICAL


def _is_temporal(value: ScalarValue) -> bool:
    return is_temporal_value(value)
