"""Command-line entrypoint for AgentViz."""

from pathlib import Path
from typing import Annotated

import typer

from agentviz import __version__
from agentviz.agents import (
    AnalysisAgent,
    DemoAnalysisPlanner,
    DemoVisualizationPlanner,
    LLMAnalysisPlanner,
    LLMVisualizationPlanner,
    VisualizationAgent,
)
from agentviz.analysis import AnalysisExecutionService, validate_request_safety
from agentviz.auth import (
    AclPolicyEngine,
    AuthorizedSchemaService,
    resolve_user_identity,
)
from agentviz.config import (
    ApplicationConfig,
    LLMSettings,
    load_application_config,
    resolve_llm_api_key,
)
from agentviz.database import DatabaseRegistry
from agentviz.errors import AgentVizError, ConfigurationError, IdentityError
from agentviz.llm import (
    LLMClient,
    LLMIORecorder,
    OpenAIClient,
    RecordingLLMClient,
    write_llm_io_trace,
)
from agentviz.models import (
    AnalysisAgentStatus,
    AnalysisArtifact,
    AnalysisRequest,
    ApplicationRunResult,
    ChartType,
    DatabaseMetadata,
    ScalarValue,
)
from agentviz.orchestrator import ApplicationOrchestrator
from agentviz.runs import (
    default_chart_output_path,
    default_manifest_output_path,
    generate_run_id,
    write_run_manifest,
)
from agentviz.visualization import ChartRenderer

app = typer.Typer(
    add_completion=False,
    help="Secure AI-assisted data analysis and visualization.",
)

RESULT_DISPLAY_ROW_LIMIT = 10
RESULT_DISPLAY_CELL_LIMIT = 80
MAX_INTERACTIVE_CLARIFICATIONS = 2


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


