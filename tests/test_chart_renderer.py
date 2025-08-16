from datetime import UTC, datetime

import pytest
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

from agentviz.errors import ChartRenderingError, ChartValidationError
from agentviz.models import (
    AnalysisArtifact,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    QueryProvenance,
    Row,
    UserIdentity,
)
from agentviz.visualization import ChartRenderer


def artifact_with_rows(rows: list[Row]) -> AnalysisArtifact:
    columns = list(rows[0]) if rows else ["category", "value"]
    return AnalysisArtifact(
        request=AnalysisRequest(
            user=UserIdentity(username="alice"),
            database="chinook",
            question="Show values.",
        ),
        database="chinook",
        sql="SELECT category, value FROM metrics",
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=False,
        summary="Returned values.",
        provenance=QueryProvenance(
            user="alice",
            database="chinook",
            executed_sql="SELECT category, value FROM metrics",
            tables_used=frozenset({"metrics"}),
            row_count=len(rows),
            truncated=False,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )


def assert_png_written(path) -> None:
    assert path.exists()
    assert path.stat().st_size > 0
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_renderer_writes_bar_chart_png(tmp_path) -> None:
    artifact = artifact_with_rows(
        [
            {"category": "A", "value": 10},
            {"category": "B", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )
    output_path = tmp_path / "bar.png"

    result = ChartRenderer().render(
        artifact=artifact,
        spec=spec,
        output_path=output_path,
    )

    assert result == output_path
    assert_png_written(output_path)


def test_bar_chart_uses_company_style_x_tick_rotation(tmp_path, monkeypatch) -> None:
    artifact = artifact_with_rows(
        [
            {"store_id": 1, "revenue": 10},
            {"store_id": 2, "revenue": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Revenue by store",
        x="store_id",
        y=["revenue"],
    )
    saved_figures = []

    def record_savefig(self, *args, **kwargs):
        saved_figures.append(self)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", record_savefig)

    ChartRenderer().render(
        artifact=artifact,
        spec=spec,
        output_path=tmp_path / "bar.png",
    )

    labels = saved_figures[0].axes[0].get_xticklabels()
    assert [label.get_rotation() for label in labels] == [30, 30]


def test_chart_renderer_writes_line_chart_png(tmp_path) -> None:
    artifact = artifact_with_rows(
        [
            {"month": "2026-01-01", "value": 10},
            {"month": "2026-02-01", "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by month",
        x="month",
        y=["value"],
    )
    output_path = tmp_path / "line.png"

    ChartRenderer().render(artifact=artifact, spec=spec, output_path=output_path)

    assert_png_written(output_path)


def test_line_chart_uses_date_axis_for_temporal_strings(tmp_path, monkeypatch) -> None:
    artifact = artifact_with_rows(
        [
            {"month": "2026-01", "value": 10},
            {"month": "2026-02", "value": 12},
            {"month": "2026-03", "value": 14},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Value by month",
        x="month",
        y=["value"],
    )
    saved_figures = []

    def record_savefig(self, *args, **kwargs):
        saved_figures.append(self)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", record_savefig)

    ChartRenderer().render(
        artifact=artifact,
        spec=spec,
        output_path=tmp_path / "line.png",
    )

    axis = saved_figures[0].axes[0].xaxis
    assert isinstance(axis.get_major_locator(), AutoDateLocator)
    assert isinstance(axis.get_major_formatter(), ConciseDateFormatter)


def test_chart_renderer_writes_scatter_chart_png(tmp_path) -> None:
    artifact = artifact_with_rows(
        [
            {"x": 1, "value": 10},
            {"x": 2, "value": 12},
        ]
    )
    spec = ChartSpec(
        chart_type=ChartType.SCATTER,
        title="Value by x",
        x="x",
        y=["value"],
    )
    output_path = tmp_path / "scatter.png"

    ChartRenderer().render(artifact=artifact, spec=spec, output_path=output_path)

    assert_png_written(output_path)


def test_chart_renderer_validates_before_writing_file(tmp_path) -> None:
    artifact = artifact_with_rows([{"category": "A", "value": 10}])
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="missing",
        y=["value"],
    )
    output_path = tmp_path / "invalid.png"

    with pytest.raises(ChartValidationError, match="missing column"):
        ChartRenderer().render(artifact=artifact, spec=spec, output_path=output_path)

    assert not output_path.exists()


def test_chart_renderer_rejects_unsupported_chart_type(tmp_path) -> None:
    artifact = artifact_with_rows([{"value": 10}, {"value": 12}])
    spec = ChartSpec(
        chart_type=ChartType.HISTOGRAM,
        title="Value distribution",
        x="value",
    )

    with pytest.raises(ChartRenderingError, match="not implemented"):
        ChartRenderer().render(
            artifact=artifact,
            spec=spec,
            output_path=tmp_path / "histogram.png",
        )
