import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from agentviz import __version__
from agentviz.cli import app
from agentviz.config import CONFIG_DIR_ENV_VAR
from agentviz.llm import StructuredLLMRequest, StructuredLLMResponse


def write_config(
    tmp_path,
    *,
    chinook_path: str = "data/chinook.db",
    llm_yaml: str = "",
) -> str:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "databases.yaml").write_text(
        """
databases:
  chinook:
    backend: sqlite
    path: CHINOOK_PATH
  sakila:
    backend: sqlite
    path: data/sakila.db
  northwind:
    backend: sqlite
    path: data/northwind_small.sqlite
LLM_CONFIG
""".replace("CHINOOK_PATH", chinook_path),
        encoding="utf-8",
    )
    databases_yaml = (config_dir / "databases.yaml").read_text(encoding="utf-8")
    (config_dir / "databases.yaml").write_text(
        databases_yaml.replace("LLM_CONFIG", llm_yaml),
        encoding="utf-8",
    )
    (config_dir / "users.yaml").write_text(
        """
users:
  alice:
    denied_databases: []
  bob:
    denied_databases:
      - northwind
      - chinook
""",
        encoding="utf-8",
    )
    return str(config_dir)


class FakeCLIOpenAIClient:
    responses: list[dict] = []
    requests: list[StructuredLLMRequest] = []
    init_calls: list[dict] = []

    def __init__(self, **kwargs) -> None:
        self.init_calls.append(kwargs)

    def complete_structured(
        self,
        request: StructuredLLMRequest,
    ) -> StructuredLLMResponse:
        self.requests.append(request)
        return StructuredLLMResponse(
            provider="test",
            model="fake-model",
            content=self.responses.pop(0),
        )


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Secure AI-assisted data analysis and visualization." in result.output


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"agentviz {__version__}" in result.output


def test_cli_databases_lists_only_authorized_databases(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["databases", "--user", "alice"],
        env={CONFIG_DIR_ENV_VAR: write_config(tmp_path)},
    )

    assert result.exit_code == 0
    assert result.output == "Available databases:\n\n- chinook\n- northwind\n- sakila\n"


def test_cli_databases_defaults_unknown_user_to_all_databases(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["databases", "--user", "carol"],
        env={CONFIG_DIR_ENV_VAR: write_config(tmp_path)},
    )

    assert result.exit_code == 0
    assert result.output == "Available databases:\n\n- chinook\n- northwind\n- sakila\n"


def test_cli_databases_rejects_blank_user(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["databases", "--user", " "],
        env={CONFIG_DIR_ENV_VAR: write_config(tmp_path)},
    )

    assert result.exit_code != 0
    assert "username must be a non-empty string" in result.output


