"""Tests for server/auth/password.py (argon2id)."""

from __future__ import annotations

import pytest

from luplo.server.auth.password import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    hash_password,
    verify_password,
)


def test_hash_round_trip() -> None:
    hashed = hash_password("correcthorsebattery")
    assert hashed.startswith("$argon2")
    assert verify_password("correcthorsebattery", hashed) is True


def test_wrong_password_rejected() -> None:
    hashed = hash_password("correcthorsebattery")
    assert verify_password("wrongpassword1", hashed) is False


def test_weak_password_rejected() -> None:
    with pytest.raises(WeakPasswordError):
        hash_password("a" * (MIN_PASSWORD_LENGTH - 1))


def test_malformed_hash_returns_false() -> None:
    assert verify_password("whatever1234", "not-a-valid-hash") is False


def test_hash_is_salted() -> None:
    h1 = hash_password("samepassword")
    h2 = hash_password("samepassword")
    assert h1 != h2
    assert verify_password("samepassword", h1)
    assert verify_password("samepassword", h2)
