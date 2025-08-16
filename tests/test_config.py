from pathlib import Path

import pytest

from agentviz.config import (
    CONFIG_DIR_ENV_VAR,
    LLMSettings,
    load_application_config,
    resolve_llm_api_key,
)
from agentviz.errors import ConfigurationError
from agentviz.models import DatabaseBackend


def write_config(
    tmp_path: Path,
    *,
    databases_yaml: str,
    users_yaml: str,
) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "databases.yaml").write_text(databases_yaml, encoding="utf-8")
    (config_dir / "users.yaml").write_text(users_yaml, encoding="utf-8")
    return config_dir


def test_load_application_config_from_yaml(tmp_path: Path) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
query:
  max_rows: 250
  timeout_seconds: 5
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
""",
    )

    config = load_application_config(config_dir)

    assert config.databases["chinook"].backend == DatabaseBackend.SQLITE
    assert config.databases["chinook"].path == Path("data/chinook.db")
    assert config.users["alice"].denied_databases == ["chinook"]
    assert config.query.max_rows == 250
    assert config.query.timeout_seconds == 5
    assert config.llm is None


def test_load_application_config_allows_empty_user_restrictions(
    tmp_path: Path,
) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
""",
        users_yaml="""
users: {}
""",
    )

    config = load_application_config(config_dir)

    assert config.users == {}


def test_load_application_config_parses_optional_llm_settings(
    tmp_path: Path,
) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
llm:
  provider: OpenAI
  model: gpt-4.1-mini
  visualization_model: gpt-4.1-nano
  api_key_env: AGENTVIZ_TEST_OPENAI_KEY
  temperature: 0.1
  timeout_seconds: 45
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
""",
    )

    config = load_application_config(config_dir)

    assert config.llm == LLMSettings(
        provider="openai",
        model="gpt-4.1-mini",
        visualization_model="gpt-4.1-nano",
        api_key_env="AGENTVIZ_TEST_OPENAI_KEY",
        temperature=0.1,
        timeout_seconds=45,
    )


def test_resolve_llm_api_key_reads_configured_environment_variable() -> None:
    settings = LLMSettings(model="gpt-4.1-mini", api_key_env="OPENAI_API_KEY")

    assert resolve_llm_api_key(
        settings,
        env={"OPENAI_API_KEY": "secret-key"},
    ) == "secret-key"


def test_resolve_llm_api_key_rejects_missing_key() -> None:
    settings = LLMSettings(model="gpt-4.1-mini", api_key_env="OPENAI_API_KEY")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        resolve_llm_api_key(settings, env={})


def test_load_application_config_uses_environment_config_dir(tmp_path: Path) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
""",
    )

    config = load_application_config(env={CONFIG_DIR_ENV_VAR: str(config_dir)})

    assert set(config.databases) == {"chinook"}


def test_load_application_config_rejects_missing_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(ConfigurationError, match="configuration file not found"):
        load_application_config(config_dir)


def test_load_application_config_rejects_unknown_user_database(
    tmp_path: Path,
) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - missing
""",
    )

    with pytest.raises(ConfigurationError, match="unknown database"):
        load_application_config(config_dir)


def test_load_application_config_rejects_duplicate_user_restrictions(
    tmp_path: Path,
) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
      - chinook
""",
    )

    with pytest.raises(
        ConfigurationError,
        match="denied database entries must be unique",
    ):
        load_application_config(config_dir)


def test_load_application_config_rejects_invalid_yaml_shape(tmp_path: Path) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
- not
- a
- mapping
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
""",
    )

    with pytest.raises(ConfigurationError, match="must contain a mapping"):
        load_application_config(config_dir)


def test_load_application_config_rejects_invalid_llm_settings(
    tmp_path: Path,
) -> None:
    config_dir = write_config(
        tmp_path,
        databases_yaml="""
databases:
  chinook:
    backend: sqlite
    path: data/chinook.db
llm:
  provider: "bad provider!"
  model: gpt-4.1-mini
""",
        users_yaml="""
users:
  alice:
    denied_databases:
      - chinook
""",
    )

    with pytest.raises(ConfigurationError, match="LLM provider"):
        load_application_config(config_dir)