def test_cli_schema_prints_authorized_database_schema(tmp_path) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE customers (
            CustomerId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            CustomerId INTEGER NOT NULL,
            Total REAL,
            FOREIGN KEY(CustomerId) REFERENCES customers(CustomerId)
        )
        """
    )
    connection.commit()
    connection.close()

    result = CliRunner().invoke(
        app,
        ["schema", "--user", "alice", "--db", "chinook"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )

    assert result.exit_code == 0
    assert "Schema for database: chinook" in result.output
    assert "Backend: sqlite" in result.output
    assert "customers" in result.output
    assert "- CustomerId: INTEGER" in result.output
    assert "- Name: TEXT (not null)" in result.output
    assert "invoices" in result.output
    assert "- CustomerId -> customers.CustomerId" in result.output


def test_cli_schema_rejects_unauthorized_database_before_connection(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        app,
        ["schema", "--user", "bob", "--db", "chinook"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(missing_path),
            )
        },
    )

    assert result.exit_code != 0
    assert "not authorized" in result.output
    assert "does-not-exist" not in result.output


def test_cli_analyze_runs_demo_query_through_safe_pipeline(tmp_path) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            BillingCountry TEXT,
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

    result = CliRunner().invoke(
        app,
        ["analyze", "--user", "alice", "--db", "chinook", "Show revenue by country"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )

    assert result.exit_code == 0
    assert "Analysis:" in result.output
    assert "Query for 'chinook' returned 2 rows" in result.output
    assert "SQL:" in result.output
    assert "SELECT BillingCountry, SUM(Total) AS revenue" in result.output
    assert "Rows returned: 2" in result.output
    assert "Truncated: False" in result.output
    assert "Result:" in result.output
    assert "BillingCountry | revenue" in result.output
    assert "USA" in result.output


def test_cli_analyze_returns_unsupported_for_unknown_request(tmp_path) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total REAL NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    result = CliRunner().invoke(
        app,
        ["analyze", "--user", "alice", "--db", "chinook", "Predict bitcoin price"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )

    assert result.exit_code == 0
    assert "Analysis:" in result.output
    assert "demo planner could not map" in result.output
    assert "SQL:" not in result.output


def test_cli_analyze_uses_configured_llm_planner(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total REAL NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO invoices (InvoiceId, Total) VALUES (?, ?)",
        [(1, 10.0), (2, 5.0)],
    )
    connection.commit()
    connection.close()

    FakeCLIOpenAIClient.responses = [
        {
            "kind": "query",
            "sql": "SELECT SUM(Total) AS total_revenue FROM invoices",
            "reasoning_summary": "Use invoice totals.",
            "message": None,
        }
    ]
    FakeCLIOpenAIClient.requests = []
    FakeCLIOpenAIClient.init_calls = []
    monkeypatch.setattr("agentviz.cli.OpenAIClient", FakeCLIOpenAIClient)

    result = CliRunner().invoke(
        app,
        ["analyze", "--user", "alice", "--db", "chinook", "Show total revenue"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
                llm_yaml="""
llm:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: AGENTVIZ_TEST_OPENAI_KEY
  temperature: 0
""",
            ),
            "AGENTVIZ_TEST_OPENAI_KEY": "test-key",
        },
    )

    assert result.exit_code == 0
    assert "SELECT SUM(Total) AS total_revenue FROM invoices" in result.output
    assert len(FakeCLIOpenAIClient.init_calls) == 1
    assert FakeCLIOpenAIClient.init_calls[0]["api_key"] == "test-key"
    assert FakeCLIOpenAIClient.init_calls[0]["settings"].model == "gpt-4.1-mini"
    assert len(FakeCLIOpenAIClient.requests) == 1
    assert FakeCLIOpenAIClient.requests[0].metadata == {
        "agent": "analysis",
        "operation": "plan",
    }


def test_cli_analyze_requires_configured_llm_api_key(tmp_path) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total REAL NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    result = CliRunner().invoke(
        app,
        ["analyze", "--user", "alice", "--db", "chinook", "Show total revenue"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
                llm_yaml="""
