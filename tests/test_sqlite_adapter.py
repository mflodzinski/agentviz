import sqlite3
from pathlib import Path

import pytest

from agentviz.database import DatabaseAdapter, SQLiteAdapter
from agentviz.errors import DatabaseConnectionError, DatabaseExecutionError
from agentviz.models import DatabaseBackend, DatabaseConfig


@pytest.fixture()
def sqlite_database(tmp_path: Path) -> Path:
    path = tmp_path / "sample.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE artists (
            ArtistId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL
        );

        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            ArtistId INTEGER NOT NULL REFERENCES artists(ArtistId),
            Total NUMERIC NOT NULL
        );

        INSERT INTO artists (ArtistId, Name)
        VALUES
            (1, 'AC/DC'),
            (2, 'Accept');

        INSERT INTO invoices (InvoiceId, ArtistId, Total)
        VALUES
            (1, 1, 1.98),
            (2, 1, 3.96),
            (3, 2, 0.99);
        """
    )
    connection.close()
    return path


def test_sqlite_adapter_satisfies_database_adapter_protocol(
    sqlite_database: Path,
) -> None:
    adapter = SQLiteAdapter(name="sample", path=sqlite_database)

    assert isinstance(adapter, DatabaseAdapter)


def test_sqlite_adapter_can_be_created_from_database_config(
    sqlite_database: Path,
) -> None:
    config = DatabaseConfig(
        name="sample",
        backend=DatabaseBackend.SQLITE,
        path=sqlite_database,
    )

    adapter = SQLiteAdapter.from_config(config)

    assert adapter.name == "sample"
    assert adapter.backend == DatabaseBackend.SQLITE


def test_sqlite_adapter_inspects_schema(sqlite_database: Path) -> None:
    adapter = SQLiteAdapter(name="sample", path=sqlite_database)

    schema = adapter.get_schema()
    tables = {table.name: table for table in schema.tables}

    assert schema.name == "sample"
    assert schema.backend == DatabaseBackend.SQLITE
    assert set(tables) == {"artists", "invoices"}
    assert tables["artists"].row_count == 2
    assert tables["invoices"].row_count == 3
    assert {column.name for column in tables["invoices"].columns} == {
        "InvoiceId",
        "ArtistId",
        "Total",
    }
    assert tables["invoices"].foreign_keys[0].column == "ArtistId"
    assert tables["invoices"].foreign_keys[0].referenced_table == "artists"
    assert tables["invoices"].foreign_keys[0].referenced_column == "ArtistId"


def test_sqlite_adapter_executes_query_with_row_limit(sqlite_database: Path) -> None:
    adapter = SQLiteAdapter(name="sample", path=sqlite_database)

    result = adapter.execute_query(
        "SELECT InvoiceId, Total FROM invoices ORDER BY InvoiceId",
        max_rows=2,
        timeout_seconds=5,
    )

    assert result.columns == ["InvoiceId", "Total"]
    assert result.rows == [
        {"InvoiceId": 1, "Total": 1.98},
        {"InvoiceId": 2, "Total": 3.96},
    ]
    assert result.row_count == 2
    assert result.truncated is True


def test_sqlite_adapter_uses_read_only_connection(sqlite_database: Path) -> None:
    adapter = SQLiteAdapter(name="sample", path=sqlite_database)

    with pytest.raises(DatabaseExecutionError):
        adapter.execute_query(
            "INSERT INTO artists (ArtistId, Name) VALUES (3, 'Write Attempt')",
            max_rows=1,
            timeout_seconds=5,
        )

    connection = sqlite3.connect(sqlite_database)
    count = connection.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    connection.close()

    assert count == 2


def test_sqlite_adapter_reports_missing_database(tmp_path: Path) -> None:
    adapter = SQLiteAdapter(name="missing", path=tmp_path / "missing.db")

    with pytest.raises(DatabaseConnectionError, match="not found"):
        adapter.get_schema()
