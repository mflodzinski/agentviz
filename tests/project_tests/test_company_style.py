from datetime import UTC, datetime

from agentviz.models import (
    AnalysisArtifact,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    QueryProvenance,
    UserIdentity,
)
from agentviz.visualization import ChartRenderer, CompanyChartStyle


def test_company_chart_style_cycles_palette() -> None:
    style = CompanyChartStyle(palette=("#111111", "#222222"))

    assert style.color_for_series(0) == "#111111"
    assert style.color_for_series(1) == "#222222"
    assert style.color_for_series(2) == "#111111"


def test_chart_renderer_accepts_injected_company_style(tmp_path) -> None:
    artifact = AnalysisArtifact(
        request=AnalysisRequest(
            user=UserIdentity(username="alice"),
            database="chinook",
            question="Show values.",
        ),
        database="chinook",
        sql="SELECT category, value FROM metrics",
        columns=["category", "value"],
        rows=[{"category": "A", "value": 10}, {"category": "B", "value": 12}],
        row_count=2,
        truncated=False,
        summary="Returned values.",
        provenance=QueryProvenance(
            user="alice",
            database="chinook",
            executed_sql="SELECT category, value FROM metrics",
            tables_used=frozenset({"metrics"}),
            row_count=2,
            truncated=False,
            executed_at=datetime(2026, 8, 16, tzinfo=UTC),
        ),
    )
    spec = ChartSpec(
        chart_type=ChartType.BAR,
        title="Value by category",
        x="category",
        y=["value"],
    )
    style = CompanyChartStyle(
        figure_size=(4.0, 3.0),
        dpi=80,
        palette=("#111111",),
        x_tick_rotation=0,
    )
    output_path = tmp_path / "styled.png"

    ChartRenderer(style=style).render(
        artifact=artifact,
        spec=spec,
        output_path=output_path,
    )

    assert output_path.exists()
    assert output_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
