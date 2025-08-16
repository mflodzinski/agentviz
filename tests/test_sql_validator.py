import pytest

from agentviz.errors import SQLValidationError
from agentviz.sql import SQLValidator, ValidatedSql


@pytest.fixture()
def validator() -> SQLValidator:
    return SQLValidator(dialect="sqlite")


def test_validator_accepts_select(validator: SQLValidator) -> None:
    result = validator.validate("SELECT InvoiceId, Total FROM invoices")

    assert result == ValidatedSql(
        sql="SELECT InvoiceId, Total FROM invoices",
        referenced_tables=frozenset({"invoices"}),
    )


def test_validator_accepts_with_select(validator: SQLValidator) -> None:
    result = validator.validate(
        """
        WITH monthly AS (
            SELECT strftime('%Y-%m', InvoiceDate) AS month, SUM(Total) AS revenue
            FROM invoices
            GROUP BY month
        )
        SELECT month, revenue FROM monthly
        """
    )

    assert result.sql.startswith("WITH monthly AS")
    assert result.referenced_tables == frozenset({"invoices"})


def test_validator_extracts_joined_tables(validator: SQLValidator) -> None:
    result = validator.validate(
        """
        SELECT i.InvoiceId, c.CustomerId
        FROM invoices AS i
        JOIN customers AS c ON i.CustomerId = c.CustomerId
        """
    )

    assert result.referenced_tables == frozenset({"customers", "invoices"})


def test_validator_extracts_tables_inside_subqueries(
    validator: SQLValidator,
) -> None:
    result = validator.validate(
        """
        SELECT *
        FROM (
            SELECT *
            FROM private_table
        ) AS nested
        """
    )

    assert result.referenced_tables == frozenset({"private_table"})


def test_validator_extracts_tables_inside_nested_ctes(
    validator: SQLValidator,
) -> None:
    result = validator.validate(
        """
        WITH customer_totals AS (
            SELECT CustomerId, SUM(Total) AS revenue
            FROM invoices
            GROUP BY CustomerId
        )
        SELECT c.CustomerId, customer_totals.revenue
        FROM customers AS c
        JOIN customer_totals ON c.CustomerId = customer_totals.CustomerId
        """
    )

    assert result.referenced_tables == frozenset({"customers", "invoices"})


def test_validator_extracts_quoted_table_names(validator: SQLValidator) -> None:
    result = validator.validate('SELECT * FROM "Order"')

    assert result.referenced_tables == frozenset({"Order"})


def test_validator_does_not_treat_cte_alias_as_internal_table(
    validator: SQLValidator,
) -> None:
    result = validator.validate(
        """
        WITH sqlite_master AS (
            SELECT InvoiceId FROM invoices
        )
        SELECT * FROM sqlite_master
        """
    )

    assert result.referenced_tables == frozenset({"invoices"})


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO invoices (InvoiceId) VALUES (1)",
        "UPDATE invoices SET Total = 0",
        "DELETE FROM invoices",
        "DROP TABLE invoices",
        "ALTER TABLE invoices ADD COLUMN unsafe INTEGER",
        "CREATE TABLE unsafe (id INTEGER)",
    ],
)
def test_validator_rejects_non_select_statements(
    validator: SQLValidator,
    sql: str,
) -> None:
    with pytest.raises(SQLValidationError, match="only SELECT"):
        validator.validate(sql)


def test_validator_rejects_multiple_statements(validator: SQLValidator) -> None:
    with pytest.raises(SQLValidationError, match="exactly one statement"):
        validator.validate("SELECT * FROM invoices; SELECT * FROM customers")


def test_validator_rejects_unparsable_sql(validator: SQLValidator) -> None:
    with pytest.raises(SQLValidationError, match="could not be parsed"):
        validator.validate("SELECT FROM")


def test_validator_rejects_empty_sql(validator: SQLValidator) -> None:
    with pytest.raises(SQLValidationError, match="must not be empty"):
        validator.validate("   ")


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info(invoices)",
        "ATTACH DATABASE 'private.db' AS private",
        "DETACH DATABASE private",
    ],
)
def test_validator_rejects_sqlite_commands(
    validator: SQLValidator,
    sql: str,
) -> None:
    with pytest.raises(SQLValidationError):
        validator.validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pragma_table_info('invoices')",
        "SELECT load_extension('unsafe')",
    ],
)
def test_validator_rejects_unsafe_sqlite_functions(
    validator: SQLValidator,
    sql: str,
) -> None:
    with pytest.raises(SQLValidationError, match="unsafe SQL function"):
        validator.validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM main.invoices",
        "SELECT * FROM private.invoices",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM sqlite_schema",
    ],
)
def test_validator_rejects_unsupported_table_references(
    validator: SQLValidator,
    sql: str,
) -> None:
    with pytest.raises(SQLValidationError, match="unsupported table reference"):
        validator.validate(sql)


def test_validator_rejects_multiple_statement_attack_with_comment(
    validator: SQLValidator,
) -> None:
    with pytest.raises(SQLValidationError, match="exactly one statement"):
        validator.validate("SELECT * FROM invoices; -- comment\nDROP TABLE invoices")


def test_validator_accepts_semicolon_inside_comment(validator: SQLValidator) -> None:
    result = validator.validate("SELECT * FROM invoices /* ; DROP TABLE invoices */")

    assert result.referenced_tables == frozenset({"invoices"})
