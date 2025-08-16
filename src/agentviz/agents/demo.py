"""Deterministic demo planners used until real LLM planners are configured."""

from __future__ import annotations

from agentviz.errors import DatabaseExecutionError
from agentviz.models import (
    AnalysisPlan,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    DatabaseMetadata,
    ProposedQuery,
    VisualizationColumnProfile,
    VisualizationColumnType,
    VisualizationContext,
)


class DemoAnalysisPlanner:
    """Small schema-aware planner for local CLI smoke tests.

    This is not a replacement for the intended LLM-backed Analysis Agent. It
    keeps the CLI demonstrable while preserving the deterministic execution
    boundary.
    """

    def plan(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
    ) -> AnalysisPlan:
        question = request.question.lower()
        if not _has_columns(schema, "invoices", {"InvoiceId", "Total"}):
            return AnalysisPlan.unsupported(
                "The demo planner only supports invoice-style schemas."
            )

        if "revenue" in question and "country" in question and _has_columns(
            schema,
            "invoices",
            {"BillingCountry", "Total"},
        ):
            return AnalysisPlan.query_plan(
                ProposedQuery(
                    sql=(
                        "SELECT BillingCountry, SUM(Total) AS revenue "
                        "FROM invoices "
                        "GROUP BY BillingCountry "
                        "ORDER BY revenue DESC"
                    ),
                    reasoning_summary=(
                        "Revenue by country can be computed from invoices."
                    ),
                )
            )

        if "total revenue" in question or "total sales" in question:
            return AnalysisPlan.query_plan(
                ProposedQuery(
                    sql="SELECT SUM(Total) AS total_revenue FROM invoices",
                    reasoning_summary="Total revenue can be summed from invoices.",
                )
            )

        if "invoice" in question and "total" in question:
            return AnalysisPlan.query_plan(
                ProposedQuery(
                    sql="SELECT InvoiceId, Total FROM invoices ORDER BY InvoiceId",
                    reasoning_summary="Invoice totals are stored in invoices.",
                )
            )

        return AnalysisPlan.unsupported(
            "No LLM planner is configured, and the demo planner could not map "
            "this request to a supported query."
        )

    def repair_query(
        self,
        *,
        request: AnalysisRequest,
        schema: DatabaseMetadata,
        failed_query: ProposedQuery,
        error: DatabaseExecutionError,
        attempt: int,
    ) -> ProposedQuery:
        return failed_query


class DemoVisualizationPlanner:
    """Small row-free visualization planner for local CLI smoke tests."""

    def propose_chart(self, *, context: VisualizationContext) -> ChartSpec:
        if context.truncated:
            return ChartSpec(
                chart_type=ChartType.NONE,
                title="No chart generated for truncated results",
            )

        if context.row_count == 0:
            return ChartSpec(chart_type=ChartType.NONE, title="No rows returned")

        if context.row_count == 1:
            return ChartSpec(
                chart_type=ChartType.NONE,
                title="Single-row result does not need a chart",
            )

        numeric_columns = _columns_by_type(
            context.columns,
            VisualizationColumnType.NUMERIC,
        )
        categorical_columns = _columns_by_type(
            context.columns,
            VisualizationColumnType.CATEGORICAL,
        )
        temporal_columns = _columns_by_type(
            context.columns,
            VisualizationColumnType.TEMPORAL,
        )

        if temporal_columns and numeric_columns:
            x = temporal_columns[0]
            y = numeric_columns[0]
            return ChartSpec(
                chart_type=ChartType.LINE,
                title=f"{y} by {x}",
                x=x,
                y=[y],
            )

        if categorical_columns and numeric_columns:
            x = categorical_columns[0]
            y = numeric_columns[0]
            return ChartSpec(
                chart_type=ChartType.BAR,
                title=f"{y} by {x}",
                x=x,
                y=[y],
            )

        if len(numeric_columns) >= 2:
            return ChartSpec(
                chart_type=ChartType.SCATTER,
                title=f"{numeric_columns[1]} by {numeric_columns[0]}",
                x=numeric_columns[0],
                y=[numeric_columns[1]],
            )

        return ChartSpec(
            chart_type=ChartType.NONE,
            title="No chart generated for this result shape",
        )


def _columns_by_type(
    columns: list[VisualizationColumnProfile],
    inferred_type: VisualizationColumnType,
) -> list[str]:
    return [
        column.name
        for column in columns
        if column.inferred_type == inferred_type
    ]


def _has_columns(
    schema: DatabaseMetadata,
    table_name: str,
    required_columns: set[str],
) -> bool:
    for table in schema.tables:
        if table.name != table_name:
            continue
        available_columns = {column.name for column in table.columns}
        return required_columns <= available_columns
    return False
