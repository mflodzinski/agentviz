from typer.testing import CliRunner

from agentviz import __version__
from agentviz.cli import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Secure AI-assisted data analysis and visualization." in result.output


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"agentviz {__version__}" in result.output
