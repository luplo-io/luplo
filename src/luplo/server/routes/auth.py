"""Authentication endpoints.

All endpoints are mounted under ``/auth``.

- ``GET  /login`` — HTML form
- ``POST /login`` — form (email, password); returns JSON ``{token}`` +
  sets a cookie. Accepts JSON body too.
- ``GET  /oauth/{provider}/start`` — begins an OAuth flow (browser path).
- ``GET  /oauth/{provider}/callback`` — handles the provider callback.
- ``POST /logout`` — clears the auth cookie.
- ``GET  /whoami`` — returns the authenticated actor.
- ``POST /token/refresh`` — issues a fresh token for the current actor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from luplo.core.actors import (
    create_actor,
    get_actor,
    get_actor_by_email,
    touch_login,
)
from luplo.server.auth.deps import CurrentActor, get_current_actor
from luplo.server.auth.domain_filter import is_allowed_domain
from luplo.server.auth.email import email_sender_from_env
from luplo.server.auth.jwt import issue_token
from luplo.server.auth.oauth import fetch_github_email
from luplo.server.auth.password import verify_password
from luplo.server.auth.reset import confirm_reset, request_reset
from luplo.server.config import LuploServerSettings

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "auth" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

AUTH_COOKIE = "luplo_token"


def _settings(request: Request) -> LuploServerSettings:
    return request.app.state.settings


def _pool(request: Request):
    return request.app.state.pool


def _issue_for(actor_id: str, email: str, is_admin: bool, settings: LuploServerSettings) -> str:
    return issue_token(
        actor_id=actor_id,
        email=email,
        is_admin=is_admin,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_ttl_minutes,
        alg=settings.jwt_alg,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    settings = _settings(request)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": request.query_params.get("error"),
            "github_enabled": settings.github_enabled,
            "google_enabled": settings.google_enabled,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> JSONResponse:
    settings = _settings(request)
    pool = _pool(request)
    async with pool.connection() as conn:
        actor = await get_actor_by_email(conn, email)
        if not actor or not actor.password_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(password, actor.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        await touch_login(conn, actor.id)
    token = _issue_for(actor.id, actor.email, actor.is_admin, settings)
    resp = JSONResponse({"token": token, "email": actor.email})
    resp.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.jwt_ttl_minutes * 60,
    )
    return resp


@router.get("/oauth/{provider}/start")
async def oauth_start(request: Request, provider: str) -> RedirectResponse:
    oauth = request.app.state.oauth
    client = getattr(oauth, provider, None)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured")
    settings = _settings(request)
    redirect_uri = f"{settings.base_url.rstrip('/')}/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str) -> JSONResponse:
    oauth = request.app.state.oauth
    client = getattr(oauth, provider, None)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured")
    settings = _settings(request)
    token = await client.authorize_access_token(request)

    # Resolve email
    email: str | None = None
    if provider == "google":
        userinfo = token.get("userinfo")
        if userinfo:
            email = userinfo.get("email")
    elif provider == "github":
        email = await fetch_github_email(client, token)
        if not email:
            # Fallback: try /user endpoint's public email
            resp = await client.get("user", token=token)
            data = resp.json()
            email = data.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="Could not resolve email from provider")

    if not is_allowed_domain(email, settings.allowed_email_domains):
        raise HTTPException(status_code=403, detail="Email domain not allowed")

    pool = _pool(request)
    async with pool.connection() as conn:
        actor = await get_actor_by_email(conn, email)
        if not actor:
            if not settings.auto_create_users:
                raise HTTPException(status_code=403, detail="User not registered")
            actor = await create_actor(
                conn,
                name=email.split("@", 1)[0],
                email=email,
                role="user",
                oauth_provider=provider,
            )
        await touch_login(conn, actor.id)

    jwt_token = _issue_for(actor.id, actor.email, actor.is_admin, settings)
    resp = JSONResponse({"token": jwt_token, "email": actor.email})
    resp.set_cookie(
        AUTH_COOKIE,
        jwt_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.jwt_ttl_minutes * 60,
    )
    return resp


@router.post("/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE)
    return resp


@router.get("/whoami")
async def whoami(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
) -> dict[str, object]:
    return {"id": actor.id, "email": actor.email, "is_admin": actor.is_admin}


@router.post("/token/refresh")
async def token_refresh(
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
) -> JSONResponse:
    settings = _settings(request)
    pool = _pool(request)
    async with pool.connection() as conn:
        full = await get_actor(conn, actor.id)
    if not full:
        raise HTTPException(status_code=401, detail="Actor no longer exists")
    token = _issue_for(full.id, full.email, full.is_admin, settings)
    return JSONResponse({"token": token, "email": full.email})


@router.post("/reset-request")
async def reset_request(
    request: Request,
    email: Annotated[str, Form()],
) -> JSONResponse:
    """Start a password reset.

    Returns 200 unconditionally — same shape whether *email* is
    registered or not, so the endpoint cannot be used to enumerate
    accounts. If the email exists, a reset link is emailed via the
    configured :class:`~luplo.server.auth.email.EmailSender`.
    """
    settings = _settings(request)
    pool = _pool(request)
    sender = email_sender_from_env()
    async with pool.connection() as conn:
        await request_reset(
            conn,
            email=email,
            sender=sender,
            base_url=settings.base_url,
        )
    return JSONResponse({"ok": True})


@router.post("/reset-confirm")
async def reset_confirm(
    request: Request,
    token: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> JSONResponse:
    """Complete a password reset.

    Returns 200 on success. A single 400 "Invalid or expired token" on
    every failure path — unknown token, expired token, already-used
    token, or a new password that fails the strength check.
    """
    pool = _pool(request)
    async with pool.connection() as conn:
        ok = await confirm_reset(conn, token_plaintext=token, new_password=new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return JSONResponse({"ok": True})
