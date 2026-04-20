"""FastAPI application with lifespan-managed connection pool.

Run with::

    LUPLO_DB_URL=postgresql://localhost/luplo \\
        uvicorn luplo.server.app:app --host 127.0.0.1 --reload

The server does not authenticate callers. Deploy it on a trusted
network (localhost, VPN) or behind a reverse proxy that handles
authentication. Pass ``X-Actor: <uuid>`` on write requests, or set
``LUPLO_DEFAULT_ACTOR_ID`` as a fallback, to tag audit entries.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from luplo.core.backend.local import LocalBackend
from luplo.core.db import close_pool, create_pool
from luplo.server.config import LuploServerSettings, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage settings, connection pool, and backend."""
    settings = load_settings()

    # Override db_url from env if provided (backwards compat with existing flow).
    db_url = os.environ.get("LUPLO_DB_URL", settings.db_url)

    pool = await create_pool(db_url)
    app.state.settings = settings
    app.state.pool = pool
    app.state.backend = LocalBackend(pool)

    yield
    await close_pool(pool)


app = FastAPI(
    title="luplo",
    description="AI memory that survives across sessions, teammates, and vendors.",
    version="0.7.0",
    lifespan=lifespan,
)


# Register routers
from luplo.server.routes.checks import router as checks_router  # noqa: E402
from luplo.server.routes.items import router as items_router  # noqa: E402
from luplo.server.routes.projects import router as projects_router  # noqa: E402
from luplo.server.routes.search import router as search_router  # noqa: E402
from luplo.server.routes.work_units import router as work_units_router  # noqa: E402

app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(items_router, prefix="/items", tags=["items"])
app.include_router(work_units_router, prefix="/work-units", tags=["work-units"])
app.include_router(search_router, prefix="/search", tags=["search"])
app.include_router(checks_router, prefix="/checks", tags=["checks"])


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — reports only that the process is up."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness probe — confirms the DB connection pool is usable."""
    pool = app.state.pool
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
    return {"status": "ready"}


__all__ = ["LuploServerSettings", "app"]
