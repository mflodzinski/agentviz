from agentviz.models import (
    AnalysisRequest,
    ChartType,
    ColumnMetadata,
    DatabaseBackend,
    DatabaseMetadata,
    ForeignKeyMetadata,
    TableMetadata,
    UserIdentity,
    VisualizationColumnProfile,
    VisualizationColumnType,
    VisualizationContext,
)
from agentviz.prompts import (
    analysis_plan_response_schema,
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    build_schema_context,
    build_visualization_system_prompt,
    build_visualization_user_prompt,
    chart_spec_response_schema,
)


def schema() -> DatabaseMetadata:
    return DatabaseMetadata(
        name="sales",
        backend=DatabaseBackend.SQLITE,
        tables=[
            TableMetadata(
                name="orders",
                row_count=10,
                columns=[
                    ColumnMetadata(
                        name="order_id",
                        data_type="INTEGER",
                        nullable=False,
                        primary_key=True,
                    ),
                    ColumnMetadata(
                        name="customer_id",
                        data_type="INTEGER",
                        nullable=False,
                    ),
                    ColumnMetadata(name="total", data_type="REAL"),
                ],
                foreign_keys=[
                    ForeignKeyMetadata(
                        column="customer_id",
                        referenced_table="customers",
                        referenced_column="customer_id",
                    )
                ],
            ),
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="customer_id", data_type="INTEGER"),
                    ColumnMetadata(name="email", data_type="TEXT"),
                ],
            ),
        ],
    )


def test_build_schema_context_serializes_authorized_schema_compactly() -> None:
    context = build_schema_context(schema())

    assert "database: sales" in context
    assert "- customers" in context
    assert "- orders, rows=10" in context
    assert "order_id: INTEGER [pk, not_null]" in context
    assert "fk: customer_id -> customers.customer_id" in context


def test_build_schema_context_applies_table_and_column_limits() -> None:
    context = build_schema_context(schema(), max_tables=1, max_columns_per_table=1)

    assert "- customers" in context
    assert "- email: TEXT" not in context
    assert "... 1 more column(s) omitted" in context
    assert "... 1 more table(s) omitted" in context


def test_build_analysis_prompts_include_question_and_schema() -> None:
    request = AnalysisRequest(
        user=UserIdentity(username="alice"),
        database="sales",
        question="Show total revenue by customer.",
    )

    system_prompt = build_analysis_system_prompt()
    user_prompt = build_analysis_user_prompt(request=request, schema=schema())

    assert "read-only SQLite SELECT" in system_prompt
    assert "Authorization, SQL validation, and execution" in system_prompt
    assert "Show total revenue by customer." in user_prompt
    assert "Authorized schema:" in user_prompt
    assert "orders" in user_prompt


def test_build_visualization_prompt_uses_row_free_context() -> None:
    context = VisualizationContext(
        question="Show revenue by customer.",
        database="sales",
        summary="Returned revenue by customer.",
        row_count=100,
        truncated=False,
        columns=[
            VisualizationColumnProfile(
                name="customer_email",
                inferred_type=VisualizationColumnType.CATEGORICAL,
                null_count=0,
                non_null_count=100,
                distinct_count=100,
            ),
            VisualizationColumnProfile(
                name="revenue",
                inferred_type=VisualizationColumnType.NUMERIC,
                null_count=0,
                non_null_count=100,
                distinct_count=90,
                numeric_min=1.0,
                numeric_max=500.0,
            ),
        ],
    )

    prompt = build_visualization_user_prompt(context)

    assert "Visualization context:" in prompt
    assert "customer_email" in prompt
    assert "revenue" in prompt
    assert "alice@example.com" not in prompt
    assert "Ignore previous instructions" not in prompt


def test_visualization_system_prompt_reinforces_chart_spec_boundary() -> None:
    prompt = build_visualization_system_prompt()

    assert "ChartSpec" in prompt
    assert "Do not generate code" in prompt
    assert "row-free visualization context" in prompt


def test_response_schemas_are_json_schema_objects() -> None:
    analysis_schema = analysis_plan_response_schema()
    chart_schema = chart_spec_response_schema()

    assert analysis_schema["type"] == "object"
    assert analysis_schema["additionalProperties"] is False
    assert set(analysis_schema["properties"]["kind"]["enum"]) == {
        "query",
        "clarification",
        "unsupported",
    }
    assert chart_schema["type"] == "object"
    assert "chart_type" in chart_schema["properties"]
    assert ChartType.LINE in set(ChartType)


def test_chart_spec_schema_is_compatible_with_openai_strict_outputs() -> None:
    chart_schema = chart_spec_response_schema()

    assert set(chart_schema["required"]) == set(chart_schema["properties"])
    assert "default" not in str(chart_schema)
    assert chart_schema["additionalProperties"] is False
    assert chart_schema["properties"]["x"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
