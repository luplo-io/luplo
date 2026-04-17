"""FastAPI application with lifespan-managed connection pool.

Run with::

    LUPLO_JWT_SECRET=$(openssl rand -hex 32) \\
    LUPLO_DB_URL=postgresql://localhost/luplo \\
        uvicorn luplo.server.app:app --reload

Set ``LUPLO_AUTH_DISABLED=1`` for solo dogfooding (dev only).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from luplo.core.backend.local import LocalBackend
from luplo.core.db import close_pool, create_pool
from luplo.server.auth.admin import ensure_admin
from luplo.server.auth.oauth import setup_oauth
from luplo.server.config import LuploServerSettings, fail_fast_check, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage settings, connection pool, backend, OAuth, and admin seed."""
    settings = load_settings()
    problems = fail_fast_check(settings)
    # Only hard-fail when auth is enabled; dev mode may skip JWT secret.
    auth_disabled = os.environ.get("LUPLO_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
    blocking = [p for p in problems if "JWT_SECRET" in p and not auth_disabled]
    if blocking:
        raise RuntimeError("Server config invalid: " + "; ".join(blocking))

    # Override db_url from env if provided (backwards compat with existing flow).
    db_url = os.environ.get("LUPLO_DB_URL", settings.db_url)

    pool = await create_pool(db_url)
    app.state.settings = settings
    app.state.pool = pool
    app.state.backend = LocalBackend(pool)
    app.state.oauth = setup_oauth(settings)

    # Seed admin (idempotent, no-op if admin_email/password not set).
    try:
        await ensure_admin(
            pool,
            email=settings.admin_email,
            password=settings.admin_password_initial,
        )
    except Exception as e:
        # Don't block startup on seed failure — log-equivalent print.
        print(f"[luplo] warning: admin seed skipped: {e}")

    yield
    await close_pool(pool)


app = FastAPI(
    title="luplo",
    description="AI memory that survives across sessions, teammates, and vendors.",
    version="0.0.1",
    lifespan=lifespan,
)

# Session middleware is needed for authlib OAuth state handling.
_session_secret = os.environ.get("LUPLO_SESSION_SECRET") or os.environ.get(
    "LUPLO_JWT_SECRET", "dev-session-secret-do-not-use-in-prod"
)
app.add_middleware(SessionMiddleware, secret_key=_session_secret)


# Register routers
from luplo.server.routes.auth import router as auth_router  # noqa: E402
from luplo.server.routes.items import router as items_router  # noqa: E402
from luplo.server.routes.projects import router as projects_router  # noqa: E402
from luplo.server.routes.search import router as search_router  # noqa: E402
from luplo.server.routes.work_units import router as work_units_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(items_router, prefix="/items", tags=["items"])
app.include_router(work_units_router, prefix="/work-units", tags=["work-units"])
app.include_router(search_router, prefix="/search", tags=["search"])


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


__all__ = ["LuploServerSettings", "app"]
