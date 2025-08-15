"""Core domain models used at deterministic boundaries."""

from __future__ import annotations

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
