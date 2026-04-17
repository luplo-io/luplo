"""Password reset flow — magic-link tokens.

Core logic is DB-only and sender-agnostic. The HTTP routes in
``server/routes/auth.py`` call :func:`request_reset` and
:func:`confirm_reset` with an injected :class:`~luplo.server.auth.email.EmailSender`.

Design:

- Reset tokens are single-use and short-lived (15 minutes).
- Plaintext is ``secrets.token_urlsafe(32)`` — cryptographically random.
- Only the argon2id hash is stored in ``auth_reset_tokens``; the
  plaintext is emailed to the user and never returns to the DB.
- :func:`request_reset` always succeeds silently: it returns the same
  shape whether the email exists or not, so callers cannot enumerate
  registered addresses via the endpoint.
- :func:`confirm_reset` rotates the password hash and marks the token
  used in a single transaction. It returns a bool so the caller can
  respond with generic success/failure; it never leaks *why* the
  verification failed.

Known gap (documented, not addressed in v0.6): existing issued JWTs
remain valid until their TTL. Session revocation on password reset
requires a token-denylist store that v0.5/0.6 does not have.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.actors import get_actor_by_email, set_password
from luplo.server.auth.email import EmailSender
from luplo.server.auth.password import WeakPasswordError, hash_password, verify_password

RESET_TOKEN_TTL = timedelta(minutes=15)
"""How long a reset token is valid. Longer means easier phishing."""


async def request_reset(
    conn: AsyncConnection[Any],
    *,
    email: str,
    sender: EmailSender,
    base_url: str,
) -> None:
    """Issue a reset token for *email* and email it to the user.

    Always returns silently, whether or not *email* is registered. This
    preserves the no-enumeration property — the caller's response shape
    is identical in both cases.

    The email body contains a URL the user can paste into a browser; the
    URL embeds the plaintext token (not the hash). The server stores
    only the hash.
    """
    actor = await get_actor_by_email(conn, email)
    if actor is None:
        return

    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_password(plaintext)
    expires_at = datetime.now(tz=UTC) + RESET_TOKEN_TTL

    await conn.execute(
        "INSERT INTO auth_reset_tokens (token_hash, actor_id, expires_at) VALUES (%s, %s, %s)",
        (token_hash, actor.id, expires_at),
    )

    reset_url = f"{base_url.rstrip('/')}/auth/reset-confirm?token={plaintext}"
    body = (
        f"Someone (hopefully you) requested a password reset for {email}.\n\n"
        f"To choose a new password, follow this link within 15 minutes:\n\n"
        f"  {reset_url}\n\n"
        f"If you did not request this, you can ignore this email — no "
        f"change will be made."
    )
    await sender.send(to=email, subject="luplo password reset", body=body)


async def confirm_reset(
    conn: AsyncConnection[Any],
    *,
    token_plaintext: str,
    new_password: str,
) -> bool:
    """Verify *token_plaintext* and rotate the owning actor's password.

    Returns ``True`` when the password was rotated; ``False`` for every
    failure path (unknown token, expired token, already-used token, weak
    password). Callers respond with a single generic message — never
    with a reason — to avoid leaking which of the failures occurred.

    The token is marked used atomically with the password rotation, so
    a concurrent replay attack cannot succeed twice.
    """
    try:
        new_hash = hash_password(new_password)
    except WeakPasswordError:
        return False

    now = datetime.now(tz=UTC)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT token_hash, actor_id, expires_at, used_at"
            " FROM auth_reset_tokens"
            " WHERE expires_at > %s AND used_at IS NULL",
            (now,),
        )
        rows = await cur.fetchall()

    matched_hash: str | None = None
    matched_actor: str | None = None
    for row in rows:
        if verify_password(token_plaintext, row["token_hash"]):
            matched_hash = row["token_hash"]
            matched_actor = str(row["actor_id"])
            break

    if matched_hash is None or matched_actor is None:
        return False

    # Atomically mark token used AND rotate password. If the UPDATE on the
    # token loses the race (used_at was set in the meantime), the
    # rotation is rolled back by the caller's transaction context.
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE auth_reset_tokens SET used_at = %s WHERE token_hash = %s AND used_at IS NULL",
            (now, matched_hash),
        )
        if cur.rowcount != 1:
            return False

    await set_password(conn, matched_actor, new_hash)
    return True
