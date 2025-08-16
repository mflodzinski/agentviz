"""Core domain models used at deterministic boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type ScalarValue = str | int | float | bool | None
type Row = dict[str, ScalarValue]


class AgentVizModel(BaseModel):
    """Base settings for small immutable domain models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class DatabaseBackend(StrEnum):
    """Supported database backend identifiers."""

    SQLITE = "sqlite"


class UserIdentity(AgentVizModel):
    """Identity supplied by the CLI.

    This is not authentication. It only represents the user name that future
    deterministic authorization code will evaluate.
    """

    username: str = Field(min_length=1)


class AnalysisRequest(AgentVizModel):
    """A user's natural-language request against a logical database."""

    user: UserIdentity
    database: str = Field(min_length=1)
    question: str = Field(min_length=1)
    include_visualization: bool = True


class DatabaseConfig(AgentVizModel):
    """Configuration for a registered logical database."""

    name: str = Field(min_length=1)
    backend: DatabaseBackend
    path: Path


class ForeignKeyMetadata(AgentVizModel):
    """A declared table relationship discovered from database metadata."""

    column: str = Field(min_length=1)
    referenced_table: str = Field(min_length=1)
    referenced_column: str = Field(min_length=1)


class ColumnMetadata(AgentVizModel):
    """Column information exposed to deterministic code and agents."""

    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool = True
    primary_key: bool = False


class TableMetadata(AgentVizModel):
    """Schema information for one table or view."""

    name: str = Field(min_length=1)
    columns: list[ColumnMetadata] = Field(min_length=1)
    foreign_keys: list[ForeignKeyMetadata] = Field(default_factory=list)
    row_count: int | None = Field(default=None, ge=0)

    @field_validator("columns")
    @classmethod
    def column_names_must_be_unique(
        cls, columns: list[ColumnMetadata]
    ) -> list[ColumnMetadata]:
        names = [column.name for column in columns]
        if len(names) != len(set(names)):
            raise ValueError("column names must be unique within a table")
        return columns


class DatabaseMetadata(AgentVizModel):
    """Schema information for a logical database."""

    name: str = Field(min_length=1)
    backend: DatabaseBackend
    tables: list[TableMetadata] = Field(min_length=1)

    @field_validator("tables")
    @classmethod
    def table_names_must_be_unique(
        cls, tables: list[TableMetadata]
    ) -> list[TableMetadata]:
        names = [table.name for table in tables]
        if len(names) != len(set(names)):
            raise ValueError("table names must be unique within a database")
        return tables


class QueryExecutionResult(AgentVizModel):
    """Rows returned by deterministic query execution."""

    executed_sql: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    rows: list[Row] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    truncated: bool = False

    @field_validator("columns")
    @classmethod
    def result_column_names_must_be_unique(cls, columns: list[str]) -> list[str]:
        if len(columns) != len(set(columns)):
            raise ValueError("result column names must be unique")
        return columns

    @model_validator(mode="after")
    def rows_must_match_columns(self) -> QueryExecutionResult:
        expected_columns = set(self.columns)
        for index, row in enumerate(self.rows):
            if set(row) != expected_columns:
                raise ValueError(
                    f"row {index} keys must exactly match result columns"
                )

        if self.row_count != len(self.rows):
            raise ValueError("row_count must match the number of returned rows")

        return self


class QueryProvenance(AgentVizModel):
    """Metadata describing where a deterministic query result came from."""

    user: str = Field(min_length=1)
    database: str = Field(min_length=1)
    executed_sql: str = Field(min_length=1)
    tables_used: frozenset[str]
    row_count: int = Field(ge=0)
    truncated: bool
    executed_at: datetime


class AnalysisQueryResult(AgentVizModel):
    """Deterministic query result returned before any LLM analysis exists."""

    result: QueryExecutionResult
    provenance: QueryProvenance


class ProposedQuery(AgentVizModel):
    """Typed SQL proposal produced by the Analysis Agent planner."""

    sql: str = Field(min_length=1)
    reasoning_summary: str | None = None


class AnalysisPlanKind(StrEnum):
    """Planner outcome before deterministic query execution."""

    QUERY = "query"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


class AnalysisPlan(AgentVizModel):
    """Typed semantic plan produced by the Analysis Agent planner."""

    kind: AnalysisPlanKind
    query: ProposedQuery | None = None
    message: str | None = None

    @classmethod
    def query_plan(cls, query: ProposedQuery) -> AnalysisPlan:
        return cls(kind=AnalysisPlanKind.QUERY, query=query)

    @classmethod
    def clarification(cls, message: str) -> AnalysisPlan:
        return cls(kind=AnalysisPlanKind.CLARIFICATION, message=message)

    @classmethod
    def unsupported(cls, message: str) -> AnalysisPlan:
        return cls(kind=AnalysisPlanKind.UNSUPPORTED, message=message)

    @model_validator(mode="after")
    def plan_payload_must_match_kind(self) -> AnalysisPlan:
        if self.kind == AnalysisPlanKind.QUERY:
            if self.query is None:
                raise ValueError("query plans require a proposed query")
            if self.message is not None:
                raise ValueError("query plans must not include a message")
            return self

        if self.query is not None:
            raise ValueError("non-query plans must not include a proposed query")
        if not self.message:
            raise ValueError("non-query plans require a message")
        return self


