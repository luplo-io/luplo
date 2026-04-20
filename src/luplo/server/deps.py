"""FastAPI dependencies — attribution only, no authentication.

The server is expected to run on a trusted network (localhost, a VPN,
or behind a reverse proxy that handles auth). Every write-side handler
requires an ``actor_id`` to record attribution — it is supplied either
by an ``X-Actor`` request header (trusted proxy or SaaS wrapper sets
it) or by the ``default_actor_id`` server setting (solo/dev mode).

No token is validated, no identity is verified. Treat ``actor_id`` as
a label, not a principal.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

ACTOR_HEADER = "x-actor"


def require_actor_id(
    request: Request,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> str:
    """Resolve the writing ``actor_id`` for the current request.

    Order of precedence:

    1. ``X-Actor`` header (UUID string).
    2. ``settings.default_actor_id`` if set.
    3. HTTP 400 otherwise.
    """
    if x_actor:
        return x_actor
    settings = request.app.state.settings
    default = getattr(settings, "default_actor_id", "") or ""
    if default:
        return default
    raise HTTPException(
        status_code=400,
        detail="Missing X-Actor header and no default_actor_id configured.",
    )
