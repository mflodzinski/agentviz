"""Application-specific exception types."""


class AgentVizError(Exception):
    """Base class for AgentViz errors."""


class ConfigurationError(AgentVizError):
    """Raised when application configuration cannot be loaded or validated."""


class IdentityError(AgentVizError):
    """Raised when a user identity cannot be resolved."""


class AuthorizationError(AgentVizError):
    """Raised when a user is not authorized for a requested resource."""


class DatabaseError(AgentVizError):
    """Base class for deterministic database-layer failures."""


class UnknownDatabaseError(DatabaseError):
    """Raised when a logical database name is not registered."""


class UnsupportedDatabaseBackendError(DatabaseError):
    """Raised when no adapter factory exists for a configured backend."""


class DatabaseConnectionError(DatabaseError):
    """Raised when a database connection cannot be established."""


class DatabaseSchemaError(DatabaseError):
    """Raised when database schema metadata cannot be inspected."""


class DatabaseExecutionError(DatabaseError):
    """Raised when query execution fails."""


class QueryTimeoutError(DatabaseExecutionError):
    """Raised when query execution exceeds its configured timeout."""


class SQLValidationError(AgentVizError):
    """Raised when SQL fails deterministic safety validation."""


class AgentInputError(AgentVizError):
    """Raised when an agent receives inconsistent deterministic input."""


class RequestSafetyError(AgentVizError):
    """Raised when a natural-language request contains disallowed intent."""


class LLMClientError(AgentVizError):
    """Raised when an LLM provider call or response cannot be normalized."""


class ChartValidationError(AgentVizError):
    """Raised when a chart specification is incompatible with analysis data."""


class ChartRenderingError(AgentVizError):
    """Raised when a chart cannot be rendered deterministically."""
