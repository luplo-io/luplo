"""Tests for the password-reset flow (server/auth/reset.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from luplo.core.actors import create_actor
from luplo.server.auth.email import EmailSender
from luplo.server.auth.password import hash_password, verify_password
from luplo.server.auth.reset import confirm_reset, request_reset


class _CapturingSender:
    """Records whatever would have been emailed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})


def _assert_is_sender(sender: EmailSender) -> None:
    """Structural sanity — EmailSender is a Protocol; runtime check is shape."""
    assert hasattr(sender, "send")


def _extract_token(body: str) -> str:
    """Pull the reset-token query param out of the email body."""
    for line in body.splitlines():
        line = line.strip()
        if "token=" in line:
            return line.split("token=", 1)[1].strip()
    raise AssertionError("no token= found in email body")


async def _seeded_actor(conn: Any, email: str, password: str = "initial-pwd12345") -> str:
    actor = await create_actor(
        conn,
        name="Reset User",
        email=email,
        password_hash=hash_password(password),
    )
    return actor.id


@pytest.mark.asyncio
async def test_request_reset_sends_email_for_known_address(conn: Any) -> None:
    await _seeded_actor(conn, "reset-happy@luplo.io")
    sender = _CapturingSender()
    _assert_is_sender(sender)

    await request_reset(conn, email="reset-happy@luplo.io", sender=sender, base_url="http://x")

    assert len(sender.calls) == 1
    assert sender.calls[0]["to"] == "reset-happy@luplo.io"
    assert "token=" in sender.calls[0]["body"]


@pytest.mark.asyncio
async def test_request_reset_is_silent_for_unknown_address(conn: Any) -> None:
    """No enumeration: unknown email must not email anything, must not raise."""
    sender = _CapturingSender()

    await request_reset(
        conn,
        email="definitely-not-registered@luplo.io",
        sender=sender,
        base_url="http://x",
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_confirm_reset_rotates_password_and_marks_token_used(conn: Any) -> None:
    actor_id = await _seeded_actor(conn, "reset-rotate@luplo.io", password="initial-pwd12345")
    sender = _CapturingSender()
    await request_reset(conn, email="reset-rotate@luplo.io", sender=sender, base_url="http://x")
    token = _extract_token(sender.calls[0]["body"])

    ok = await confirm_reset(conn, token_plaintext=token, new_password="new-pwd-67890ab")

    assert ok is True
    async with conn.cursor() as cur:
        await cur.execute("SELECT password_hash FROM actors WHERE id = %s", (actor_id,))
        new_hash_row = await cur.fetchone()
        assert new_hash_row is not None
        new_hash = new_hash_row[0]

    assert verify_password("new-pwd-67890ab", new_hash)
    assert not verify_password("initial-pwd12345", new_hash)


@pytest.mark.asyncio
async def test_confirm_reset_rejects_reuse(conn: Any) -> None:
    """A token must not work twice (single-use)."""
    await _seeded_actor(conn, "reset-reuse@luplo.io")
    sender = _CapturingSender()
    await request_reset(conn, email="reset-reuse@luplo.io", sender=sender, base_url="http://x")
    token = _extract_token(sender.calls[0]["body"])

    first = await confirm_reset(conn, token_plaintext=token, new_password="new-pwd-67890ab")
    second = await confirm_reset(conn, token_plaintext=token, new_password="second-try-77777")

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_confirm_reset_rejects_expired_token(conn: Any) -> None:
    """Manually age the token row past its expires_at."""
    await _seeded_actor(conn, "reset-expired@luplo.io")
    sender = _CapturingSender()
    await request_reset(conn, email="reset-expired@luplo.io", sender=sender, base_url="http://x")
    token = _extract_token(sender.calls[0]["body"])

    past = datetime.now(tz=UTC) - timedelta(minutes=30)
    await conn.execute("UPDATE auth_reset_tokens SET expires_at = %s", (past,))

    ok = await confirm_reset(conn, token_plaintext=token, new_password="new-pwd-67890ab")

    assert ok is False


@pytest.mark.asyncio
async def test_confirm_reset_rejects_unknown_token(conn: Any) -> None:
    ok = await confirm_reset(
        conn,
        token_plaintext="not-a-real-token-xxxxxxxxxxxxxxxx",
        new_password="new-pwd-67890ab",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_confirm_reset_rejects_weak_new_password(conn: Any) -> None:
    """Too-short new password is one of the four failure paths — same return shape."""
    await _seeded_actor(conn, "reset-weak@luplo.io")
    sender = _CapturingSender()
    await request_reset(conn, email="reset-weak@luplo.io", sender=sender, base_url="http://x")
    token = _extract_token(sender.calls[0]["body"])

    ok = await confirm_reset(conn, token_plaintext=token, new_password="short")
    assert ok is False
