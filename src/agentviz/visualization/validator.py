"""Deterministic compatibility checks for chart specifications."""

from __future__ import annotations

from agentviz.errors import ChartValidationError
from agentviz.models import AnalysisArtifact, ChartSpec, ChartType, ScalarValue
from agentviz.visualization.temporal import is_temporal_value, parse_temporal_value


class ChartValidator:
    """Validate a chart intent against concrete analysis output."""

    def __init__(
        self,
        *,
        max_categories: int = 50,
        max_category_label_length: int = 80,
    ) -> None:
        if max_categories < 1:
            raise ValueError("max_categories must be at least 1")
        if max_category_label_length < 1:
            raise ValueError("max_category_label_length must be at least 1")
        self._max_categories = max_categories
        self._max_category_label_length = max_category_label_length

    def validate(self, *, spec: ChartSpec, artifact: AnalysisArtifact) -> ChartSpec:
        if spec.chart_type == ChartType.NONE:
            return spec

        if artifact.truncated and spec.chart_type != ChartType.TABLE:
            raise ChartValidationError(
                "non-table charts require complete, non-truncated data"
            )

        if artifact.row_count == 0 or not artifact.rows:
            raise ChartValidationError("non-empty data is required for chart rendering")

        self._validate_referenced_columns(spec=spec, artifact=artifact)

        match spec.chart_type:
            case ChartType.BAR:
                self._validate_bar(spec, artifact)
            case ChartType.LINE:
                self._validate_line(spec, artifact)
            case ChartType.SCATTER:
                self._validate_scatter(spec, artifact)
            case ChartType.HISTOGRAM:
                self._validate_histogram(spec, artifact)
            case ChartType.BOX:
                self._validate_box(spec, artifact)
            case ChartType.HEATMAP:
                self._validate_heatmap(spec, artifact)
            case ChartType.TABLE:
                self._validate_table(spec, artifact)
            case ChartType.NONE:
                pass

        return spec

    def _validate_referenced_columns(
        self,
        *,
        spec: ChartSpec,
        artifact: AnalysisArtifact,
    ) -> None:
        for column in _referenced_columns(spec):
            if column not in artifact.columns:
                raise ChartValidationError(f"chart references missing column: {column}")

    def _validate_bar(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        x = _require_x(spec)
        _require_y_count(spec, minimum=1)
        self._require_no_nulls(artifact, x)
        self._require_reasonable_categories(artifact, x)
        for y in spec.y:
            self._require_no_nulls(artifact, y)
            self._require_numeric(artifact, y)

    def _validate_line(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        x = _require_x(spec)
        _require_y_count(spec, minimum=1)
        self._require_no_nulls(artifact, x)
        self._require_ordered_or_temporal(artifact, x)
        for y in spec.y:
            self._require_no_nulls(artifact, y)
            self._require_numeric(artifact, y)

    def _validate_scatter(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        x = _require_x(spec)
        y = _require_y_count(spec, exact=1)[0]
        self._require_no_nulls(artifact, x)
        self._require_no_nulls(artifact, y)
        self._require_numeric(artifact, x)
        self._require_numeric(artifact, y)

    def _validate_histogram(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        x = _require_x(spec)
        _require_y_count(spec, exact=0)
        self._require_no_nulls(artifact, x)
        self._require_numeric(artifact, x)

    def _validate_box(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        y = _require_y_count(spec, exact=1)[0]
        self._require_no_nulls(artifact, y)
        self._require_numeric(artifact, y)
        if spec.x is not None:
            self._require_no_nulls(artifact, spec.x)
            self._require_reasonable_categories(artifact, spec.x)

    def _validate_heatmap(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        x = _require_x(spec)
        y = _require_y_count(spec, exact=1)[0]
        self._require_no_nulls(artifact, x)
        self._require_no_nulls(artifact, y)
        self._require_reasonable_categories(artifact, x)
        self._require_reasonable_categories(artifact, y)

    def _validate_table(self, spec: ChartSpec, artifact: AnalysisArtifact) -> None:
        for column in _referenced_columns(spec) or artifact.columns:
            self._require_not_all_null(artifact, column)

    def _require_no_nulls(
        self,
        artifact: AnalysisArtifact,
        column: str,
    ) -> None:
        self._require_not_all_null(artifact, column)
        if any(row[column] is None for row in artifact.rows):
            raise ChartValidationError(f"chart column contains null values: {column}")

    def _require_not_all_null(
        self,
        artifact: AnalysisArtifact,
        column: str,
    ) -> None:
        if not _non_null_values(artifact, column):
            raise ChartValidationError(f"chart column is all null: {column}")

    def _require_numeric(self, artifact: AnalysisArtifact, column: str) -> None:
        values = _non_null_values(artifact, column)
        if not values:
            raise ChartValidationError(f"chart column is all null: {column}")
        if not all(_is_number(value) for value in values):
            raise ChartValidationError(f"chart column must be numeric: {column}")

    def _require_ordered_or_temporal(
        self,
        artifact: AnalysisArtifact,
        column: str,
    ) -> None:
        values = _non_null_values(artifact, column)
        if not values:
            raise ChartValidationError(f"chart column is all null: {column}")
        if not all(_is_number(value) or _is_temporal(value) for value in values):
            raise ChartValidationError(
                f"line chart x column must be ordered or temporal: {column}"
            )
        if not _is_non_decreasing(values):
            raise ChartValidationError(f"line chart x column must be sorted: {column}")

        return

    def _require_reasonable_categories(
        self,
        artifact: AnalysisArtifact,
        column: str,
    ) -> None:
        values = _non_null_values(artifact, column)
        if not values:
            raise ChartValidationError(f"chart column is all null: {column}")
        category_count = len(set(values))
        if category_count > self._max_categories:
            raise ChartValidationError(
                f"chart column has too many categories: {column}"
            )
        if any(
            isinstance(value, str) and len(value) > self._max_category_label_length
            for value in values
        ):
            raise ChartValidationError(f"chart column labels are too long: {column}")


def _referenced_columns(spec: ChartSpec) -> list[str]:
    columns = []
    if spec.x is not None:
        columns.append(spec.x)
    columns.extend(spec.y)
    return columns


def _require_x(spec: ChartSpec) -> str:
    if spec.x is None:
        raise ChartValidationError(f"{spec.chart_type} chart requires an x column")
    return spec.x


def _require_y_count(
    spec: ChartSpec,
    *,
    minimum: int | None = None,
    exact: int | None = None,
) -> list[str]:
    if exact is not None and len(spec.y) != exact:
        raise ChartValidationError(
            f"{spec.chart_type} chart requires exactly {exact} y column(s)"
        )
    if minimum is not None and len(spec.y) < minimum:
        raise ChartValidationError(
            f"{spec.chart_type} chart requires at least {minimum} y column(s)"
        )
    return spec.y


def _non_null_values(
    artifact: AnalysisArtifact,
    column: str,
) -> list[ScalarValue]:
    return [row[column] for row in artifact.rows if row[column] is not None]


def _is_number(value: ScalarValue) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_temporal(value: ScalarValue) -> bool:
    return is_temporal_value(value)


def _is_non_decreasing(values: list[ScalarValue]) -> bool:
    comparable_values = [_comparable_value(value) for value in values]
    return all(
        current <= following
        for current, following in zip(
            comparable_values,
            comparable_values[1:],
            strict=False,
        )
    )


def _comparable_value(value: ScalarValue) -> float | str:
    if _is_number(value):
        return float(value)
    parsed = parse_temporal_value(value)
    if parsed is not None:
        return parsed.isoformat()
    raise ChartValidationError("chart column contains non-orderable values")