class AnalysisArtifact(AgentVizModel):
    """Structured result passed from analysis toward visualization."""

    request: AnalysisRequest
    database: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    rows: list[Row] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    truncated: bool
    summary: str = Field(min_length=1)
    provenance: QueryProvenance

    @classmethod
    def from_query_result(
        cls,
        *,
        request: AnalysisRequest,
        query_result: AnalysisQueryResult,
        summary: str,
    ) -> AnalysisArtifact:
        result = query_result.result
        return cls(
            request=request,
            database=query_result.provenance.database,
            sql=result.executed_sql,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
            summary=summary,
            provenance=query_result.provenance,
        )

    @model_validator(mode="after")
    def artifact_must_match_provenance(self) -> AnalysisArtifact:
        if self.database != self.provenance.database:
            raise ValueError("artifact database must match provenance database")

        if self.sql != self.provenance.executed_sql:
            raise ValueError("artifact SQL must match provenance SQL")

        if self.row_count != self.provenance.row_count:
            raise ValueError("artifact row_count must match provenance row_count")

        if self.truncated != self.provenance.truncated:
            raise ValueError("artifact truncated flag must match provenance")

        return self


class AnalysisAgentStatus(StrEnum):
    """Final Analysis Agent outcome."""

    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class AnalysisAgentResult(AgentVizModel):
    """Typed result returned by the Analysis Agent."""

    status: AnalysisAgentStatus
    artifact: AnalysisArtifact | None = None
    message: str | None = None

    @classmethod
    def completed(cls, artifact: AnalysisArtifact) -> AnalysisAgentResult:
        return cls(status=AnalysisAgentStatus.COMPLETED, artifact=artifact)

    @classmethod
    def needs_clarification(cls, message: str) -> AnalysisAgentResult:
        return cls(status=AnalysisAgentStatus.NEEDS_CLARIFICATION, message=message)

    @classmethod
    def unsupported(cls, message: str) -> AnalysisAgentResult:
        return cls(status=AnalysisAgentStatus.UNSUPPORTED, message=message)

    @model_validator(mode="after")
    def result_payload_must_match_status(self) -> AnalysisAgentResult:
        if self.status == AnalysisAgentStatus.COMPLETED:
            if self.artifact is None:
                raise ValueError("completed analysis results require an artifact")
            if self.message is not None:
                raise ValueError(
                    "completed analysis results must not include a message"
                )
            return self

        if self.artifact is not None:
            raise ValueError("non-completed analysis results must not include artifact")
        if not self.message:
            raise ValueError("non-completed analysis results require a message")
        return self


class ChartType(StrEnum):
    """Supported visualization intent types."""

    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    BOX = "box"
    HEATMAP = "heatmap"
    TABLE = "table"
    NONE = "none"


class ChartSpec(AgentVizModel):
    """Declarative visualization intent produced before deterministic rendering."""

    chart_type: ChartType
    title: str = Field(min_length=1)
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    x_label: str | None = None
    y_label: str | None = None
    aggregation: str | None = None
    sort: str | None = None

    @field_validator("y")
    @classmethod
    def y_columns_must_be_unique(cls, y: list[str]) -> list[str]:
        if len(y) != len(set(y)):
            raise ValueError("y columns must be unique")
        return y

    @model_validator(mode="after")
    def none_chart_must_not_include_encodings(self) -> ChartSpec:
        if self.chart_type != ChartType.NONE:
            return self

        if any(
            value is not None
            for value in (
                self.x,
                self.x_label,
                self.y_label,
                self.aggregation,
                self.sort,
            )
        ) or self.y:
            raise ValueError("none charts must not include encodings")

        return self


class VisualizationColumnType(StrEnum):
    """Conservative column type inferred for visualization planning."""

    EMPTY = "empty"
    NUMERIC = "numeric"
    TEMPORAL = "temporal"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"


class VisualizationColumnProfile(AgentVizModel):
    """Column-level metadata safe to expose to a visualization planner."""

    name: str = Field(min_length=1)
    inferred_type: VisualizationColumnType
    null_count: int = Field(ge=0)
    non_null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    numeric_min: float | None = None
    numeric_max: float | None = None

    @model_validator(mode="after")
    def numeric_bounds_must_match_type(self) -> VisualizationColumnProfile:
        has_numeric_bounds = (
            self.numeric_min is not None or self.numeric_max is not None
        )
        if self.inferred_type != VisualizationColumnType.NUMERIC and has_numeric_bounds:
            raise ValueError("numeric bounds require numeric inferred type")
        if self.inferred_type == VisualizationColumnType.NUMERIC and (
            self.numeric_min is None or self.numeric_max is None
        ):
            raise ValueError("numeric inferred type requires numeric bounds")
        return self


class VisualizationContext(AgentVizModel):
    """Compact, row-free context intended for visualization planning."""

    question: str = Field(min_length=1)
    database: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    truncated: bool
    columns: list[VisualizationColumnProfile]

    @field_validator("columns")
    @classmethod
    def column_profiles_must_be_unique(
        cls,
        columns: list[VisualizationColumnProfile],
    ) -> list[VisualizationColumnProfile]:
        names = [column.name for column in columns]
        if len(names) != len(set(names)):
            raise ValueError("visualization context column names must be unique")
        return columns


class ApplicationRunResult(AgentVizModel):
    """Typed result returned by deterministic application orchestration."""

    run_id: str = Field(min_length=1)
    analysis: AnalysisAgentResult
    chart_spec: ChartSpec | None = None
    chart_path: Path | None = None
    visualization_warning: str | None = None

    @model_validator(mode="after")
    def chart_path_requires_chart_spec(self) -> ApplicationRunResult:
        if self.chart_path is not None and self.chart_spec is None:
            raise ValueError("chart_path requires a chart_spec")
        return self
