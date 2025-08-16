"""Simple identity resolution for CLI-provided users."""

from pydantic import ValidationError

from agentviz.errors import IdentityError
from agentviz.models import UserIdentity


def resolve_user_identity(username: str) -> UserIdentity:
    """Resolve a CLI username into a validated user identity.

    This is not real authentication. It only normalizes and validates the
    identity string that future deterministic authorization code will evaluate.
    """

    try:
        return UserIdentity(username=username)
    except ValidationError as exc:
        raise IdentityError("username must be a non-empty string") from exc
