"""Deterministic summaries for analysis artifacts."""

from __future__ import annotations

from agentviz.models import AnalysisQueryResult, AnalysisRequest


def build_analysis_summary(
    *,
    request: AnalysisRequest,
    query_result: AnalysisQueryResult,
) -> str:
    """Create a concise, non-LLM summary without reading row values."""

    result = query_result.result
    column_count = len(result.columns)
    row_word = "row" if result.row_count == 1 else "rows"
    column_word = "column" if column_count == 1 else "columns"
    columns = ", ".join(result.columns)
    truncation = (
        " Result was truncated by the configured row limit."
        if result.truncated
        else ""
    )

    return (
        f"Query for {request.database!r} returned {result.row_count} {row_word} "
        f"and {column_count} {column_word}: {columns}.{truncation}"
    )
