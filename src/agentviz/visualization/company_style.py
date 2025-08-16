"""Centralized deterministic chart styling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyChartStyle:
    """Rendering constants shared by deterministic chart renderers."""

    figure_size: tuple[float, float] = (8.0, 4.5)
    dpi: int = 120
    title_size: int = 14
    label_size: int = 11
    tick_label_size: int = 9
    grid_axis: str = "y"
    grid_alpha: float = 0.25
    bar_width_fraction: float = 0.8
    x_tick_rotation: int = 30
    line_marker: str = "o"
    palette: tuple[str, ...] = (
        "#2563eb",
        "#16a34a",
        "#dc2626",
        "#9333ea",
        "#ea580c",
        "#0891b2",
    )

    def color_for_series(self, index: int) -> str:
        return self.palette[index % len(self.palette)]


DEFAULT_COMPANY_STYLE = CompanyChartStyle()
