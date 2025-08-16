import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from agentviz.cli import app
from agentviz.config import CONFIG_DIR_ENV_VAR


def create_e2e_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            BillingCountry TEXT NOT NULL,
            Total REAL NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO invoices (InvoiceId, BillingCountry, Total) VALUES (?, ?, ?)",
        [
            (1, "USA", 10.0),
            (2, "USA", 5.0),
            (3, "Canada", 7.5),
        ],
    )
    connection.commit()
    connection.close()
    return database_path


def create_e2e_config(tmp_path: Path, database_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "databases.yaml").write_text(
        f"""
databases:
  chinook:
    backend: sqlite
    path: {database_path}
query:
  max_rows: 100
  timeout_seconds: 5
""",
        encoding="utf-8",
    )
    (config_dir / "users.yaml").write_text(
        """
users:
  alice:
    denied_databases: []
""",
        encoding="utf-8",
    )
    return config_dir


def test_evaluation_full_end_to_end_cli_analysis_visualization_and_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = create_e2e_database(tmp_path)
    config_dir = create_e2e_config(tmp_path, database_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "--user",
            "alice",
            "--db",
            "chinook",
            "--show-sql",
            "Show revenue by country",
        ],
        env={CONFIG_DIR_ENV_VAR: str(config_dir)},
    )

    chart_paths = list(Path("runs").glob("*/chart.png"))
    manifest_paths = list(Path("runs").glob("*/manifest.json"))
    assert result.exit_code == 0
    assert "User: alice" in result.output
    assert "Database: chinook" in result.output
    assert "Run ID: " in result.output
    assert "SQL:" in result.output
    assert "SELECT BillingCountry, SUM(Total) AS revenue FROM invoices" in (
        result.output
    )
    assert "Rows returned: 2" in result.output
    assert "Visualization:" in result.output
    assert len(chart_paths) == 1
    assert len(manifest_paths) == 1
    assert chart_paths[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["user"] == "alice"
    assert manifest["database"] == "chinook"
    assert manifest["request"] == "Show revenue by country"
    assert manifest["analysis_status"] == "completed"
    assert manifest["row_count"] == 2
    assert manifest["chart_type"] == "bar"
    assert manifest["chart_path"] == chart_paths[0].as_posix()
    assert "rows" not in manifest
