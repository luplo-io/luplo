"""OAuth client setup (GitHub + Google) via authlib.

OAuth providers are enabled only when both ``client_id`` and
``client_secret`` are set in settings. The returned ``OAuth`` instance is
registered on ``app.state.oauth`` at startup.
"""

from __future__ import annotations

from typing import Any, cast

from authlib.integrations.starlette_client import OAuth

from luplo.server.config import LuploServerSettings


def setup_oauth(settings: LuploServerSettings) -> OAuth:
    """Return an authlib OAuth registry with enabled providers.

    If neither GitHub nor Google credentials are configured, returns an
    empty registry — OAuth routes will return 404 for disabled providers.
    """
    # authlib ships incomplete type stubs for the registry: the ``register``
    # method's parameters are declared untyped, so pyright in strict mode
    # cannot verify keyword arguments.  Treat the registry as ``Any`` at
    # this boundary — runtime behaviour is covered by tests.
    oauth = OAuth()
    registry = cast("Any", oauth)
    if settings.github_enabled:
        registry.register(
            name="github",
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
    if settings.google_enabled:
        registry.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth


async def fetch_github_email(client: object, token: dict[str, object]) -> str | None:
    """Look up the authenticated GitHub user's primary verified email.

    GitHub may not return an email in the token payload if the user's
    primary email is private — use ``/user/emails`` to find the verified
    primary one.
    """
    # authlib's starlette OAuth2App does not ship typed method signatures
    # for .get() / response.json(); cast to ``Any`` at the boundary.
    app = cast("Any", client)
    resp = await app.get("user/emails", token=token)
    data = cast("list[dict[str, Any]]", resp.json())
    for entry in data:
        if entry.get("primary") and entry.get("verified"):
            email = entry.get("email")
            if isinstance(email, str):
                return email
    return None
