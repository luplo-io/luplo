"""Tests for server/auth/jwt.py (HS256 issue + decode)."""

from __future__ import annotations

import time

import pytest

from luplo.server.auth.jwt import ISSUER, TokenError, decode_token, issue_token

SECRET = "test-secret-minimum-32-bytes-long!"
ACTOR = "00000000-0000-0000-0000-000000000010"
EMAIL = "jwt-test@luplo.io"


def test_round_trip() -> None:
    tok = issue_token(
        actor_id=ACTOR,
        email=EMAIL,
        secret=SECRET,
        ttl_minutes=5,
    )
    claims = decode_token(tok, secret=SECRET)
    assert claims["sub"] == ACTOR
    assert claims["email"] == EMAIL
    assert claims["iss"] == ISSUER
    assert claims["admin"] is False


def test_admin_flag() -> None:
    tok = issue_token(
        actor_id=ACTOR,
        email=EMAIL,
        secret=SECRET,
        ttl_minutes=5,
        is_admin=True,
    )
    claims = decode_token(tok, secret=SECRET)
    assert claims["admin"] is True


def test_wrong_secret_rejected() -> None:
    tok = issue_token(
        actor_id=ACTOR,
        email=EMAIL,
        secret=SECRET,
        ttl_minutes=5,
    )
    with pytest.raises(TokenError):
        decode_token(tok, secret="different-secret-that-does-not-match")


def test_expired_token_rejected() -> None:
    tok = issue_token(
        actor_id=ACTOR,
        email=EMAIL,
        secret=SECRET,
        ttl_minutes=0,
    )
    time.sleep(1)
    with pytest.raises(TokenError):
        decode_token(tok, secret=SECRET)


def test_malformed_token_rejected() -> None:
    with pytest.raises(TokenError):
        decode_token("not.a.token", secret=SECRET)
