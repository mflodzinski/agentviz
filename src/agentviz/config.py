"""Application configuration loading."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from agentviz.errors import ConfigurationError
from agentviz.models.core import AgentVizModel, DatabaseConfig

DEFAULT_CONFIG_DIR = Path("config")
CONFIG_DIR_ENV_VAR = "AGENTVIZ_CONFIG_DIR"


class QuerySettings(AgentVizModel):
    """Configurable query resource limits."""

    max_rows: int = Field(default=5000, ge=1)
    timeout_seconds: int = Field(default=10, ge=1)


class LLMSettings(AgentVizModel):
    """Provider-neutral configuration for future LLM clients."""

    provider: str = Field(default="openai", min_length=1)
    model: str = Field(min_length=1)
    visualization_model: str | None = Field(default=None, min_length=1)
    api_key_env: str = Field(default="OPENAI_API_KEY", min_length=1)
    temperature: float = Field(default=0, ge=0, le=2)
    timeout_seconds: int = Field(default=30, ge=1)

    @field_validator("provider")
    @classmethod
    def provider_must_be_simple_identifier(cls, provider: str) -> str:
        normalized = provider.lower()
        if not normalized.replace("-", "_").replace("_", "").isalnum():
            raise ValueError("LLM provider must be a simple identifier")
        return normalized


class UserAccessConfig(AgentVizModel):
    """Database deny-list for one configured user."""

    denied_databases: list[str] = Field(default_factory=list)

    @field_validator("denied_databases")
    @classmethod
    def denied_database_names_must_be_unique(
        cls,
        denied_databases: list[str],
    ) -> list[str]:
        if len(denied_databases) != len(set(denied_databases)):
            raise ValueError("user denied database entries must be unique")
        return denied_databases


class ApplicationConfig(AgentVizModel):
    """Typed application configuration assembled from YAML files."""

    databases: dict[str, DatabaseConfig] = Field(min_length=1)
    users: dict[str, UserAccessConfig] = Field(default_factory=dict)
    query: QuerySettings = Field(default_factory=QuerySettings)
    llm: LLMSettings | None = None

    @model_validator(mode="after")
    def validate_cross_references(self) -> ApplicationConfig:
        for database_name, database in self.databases.items():
            if database.name != database_name:
                raise ValueError(
                    f"database key '{database_name}' must match configured "
                    f"name '{database.name}'"
                )

        known_databases = set(self.databases)
        for username, access in self.users.items():
            unknown = set(access.denied_databases) - known_databases
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(
                    f"user '{username}' denies unknown database(s): {names}"
                )

        return self


def load_application_config(
    config_dir: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> ApplicationConfig:
    """Load application configuration from YAML files.

    The config directory defaults to `config/`, or to `AGENTVIZ_CONFIG_DIR` when
    that environment variable is set.
    """

    resolved_config_dir = _resolve_config_dir(config_dir, env or os.environ)
    databases_yaml = _read_yaml_mapping(resolved_config_dir / "databases.yaml")
    users_yaml = _read_yaml_mapping(resolved_config_dir / "users.yaml")

    try:
        databases = _parse_databases(databases_yaml)
        users = _parse_users(users_yaml)
        query = QuerySettings.model_validate(databases_yaml.get("query", {}))
        llm = _parse_llm(databases_yaml)
        return ApplicationConfig(
            databases=databases,
            users=users,
            query=query,
            llm=llm,
        )
    except ValidationError as exc:
        raise ConfigurationError(f"invalid configuration: {exc}") from exc
    except ValueError as exc:
        raise ConfigurationError(f"invalid configuration: {exc}") from exc


def _resolve_config_dir(
    config_dir: Path | None,
    env: Mapping[str, str],
) -> Path:
    if config_dir is not None:
        return config_dir

    configured = env.get(CONFIG_DIR_ENV_VAR)
    if configured:
        return Path(configured)

    return DEFAULT_CONFIG_DIR


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"configuration file not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ConfigurationError(f"configuration file must contain a mapping: {path}")

    return data


def _parse_databases(data: Mapping[str, Any]) -> dict[str, DatabaseConfig]:
    raw_databases = data.get("databases")
    if not isinstance(raw_databases, dict):
        raise ConfigurationError("databases.yaml must contain a 'databases' mapping")

    return {
        name: DatabaseConfig.model_validate({"name": name, **raw_config})
        for name, raw_config in raw_databases.items()
    }


def _parse_users(data: Mapping[str, Any]) -> dict[str, UserAccessConfig]:
    raw_users = data.get("users", {})
    if not isinstance(raw_users, dict):
        raise ConfigurationError("users.yaml must contain a 'users' mapping")

    return {
        username: UserAccessConfig.model_validate(raw_config)
        for username, raw_config in raw_users.items()
    }


def _parse_llm(data: Mapping[str, Any]) -> LLMSettings | None:
    raw_llm = data.get("llm")
    if raw_llm is None:
        return None
    if not isinstance(raw_llm, dict):
        raise ConfigurationError("llm configuration must be a mapping")

    return LLMSettings.model_validate(raw_llm)


def resolve_llm_api_key(
    settings: LLMSettings,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the configured API key without storing it in config files."""

    api_key = (env or os.environ).get(settings.api_key_env)
    if not api_key or not api_key.strip():
        raise ConfigurationError(
            f"LLM API key environment variable is not set: {settings.api_key_env}"
        )
    return api_key
