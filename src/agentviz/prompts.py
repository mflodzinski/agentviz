"""Prompt builders for future LLM-backed planners."""

from __future__ import annotations

import json

from agentviz.models import (
    AnalysisRequest,
    ChartSpec,
    DatabaseMetadata,
    VisualizationContext,
)

DEFAULT_MAX_TABLES = 40
DEFAULT_MAX_COLUMNS_PER_TABLE = 40


def build_schema_context(
    schema: DatabaseMetadata,
    *,
    max_tables: int = DEFAULT_MAX_TABLES,
    max_columns_per_table: int = DEFAULT_MAX_COLUMNS_PER_TABLE,
) -> str:
    """Serialize authorized schema compactly for an LLM prompt."""

    if max_tables < 1:
        raise ValueError("max_tables must be at least 1")
    if max_columns_per_table < 1:
        raise ValueError("max_columns_per_table must be at least 1")

    lines = [f"database: {schema.name}", f"backend: {schema.backend}", "tables:"]
    sorted_tables = sorted(schema.tables, key=lambda table: table.name)
    for table in sorted_tables[:max_tables]:
        row_count = f", rows={table.row_count}" if table.row_count is not None else ""
        lines.append(f"- {table.name}{row_count}")
        for column in table.columns[:max_columns_per_table]:
            flags = []
            if column.primary_key:
                flags.append("pk")
            if not column.nullable:
                flags.append("not_null")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {column.name}: {column.data_type}{suffix}")
        if len(table.columns) > max_columns_per_table:
            remaining = len(table.columns) - max_columns_per_table
            lines.append(f"  - ... {remaining} more column(s) omitted")
        for foreign_key in table.foreign_keys:
            lines.append(
                "  fk: "
                f"{foreign_key.column} -> "
                f"{foreign_key.referenced_table}.{foreign_key.referenced_column}"
            )

    if len(sorted_tables) > max_tables:
        remaining = len(sorted_tables) - max_tables
        lines.append(f"... {remaining} more table(s) omitted")

    return "\n".join(lines)


def build_analysis_system_prompt() -> str:
    return (
        "You are the AgentViz Analysis Planner. Decide whether a user's "
        "authorized database can answer the request. Return only structured "
        "data matching the requested schema. If SQL is needed, propose exactly "
        "one read-only SQLite SELECT statement. Do not propose writes, PRAGMA, "
        "ATTACH, multiple statements, or references outside the provided schema. "
        "Authorization, SQL validation, and execution are handled by "
        "deterministic code."
    )


def build_analysis_user_prompt(
    *,
    request: AnalysisRequest,
    schema: DatabaseMetadata,
    max_tables: int = DEFAULT_MAX_TABLES,
    max_columns_per_table: int = DEFAULT_MAX_COLUMNS_PER_TABLE,
) -> str:
    return "\n\n".join(
        [
            f"User question:\n{request.question}",
            "Authorized schema:\n"
            + build_schema_context(
                schema,
                max_tables=max_tables,
                max_columns_per_table=max_columns_per_table,
            ),
            "Return one of: query, clarification, unsupported.",
        ]
    )


def build_visualization_system_prompt() -> str:
    return (
        "You are the AgentViz Visualization Planner. Choose a declarative "
        "ChartSpec for the analysis result. Do not generate code. Do not assume "
        "access to a database. Use only the row-free visualization context. "
        "Return none when a chart would be misleading or not useful."
    )


def build_visualization_user_prompt(context: VisualizationContext) -> str:
    return (
        "Visualization context:\n"
        + json.dumps(context.model_dump(mode="json"), indent=2, sort_keys=True)
    )


def analysis_plan_response_schema() -> dict:
    return {
        "additionalProperties": False,
        "properties": {
            "kind": {"enum": ["query", "clarification", "unsupported"]},
            "sql": {"type": ["string", "null"]},
            "reasoning_summary": {"type": ["string", "null"]},
            "message": {"type": ["string", "null"]},
        },
        "required": ["kind", "sql", "reasoning_summary", "message"],
        "type": "object",
    }


def chart_spec_response_schema() -> dict:
    schema = ChartSpec.model_json_schema()
    _require_all_object_properties(schema)
    _remove_schema_defaults(schema)
    return schema


def _require_all_object_properties(schema: dict) -> None:
    """Adapt Pydantic JSON Schema to OpenAI strict structured outputs."""

    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        schema["required"] = list(schema["properties"])
        schema.setdefault("additionalProperties", False)

    for value in schema.values():
        if isinstance(value, dict):
            _require_all_object_properties(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _require_all_object_properties(item)


def _remove_schema_defaults(schema: dict) -> None:
    schema.pop("default", None)
    for value in schema.values():
        if isinstance(value, dict):
            _remove_schema_defaults(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _remove_schema_defaults(item)
