"""Deterministic SQL statement validation."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from agentviz.errors import SQLValidationError


@dataclass(frozen=True)
class ValidatedSql:
    """SQL that passed the current deterministic safety rules."""

    sql: str
    referenced_tables: frozenset[str]


class SQLValidator:
    """Validate basic read-only SQL statement shape."""

    def __init__(self, *, dialect: str = "sqlite") -> None:
        self._dialect = dialect

    def validate(self, sql: str) -> ValidatedSql:
        candidate = sql.strip()
        if not candidate:
            raise SQLValidationError("SQL must not be empty")

        expression = self._parse_single_statement(candidate)
        self._validate_read_only_select(expression)

        return ValidatedSql(
            sql=candidate,
            referenced_tables=_extract_referenced_tables(expression),
        )

    def _parse_single_statement(self, sql: str) -> exp.Expression:
        try:
            statements = sqlglot.parse(sql, read=self._dialect)
        except ParseError as exc:
            raise SQLValidationError(f"SQL could not be parsed: {exc}") from exc

        statements = [statement for statement in statements if statement is not None]
        if len(statements) != 1:
            raise SQLValidationError("SQL must contain exactly one statement")

        return statements[0]

    def _validate_read_only_select(self, expression: exp.Expression) -> None:
        if not isinstance(expression, exp.Select):
            raise SQLValidationError("only SELECT statements are allowed")

        unsafe_expression = _find_unsafe_expression(expression)
        if unsafe_expression is not None:
            raise SQLValidationError(
                f"unsafe SQL operation is not allowed: "
                f"{unsafe_expression.__class__.__name__}"
            )

        unsafe_function = _find_unsafe_function(expression)
        if unsafe_function is not None:
            raise SQLValidationError(
                f"unsafe SQL function is not allowed: {unsafe_function.name}"
            )

        unsupported_table = _find_unsupported_table_reference(expression)
        if unsupported_table is not None:
            raise SQLValidationError(
                f"unsupported table reference is not allowed: "
                f"{unsupported_table.sql()}"
            )


def _find_unsafe_expression(expression: exp.Expression) -> exp.Expression | None:
    unsafe_types = (
        exp.Alter,
        exp.Command,
        exp.Create,
        exp.Delete,
        exp.Drop,
        exp.Insert,
        exp.Merge,
        exp.Update,
    )

    return next(expression.find_all(*unsafe_types), None)


def _find_unsafe_function(expression: exp.Expression) -> exp.Expression | None:
    for function in expression.find_all(exp.Anonymous):
        function_name = function.name.lower()
        if function_name == "load_extension" or function_name.startswith("pragma_"):
            return function

    return None


def _find_unsupported_table_reference(
    expression: exp.Expression,
) -> exp.Table | None:
    cte_names = _cte_names(expression)
    for table in expression.find_all(exp.Table):
        if not table.name or table.name in cte_names:
            continue

        if table.db:
            return table

        if table.name.lower().startswith("sqlite_"):
            return table

    return None


def _extract_referenced_tables(expression: exp.Expression) -> frozenset[str]:
    cte_names = _cte_names(expression)
    table_names = {
        table.name
        for table in expression.find_all(exp.Table)
        if table.name and table.name not in cte_names
    }

    return frozenset(table_names)


def _cte_names(expression: exp.Expression) -> frozenset[str]:
    return frozenset(
        cte.alias_or_name
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    )
