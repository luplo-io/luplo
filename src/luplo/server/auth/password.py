"""Password hashing — argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    """Raised when a password does not meet the minimum strength requirement."""


def hash_password(plain: str) -> str:
    """Hash *plain* with argon2id.

    Args:
        plain: The plaintext password.

    Returns:
        The encoded argon2id hash.

    Raises:
        WeakPasswordError: If *plain* is shorter than ``MIN_PASSWORD_LENGTH``.
    """
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Check *plain* against *hashed*. Returns ``False`` on mismatch or
    malformed hash. Does not raise on unexpected errors."""
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash, wrong algorithm, etc.
        return False
