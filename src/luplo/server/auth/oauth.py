"""OAuth client setup (GitHub + Google) via authlib.

OAuth providers are enabled only when both ``client_id`` and
``client_secret`` are set in settings. The returned ``OAuth`` instance is
registered on ``app.state.oauth`` at startup.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from luplo.server.config import LuploServerSettings


def setup_oauth(settings: LuploServerSettings) -> OAuth:
    """Return an authlib OAuth registry with enabled providers.

    If neither GitHub nor Google credentials are configured, returns an
    empty registry — OAuth routes will return 404 for disabled providers.
    """
    oauth = OAuth()
    if settings.github_enabled:
        oauth.register(
            name="github",
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
    if settings.google_enabled:
        oauth.register(
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
    # Typed as object to avoid pulling authlib types into the public API.
    from authlib.integrations.starlette_client import StarletteOAuth2App

    app: StarletteOAuth2App = client  # type: ignore[assignment]
    resp = await app.get("user/emails", token=token)
    data = resp.json()
    for entry in data:
        if entry.get("primary") and entry.get("verified"):
            email = entry.get("email")
            if isinstance(email, str):
                return email
    return None
