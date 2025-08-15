# AgentViz

AgentViz is a take-home project for a secure, CLI-driven data analysis and
visualization system.

The intended final architecture has two AI agents:

- an Analysis Agent that makes semantic decisions about analytical intent and
  candidate SQL;
- a Visualization Agent that decides whether and how structured results should
  be visualized.

Security-sensitive responsibilities remain deterministic Python code:

- authorization;
- database connection management;
- schema inspection boundaries;
- SQL validation;
- read-only SQL execution;
- chart validation;
- chart rendering.

This repository is being built incrementally. The current milestone only
creates the project skeleton and a minimal CLI entrypoint. It does not contain
agents, database adapters, authorization, SQL execution, or rendering yet.

## Development

Install the project in editable mode:

```bash
python3 -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Check linting:

```bash
ruff check .
```

Check the CLI entrypoint:

```bash
agentviz --help
```

## Dataset Notes

The local sample SQLite databases are documented in
`docs/DATASET_NOTES.md`. The first recommended implementation database is
`data/chinook.db`.