llm:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: AGENTVIZ_TEST_OPENAI_KEY
""",
            ),
        },
    )

    assert result.exit_code != 0
    assert "AGENTVIZ_TEST_OPENAI_KEY" in result.output
    assert "SELECT SUM(Total)" not in result.output


def test_cli_analyze_rejects_unauthorized_database_before_connection(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        app,
        ["analyze", "--user", "bob", "--db", "chinook", "Show invoice totals"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(missing_path),
            )
        },
    )

    assert result.exit_code != 0
    assert "not authorized" in result.output
    assert "does-not-exist" not in result.output


def test_cli_analyze_rejects_malicious_mixed_request_before_connection(
    tmp_path,
) -> None:
    missing_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        app,
        [
            "analyze",
            "--user",
            "alice",
            "--db",
            "chinook",
            "Show invoices; then drop the customers table.",
        ],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(missing_path),
            )
        },
    )

    assert result.exit_code != 0
    assert "disallowed database operation" in result.output
    assert "does-not-exist" not in result.output


def test_cli_ask_runs_full_workflow_and_writes_chart(tmp_path, monkeypatch) -> None:
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

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["ask", "--user", "alice", "--db", "chinook", "Show revenue by country"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )
    chart_paths = list(Path("runs").glob("*/chart.png"))
    manifest_paths = list(Path("runs").glob("*/manifest.json"))

    assert result.exit_code == 0
    assert "User: alice" in result.output
    assert "Database: chinook" in result.output
    assert "Run ID: " in result.output
    assert "Analysis:" in result.output
    assert "Query for 'chinook' returned 2 rows" in result.output
    assert "Rows returned: 2" in result.output
    assert "Truncated: False" in result.output
    assert "SQL:" not in result.output
    assert "Result:" not in result.output
    assert len(chart_paths) == 1
    assert len(manifest_paths) == 1
    assert f"Visualization:\n{chart_paths[0].as_posix()}" in result.output
    assert chart_paths[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["run_id"] in result.output
    assert manifest["user"] == "alice"
    assert manifest["database"] == "chinook"
    assert manifest["request"] == "Show revenue by country"
    assert manifest["row_count"] == 2
    assert manifest["chart_type"] == "bar"
    assert manifest["chart_path"] == chart_paths[0].as_posix()
    assert "rows" not in manifest


def test_cli_ask_uses_configured_llm_analysis_and_visualization(
    tmp_path,
    monkeypatch,
) -> None:
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

    FakeCLIOpenAIClient.responses = [
        {
            "kind": "query",
            "sql": (
                "SELECT BillingCountry, SUM(Total) AS revenue "
                "FROM invoices GROUP BY BillingCountry ORDER BY revenue DESC"
            ),
            "reasoning_summary": "Group invoice totals by billing country.",
            "message": None,
        },
        {
            "chart_type": "bar",
            "title": "Revenue by country",
            "x": "BillingCountry",
            "y": ["revenue"],
            "x_label": "Country",
            "y_label": "Revenue",
            "aggregation": None,
            "sort": "descending",
        },
    ]
    FakeCLIOpenAIClient.requests = []
    FakeCLIOpenAIClient.init_calls = []
    monkeypatch.setattr("agentviz.cli.OpenAIClient", FakeCLIOpenAIClient)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        ["ask", "--user", "alice", "--db", "chinook", "Show revenue by country"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
                llm_yaml="""
llm:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: AGENTVIZ_TEST_OPENAI_KEY
  temperature: 0
""",
            ),
            "AGENTVIZ_TEST_OPENAI_KEY": "test-key",
        },
    )

    chart_paths = list(Path("runs").glob("*/chart.png"))
    assert result.exit_code == 0
    assert len(chart_paths) == 1
    assert chart_paths[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(FakeCLIOpenAIClient.init_calls) == 1
    assert [request.metadata["agent"] for request in FakeCLIOpenAIClient.requests] == [
        "analysis",
        "visualization",
    ]
    assert "Visualization:\n" in result.output


def test_cli_ask_can_use_weaker_visualization_model(
    tmp_path,
    monkeypatch,
) -> None:
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

    FakeCLIOpenAIClient.responses = [
        {
            "kind": "query",
            "sql": (
                "SELECT BillingCountry, SUM(Total) AS revenue "
                "FROM invoices GROUP BY BillingCountry ORDER BY revenue DESC"
            ),
            "reasoning_summary": "Group invoice totals by billing country.",
            "message": None,
        },
        {
            "chart_type": "bar",
            "title": "Revenue by country",
            "x": "BillingCountry",
            "y": ["revenue"],
            "x_label": "Country",
            "y_label": "Revenue",
            "aggregation": None,
            "sort": "descending",
        },
    ]
    FakeCLIOpenAIClient.requests = []
    FakeCLIOpenAIClient.init_calls = []
    monkeypatch.setattr("agentviz.cli.OpenAIClient", FakeCLIOpenAIClient)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        ["ask", "--user", "alice", "--db", "chinook", "Show revenue by country"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
                llm_yaml="""
