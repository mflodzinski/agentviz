import pytest

from agentviz.auth import resolve_user_identity
from agentviz.errors import IdentityError
from agentviz.models import UserIdentity


def test_resolve_user_identity_returns_validated_identity() -> None:
    identity = resolve_user_identity(" alice ")

    assert identity == UserIdentity(username="alice")


def test_resolve_user_identity_rejects_blank_username() -> None:
    with pytest.raises(IdentityError, match="non-empty"):
        resolve_user_identity("   ")