@app.command()
def databases(
    user: str = typer.Option(
        ...,
        "--user",
        help="Configured username whose database access should be listed.",
    ),
) -> None:
    """List databases the configured user is authorized to access."""

    try:
        identity = resolve_user_identity(user)
        config = load_application_config()
    except (ConfigurationError, IdentityError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    policy = AclPolicyEngine(config.users, all_databases=set(config.databases))
    database_names = policy.authorized_databases(identity)

    typer.echo("Available databases:")
    if not database_names:
        typer.echo()
        typer.echo("(none)")
        return

    typer.echo()
    for database_name in database_names:
        typer.echo(f"- {database_name}")


@app.command()
def schema(
    user: str = typer.Option(
        ...,
        "--user",
        help="Configured username requesting schema access.",
    ),
    db: str = typer.Option(
        ...,
        "--db",
        help="Logical database name to inspect.",
    ),
) -> None:
    """Show schema for an authorized logical database."""

    try:
        identity = resolve_user_identity(user)
        config = load_application_config()
        policy = AclPolicyEngine(config.users, all_databases=set(config.databases))
        registry = DatabaseRegistry(config.databases)
        schema_service = AuthorizedSchemaService(policy=policy, registry=registry)
        metadata = schema_service.get_schema(identity, db)
    except (AgentVizError, ConfigurationError, IdentityError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    _print_schema(metadata)


@app.command()
def analyze(
    question: str = typer.Argument(..., help="Natural-language analysis request."),
    user: str = typer.Option(
        ...,
        "--user",
        help="Configured username requesting analysis.",
    ),
    db: str = typer.Option(
        ...,
        "--db",
        help="Logical database name to analyze.",
    ),
) -> None:
    """Run an analysis-only request using the configured safe query pipeline."""

    try:
        identity = resolve_user_identity(user)
        config = load_application_config()
        policy = AclPolicyEngine(config.users, all_databases=set(config.databases))
        registry = DatabaseRegistry(config.databases)
        schema_service = AuthorizedSchemaService(policy=policy, registry=registry)
        execution_service = AnalysisExecutionService(
            policy=policy,
            registry=registry,
            query_settings=config.query,
        )
        request = AnalysisRequest(
            user=identity,
            database=db,
            question=question,
            include_visualization=False,
        )
        validate_request_safety(request)
        metadata = schema_service.get_schema(identity, db)
        agent = AnalysisAgent(
            planner=_build_analysis_planner(config),
            execution_service=execution_service,
        )
        result = agent.run(request=request, schema=metadata)
    except (AgentVizError, ConfigurationError, IdentityError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("Analysis:")
    if result.status != AnalysisAgentStatus.COMPLETED:
        typer.echo(result.message or result.status)
        return

    if result.artifact is None:
        raise typer.BadParameter("completed analysis result did not include artifact")

    artifact = result.artifact
    typer.echo(artifact.summary)
    typer.echo()
    typer.echo("SQL:")
    typer.echo(artifact.sql)
    typer.echo()
    typer.echo(f"Rows returned: {artifact.row_count}")
    typer.echo(f"Truncated: {artifact.truncated}")
    _print_result_preview(artifact)


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural-language analysis request."),
    user: str = typer.Option(
        ...,
        "--user",
        help="Configured username requesting analysis.",
    ),
    db: str = typer.Option(
        ...,
        "--db",
        help="Logical database name to analyze.",
    ),
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help=(
                "Where to write the rendered chart. Defaults to "
                "runs/<run_id>/chart.png."
            ),
        ),
    ] = None,
    show_sql: Annotated[
        bool,
        typer.Option(
            "--show-sql",
            help="Print the SQL that was validated and executed.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Print additional deterministic workflow status.",
        ),
    ] = False,
    save_llm_io: Annotated[
        bool,
        typer.Option(
            "--save-llm-io",
            help=(
                "Write readable LLM prompts, response schemas, and structured "
                "outputs to runs/<run_id>/llm_io.json."
            ),
        ),
    ] = False,
    llm_io_output: Annotated[
        Path | None,
        typer.Option(
            "--llm-io-output",
            help=(
                "Where to write LLM input/output JSON. Requires "
                "--save-llm-io."
            ),
        ),
    ] = None,
) -> None:
    """Run the complete analysis and visualization workflow."""

    if llm_io_output is not None and not save_llm_io:
        raise typer.BadParameter("--llm-io-output requires --save-llm-io")

    try:
        identity = resolve_user_identity(user)
        config = load_application_config()
        policy = AclPolicyEngine(config.users, all_databases=set(config.databases))
        registry = DatabaseRegistry(config.databases)
        execution_service = AnalysisExecutionService(
            policy=policy,
            registry=registry,
            query_settings=config.query,
        )
        llm_io_recorder = LLMIORecorder() if save_llm_io else None
        analysis_llm_client = (
            _build_llm_client(config.llm) if config.llm is not None else None
        )
        if analysis_llm_client is not None and llm_io_recorder is not None:
            analysis_llm_client = RecordingLLMClient(
                analysis_llm_client,
                llm_io_recorder,
            )
        visualization_llm_client = _build_visualization_llm_client(
            config.llm,
            analysis_llm_client=analysis_llm_client,
            llm_io_recorder=llm_io_recorder,
        )
        orchestrator = ApplicationOrchestrator(
            schema_service=AuthorizedSchemaService(
                policy=policy,
                registry=registry,
            ),
            analysis_agent=AnalysisAgent(
                planner=_build_analysis_planner(
                    config,
                    llm_client=analysis_llm_client,
                ),
                execution_service=execution_service,
            ),
            visualization_agent=VisualizationAgent(
                planner=_build_visualization_planner(
                    config,
                    llm_client=visualization_llm_client,
                ),
            ),
            renderer=ChartRenderer(),
        )
        run_id = generate_run_id()
        chart_output_path = output or default_chart_output_path(run_id)
        request = AnalysisRequest(
            user=identity,
            database=db,
            question=question,
            include_visualization=True,
        )
        result, request = _run_with_interactive_clarifications(
            orchestrator=orchestrator,
            request=request,
            chart_output_path=chart_output_path,
            run_id=run_id,
        )
        manifest_path = write_run_manifest(
            request=request,
            result=result,
            output_path=default_manifest_output_path(run_id),
        )
        written_llm_io_path = (
            write_llm_io_trace(
                llm_io_recorder,
                llm_io_output or Path("runs") / run_id / "llm_io.json",
            )
            if llm_io_recorder is not None
            else None
        )
    except (AgentVizError, ConfigurationError, IdentityError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    _print_application_result(
        result,
        user=user,
        database=db,
        manifest_path=manifest_path,
        show_sql=show_sql,
        verbose=verbose,
    )
    if written_llm_io_path is not None:
        typer.echo()
        typer.echo("LLM IO:")
        typer.echo(written_llm_io_path)


def _run_with_interactive_clarifications(
    *,
    orchestrator: ApplicationOrchestrator,
    request: AnalysisRequest,
    chart_output_path: Path,
    run_id: str,
) -> tuple[ApplicationRunResult, AnalysisRequest]:
    current_request = request
    clarification_count = 0
    while True:
        result = orchestrator.run(
            request=current_request,
            chart_output_path=chart_output_path,
            run_id=run_id,
        )
        if result.analysis.status != AnalysisAgentStatus.NEEDS_CLARIFICATION:
            return result, current_request
        if clarification_count >= MAX_INTERACTIVE_CLARIFICATIONS:
            return result, current_request

        typer.echo("Analysis needs clarification:")
        typer.echo(result.analysis.message or "Please clarify the request.")
        answer = typer.prompt("Your clarification").strip()
        if not answer:
            raise typer.BadParameter("clarification response must be non-empty")

        current_request = current_request.model_copy(
            update={
                "question": _append_clarification_answer(
                    question=current_request.question,
                    clarification=result.analysis.message
                    or "Please clarify the request.",
                    answer=answer,
                )
            }
        )
        clarification_count += 1


def _append_clarification_answer(
    *,
    question: str,
    clarification: str,
    answer: str,
) -> str:
    return "\n\n".join(
        [
            f"Original request:\n{question}",
            f"Analysis agent clarification question:\n{clarification}",
            f"User clarification answer:\n{answer}",
        ]
    )


def _print_schema(metadata: DatabaseMetadata) -> None:
    typer.echo(f"Schema for database: {metadata.name}")
    typer.echo(f"Backend: {metadata.backend}")
    typer.echo()

    for table in metadata.tables:
        typer.echo(f"{table.name}")
        for column in table.columns:
            flags = []
            if column.primary_key:
                flags.append("pk")
            if not column.nullable:
                flags.append("not null")
            suffix = f" ({', '.join(flags)})" if flags else ""
            typer.echo(f"  - {column.name}: {column.data_type}{suffix}")

        if table.foreign_keys:
            typer.echo("  foreign keys:")
            for foreign_key in table.foreign_keys:
                typer.echo(
                    f"  - {foreign_key.column} -> "
                    f"{foreign_key.referenced_table}.{foreign_key.referenced_column}"
                )

        typer.echo()


def _build_analysis_planner(
    config: ApplicationConfig,
    *,
    llm_client: LLMClient | None = None,
):
    if config.llm is None:
        return DemoAnalysisPlanner()

    return LLMAnalysisPlanner(
        client=llm_client or _build_llm_client(config.llm),
        temperature=config.llm.temperature,
    )


def _build_visualization_planner(
    config: ApplicationConfig,
    *,
    llm_client: LLMClient | None = None,
):
    if config.llm is None:
        return DemoVisualizationPlanner()

    return LLMVisualizationPlanner(
        client=llm_client or _build_llm_client(_visualization_llm_settings(config.llm)),
        temperature=config.llm.temperature,
    )


def _build_llm_client(settings: LLMSettings) -> LLMClient:
    api_key = resolve_llm_api_key(settings)
    if settings.provider == "openai":
        return OpenAIClient(settings=settings, api_key=api_key)

    raise ConfigurationError(f"unsupported LLM provider: {settings.provider}")


def _build_visualization_llm_client(
    settings: LLMSettings | None,
    *,
    analysis_llm_client: LLMClient | None,
    llm_io_recorder: LLMIORecorder | None = None,
) -> LLMClient | None:
    if settings is None:
        return None

    visualization_settings = _visualization_llm_settings(settings)
    if visualization_settings == settings:
        return analysis_llm_client
    visualization_llm_client = _build_llm_client(visualization_settings)
    if llm_io_recorder is not None:
        return RecordingLLMClient(visualization_llm_client, llm_io_recorder)
    return visualization_llm_client


def _visualization_llm_settings(settings: LLMSettings) -> LLMSettings:
    if settings.visualization_model is None:
        return settings
    return settings.model_copy(update={"model": settings.visualization_model})


def _print_application_result(
    result: ApplicationRunResult,
    *,
    user: str,
    database: str,
    manifest_path: Path,
    show_sql: bool,
    verbose: bool,
) -> None:
    typer.echo(f"User: {user}")
    typer.echo(f"Database: {database}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo()
    typer.echo("Analysis:")
    if result.analysis.status != AnalysisAgentStatus.COMPLETED:
        typer.echo(f"Status: {result.analysis.status}")
        typer.echo(result.analysis.message or result.analysis.status)
        if verbose:
            typer.echo()
            typer.echo(f"Manifest: {manifest_path}")
        return

    if result.analysis.artifact is None:
        raise typer.BadParameter("completed analysis result did not include artifact")

    artifact = result.analysis.artifact
    typer.echo(artifact.summary)
    typer.echo()
    if show_sql:
        typer.echo("SQL:")
        typer.echo(artifact.sql)
        typer.echo()
    typer.echo(f"Rows returned: {artifact.row_count}")
    typer.echo(f"Truncated: {artifact.truncated}")

    if verbose:
        typer.echo()
        typer.echo("Status:")
        typer.echo("- authorization and schema access passed")
        typer.echo("- analysis completed")
        typer.echo(f"- manifest written: {manifest_path}")

    if result.visualization_warning is not None:
        _print_result_preview(artifact)
        typer.echo()
        typer.echo(f"Visualization warning: {result.visualization_warning}")
        return

    if result.chart_spec is None:
        _print_result_preview(artifact)
        return

    typer.echo()
    typer.echo("Visualization:")
    if result.chart_spec.chart_type == ChartType.NONE:
        typer.echo(f"not generated ({result.chart_spec.title})")
        _print_result_preview(artifact)
        return

    if result.chart_path is None:
        typer.echo(f"not generated ({result.chart_spec.title})")
        _print_result_preview(artifact)
        return

    typer.echo(result.chart_path)
    if verbose:
        typer.echo("- visualization completed")


def _print_result_preview(artifact: AnalysisArtifact) -> None:
    typer.echo()
    typer.echo("Result:")
    if not artifact.rows:
        typer.echo("(no rows)")
        return

    if len(artifact.columns) == 1 and len(artifact.rows) == 1:
        column = artifact.columns[0]
        typer.echo(f"{column}: {_format_result_value(artifact.rows[0][column])}")
        return

    rows = artifact.rows[:RESULT_DISPLAY_ROW_LIMIT]
    rendered_rows = [
        [_format_result_value(row[column]) for column in artifact.columns]
        for row in rows
    ]
    widths = [
        max(len(column), *(len(row[index]) for row in rendered_rows))
        for index, column in enumerate(artifact.columns)
    ]

    typer.echo(_format_result_row(artifact.columns, widths))
    typer.echo(_format_result_row(["-" * width for width in widths], widths))
    for row in rendered_rows:
        typer.echo(_format_result_row(row, widths))

    if artifact.row_count > len(rows):
        typer.echo(f"... {artifact.row_count - len(rows)} more row(s) not shown")


def _format_result_row(values: list[str], widths: list[int]) -> str:
    return " | ".join(value.ljust(widths[index]) for index, value in enumerate(values))


def _format_result_value(value: ScalarValue) -> str:
    if value is None:
        rendered = "NULL"
    else:
        rendered = str(value)

    if len(rendered) <= RESULT_DISPLAY_CELL_LIMIT:
        return rendered
    return rendered[: RESULT_DISPLAY_CELL_LIMIT - 3] + "..."


def main() -> None:
    app()
