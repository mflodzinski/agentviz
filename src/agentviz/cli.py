"""Command-line entrypoint for AgentViz."""

import typer

from agentviz import __version__

app = typer.Typer(
    add_completion=False,
    help="Secure AI-assisted data analysis and visualization.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agentviz {__version__}")
        raise typer.Exit


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the AgentViz version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Secure AI-assisted data analysis and visualization."""


def main() -> None:
    app()
