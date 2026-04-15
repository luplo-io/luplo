"""FastAPI dependencies for authentication.

When ``LUPLO_AUTH_DISABLED=1`` is set (solo dogfooding), all requests are
treated as coming from a default actor (UUID ``00000000-...-000``). In
production, JWT validation is enforced.

The token may come from an ``Authorization: Bearer <token>`` header or a
``luplo_token`` cookie — CLI uses the header, browser sessions use the
cookie.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from luplo.core.actors import get_actor
from luplo.server.auth.jwt import TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)

DEFAULT_ACTOR_UUID = "00000000-0000-0000-0000-000000000000"
DEFAULT_ACTOR_EMAIL = "dev@local"

AUTH_COOKIE = "luplo_token"


def _is_auth_disabled() -> bool:
    """Evaluated per-request so tests can toggle the env var freely."""
    return os.environ.get("LUPLO_AUTH_DISABLED", "").lower() in (
        "1", "true", "yes",
    )


@dataclass(slots=True)
class CurrentActor:
    """Resolved actor identity for the current request."""

    id: str  # UUID string
    email: str
    is_admin: bool


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie = request.cookies.get(AUTH_COOKIE)
    if cookie:
        return cookie
    return None


async def get_current_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentActor:
    """Resolve the current actor from the request.

    When auth is disabled, returns a default actor. Otherwise validates
    the JWT (from Authorization header or auth cookie) and looks up the
    referenced actor in the DB.

    Raises:
        HTTPException: 401 if auth is enabled and no valid token is
            provided, or the referenced actor no longer exists.
    """
    if _is_auth_disabled():
        # Allow tests / dev to override which actor stands in for "current".
        actor_id = os.environ.get("LUPLO_ACTOR_ID", DEFAULT_ACTOR_UUID)
        return CurrentActor(
            id=actor_id,
            email=DEFAULT_ACTOR_EMAIL,
            is_admin=True,
        )

    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    settings = request.app.state.settings
    try:
        claims = decode_token(token, secret=settings.jwt_secret, alg=settings.jwt_alg)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e

    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")

    pool = request.app.state.pool
    async with pool.connection() as conn:
        actor = await get_actor(conn, sub)
    if actor is None:
        raise HTTPException(status_code=401, detail="Actor no longer exists")

    return CurrentActor(id=actor.id, email=actor.email, is_admin=actor.is_admin)
