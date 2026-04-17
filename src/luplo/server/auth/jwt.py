"""JWT issuance + validation (HS256 default)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from jwt.exceptions import InvalidTokenError

ISSUER = "luplo"


class TokenError(Exception):
    """Raised when a token is invalid, expired, or malformed."""


def issue_token(
    *,
    actor_id: str,
    email: str,
    secret: str,
    ttl_minutes: int,
    alg: str = "HS256",
    is_admin: bool = False,
) -> str:
    """Issue a signed JWT.

    Args:
        actor_id: UUID string of the actor.
        email: Actor email (non-sensitive identifier).
        secret: Signing secret.
        ttl_minutes: Lifetime in minutes.
        alg: JWT algorithm. Default HS256.
        is_admin: Optional admin flag claim.

    Returns:
        The encoded JWT.
    """
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": actor_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": ISSUER,
        "admin": bool(is_admin),
    }
    return pyjwt.encode(claims, secret, algorithm=alg)


def decode_token(token: str, *, secret: str, alg: str = "HS256") -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises:
        TokenError: If the token is invalid, expired, or has missing claims.
    """
    try:
        return pyjwt.decode(
            token,
            secret,
            algorithms=[alg],
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iss"]},
        )
    except InvalidTokenError as e:
        raise TokenError(str(e)) from e