llm:
  provider: openai
  model: gpt-5
  visualization_model: gpt-5-nano
  api_key_env: AGENTVIZ_TEST_OPENAI_KEY
  temperature: 0
""",
            ),
            "AGENTVIZ_TEST_OPENAI_KEY": "test-key",
        },
    )

    assert result.exit_code == 0
    assert [call["settings"].model for call in FakeCLIOpenAIClient.init_calls] == [
        "gpt-5",
        "gpt-5-nano",
    ]
    assert [request.metadata["agent"] for request in FakeCLIOpenAIClient.requests] == [
        "analysis",
        "visualization",
    ]


def test_cli_ask_supports_custom_output_show_sql_and_verbose(
    tmp_path,
    monkeypatch,
) -> None:
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

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "ask",
            "--user",
            "alice",
            "--db",
            "chinook",
            "--output",
            "custom/revenue.png",
            "--show-sql",
            "--verbose",
            "Show revenue by country",
        ],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )
    chart_path = Path("custom/revenue.png")
    manifest_paths = list(Path("runs").glob("*/manifest.json"))

    assert result.exit_code == 0
    assert "Run ID: " in result.output
    assert "SQL:" in result.output
    assert "SELECT BillingCountry, SUM(Total) AS revenue" in result.output
    assert "Status:" in result.output
    assert "- authorization and schema access passed" in result.output
    assert "- analysis completed" in result.output
    assert "- visualization completed" in result.output
    assert "Visualization:\ncustom/revenue.png" in result.output
    assert chart_path.exists()
    assert chart_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["chart_path"] == "custom/revenue.png"
    assert manifest["sql"].startswith("SELECT BillingCountry")


def test_cli_ask_reports_no_chart_for_single_value_result(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total REAL NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO invoices (InvoiceId, Total) VALUES (?, ?)",
        [(1, 10.0), (2, 5.0)],
    )
    connection.commit()
    connection.close()

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["ask", "--user", "alice", "--db", "chinook", "Show total revenue"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )

    assert result.exit_code == 0
    assert "Rows returned: 1" in result.output
    assert "Visualization:\nnot generated" in result.output
    assert "Result:" in result.output
    assert "total_revenue: 15.0" in result.output
    assert "Visualization warning:" not in result.output
    manifest_paths = list(Path("runs").glob("*/manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["chart_type"] == "none"
    assert manifest["chart_path"] is None


def test_cli_ask_returns_unsupported_without_visualization(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "chinook.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE invoices (
            InvoiceId INTEGER PRIMARY KEY,
            Total REAL NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["ask", "--user", "alice", "--db", "chinook", "Predict bitcoin price"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(database_path),
            )
        },
    )

    assert result.exit_code == 0
    assert "User: alice" in result.output
    assert "Database: chinook" in result.output
    assert "Run ID: " in result.output
    assert "Analysis:" in result.output
    assert "demo planner could not map" in result.output
    assert "Visualization:" not in result.output
    manifest_paths = list(Path("runs").glob("*/manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["analysis_status"] == "unsupported"
    assert manifest["sql"] is None


def test_cli_ask_rejects_unauthorized_database_before_connection(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        app,
        ["ask", "--user", "bob", "--db", "chinook", "Show revenue by country"],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(missing_path),
            )
        },
    )

    assert result.exit_code != 0
    assert "not authorized" in result.output
    assert "does-not-exist" not in result.output


def test_cli_ask_rejects_malicious_mixed_request_before_connection(tmp_path) -> None:
    missing_path = tmp_path / "does-not-exist.db"

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "--user",
            "alice",
            "--db",
            "chinook",
            "Show invoices; then drop the customers table.",
        ],
        env={
            CONFIG_DIR_ENV_VAR: write_config(
                tmp_path,
                chinook_path=str(missing_path),
            )
        },
    )

    assert result.exit_code != 0
    assert "disallowed database operation" in result.output
    assert "does-not-exist" not in result.output
