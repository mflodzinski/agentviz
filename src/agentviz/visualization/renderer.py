"""Deterministic Matplotlib renderer for validated chart specifications."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir()) / "agentviz-matplotlib"))

from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure

from agentviz.errors import ChartRenderingError
from agentviz.models import AnalysisArtifact, ChartSpec, ChartType, ScalarValue
from agentviz.visualization.company_style import (
    DEFAULT_COMPANY_STYLE,
    CompanyChartStyle,
)
from agentviz.visualization.temporal import parse_temporal_value
from agentviz.visualization.validator import ChartValidator


class ChartRenderer:
    """Render validated chart specs without LLM involvement."""

    def __init__(
        self,
        *,
        validator: ChartValidator | None = None,
        style: CompanyChartStyle = DEFAULT_COMPANY_STYLE,
    ) -> None:
        self._validator = validator or ChartValidator()
        self._style = style

    def render(
        self,
        *,
        artifact: AnalysisArtifact,
        spec: ChartSpec,
        output_path: Path,
    ) -> Path:
        validated_spec = self._validator.validate(spec=spec, artifact=artifact)
        if validated_spec.chart_type not in {
            ChartType.BAR,
            ChartType.LINE,
            ChartType.SCATTER,
        }:
            raise ChartRenderingError(
                f"rendering is not implemented for chart type: "
                f"{validated_spec.chart_type}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure = Figure(figsize=self._style.figure_size, dpi=self._style.dpi)
        FigureCanvas(figure)
        axes = figure.subplots()

        match validated_spec.chart_type:
            case ChartType.BAR:
                _render_bar(axes, artifact, validated_spec, self._style)
            case ChartType.LINE:
                _render_line(axes, artifact, validated_spec, self._style)
            case ChartType.SCATTER:
                _render_scatter(axes, artifact, validated_spec, self._style)
            case _:
                raise ChartRenderingError(
                    f"rendering is not implemented for chart type: "
                    f"{validated_spec.chart_type}"
                )

        _apply_axes_style(axes, validated_spec, self._style)
        figure.tight_layout()
        figure.savefig(output_path)
        return output_path


def _apply_axes_style(
    axes,
    spec: ChartSpec,
    style: CompanyChartStyle,
) -> None:
    axes.set_title(spec.title, fontsize=style.title_size)
    if spec.x_label or spec.x:
        axes.set_xlabel(spec.x_label or spec.x or "", fontsize=style.label_size)
    if spec.y_label or spec.y:
        axes.set_ylabel(spec.y_label or ", ".join(spec.y), fontsize=style.label_size)
    axes.tick_params(axis="both", labelsize=style.tick_label_size)
    axes.grid(True, axis=style.grid_axis, alpha=style.grid_alpha)


def _render_bar(
    axes,
    artifact: AnalysisArtifact,
    spec: ChartSpec,
    style: CompanyChartStyle,
) -> None:
    x_column = _require_x(spec)
    x_values = _column_values(artifact, x_column)
    positions = list(range(len(x_values)))
    series_count = len(spec.y)
    width = style.bar_width_fraction / series_count

    for series_index, y_column in enumerate(spec.y):
        offset = (series_index - (series_count - 1) / 2) * width
        axes.bar(
            [position + offset for position in positions],
            _column_values(artifact, y_column),
            width=width,
            label=y_column,
            color=style.color_for_series(series_index),
        )

    axes.set_xticks(positions)
    axes.set_xticklabels(
        [str(value) for value in x_values],
        rotation=style.x_tick_rotation,
        ha="right",
    )
    if len(spec.y) > 1:
        axes.legend()


def _render_line(
    axes,
    artifact: AnalysisArtifact,
    spec: ChartSpec,
    style: CompanyChartStyle,
) -> None:
    x_column = _require_x(spec)
    x_values = _column_values(artifact, x_column)
    rendered_x_values = _renderable_x_values(x_values)
    for series_index, y_column in enumerate(spec.y):
        axes.plot(
            rendered_x_values,
            _column_values(artifact, y_column),
            marker=style.line_marker,
            label=y_column,
            color=style.color_for_series(series_index),
        )

    if rendered_x_values != x_values:
        locator = AutoDateLocator(minticks=4, maxticks=8)
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))

    if len(spec.y) > 1:
        axes.legend()


def _render_scatter(
    axes,
    artifact: AnalysisArtifact,
    spec: ChartSpec,
    style: CompanyChartStyle,
) -> None:
    x_column = _require_x(spec)
    y_column = spec.y[0]
    axes.scatter(
        _column_values(artifact, x_column),
        _column_values(artifact, y_column),
        color=style.color_for_series(0),
    )


def _column_values(artifact: AnalysisArtifact, column: str) -> list[ScalarValue]:
    return [row[column] for row in artifact.rows]


def _renderable_x_values(values: list[ScalarValue]) -> list[ScalarValue]:
    parsed_values = [parse_temporal_value(value) for value in values]
    if all(value is not None for value in parsed_values):
        return parsed_values
    return values


def _require_x(spec: ChartSpec) -> str:
    if spec.x is None:
        raise ChartRenderingError(f"{spec.chart_type} chart requires an x column")
    return spec.x
