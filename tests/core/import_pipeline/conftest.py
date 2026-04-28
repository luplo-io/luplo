"""Shared fixtures for import pipeline tests.

The import pipeline tests exercise real PG round-trips through the
``LocalBackend``. They cannot reuse the per-test rollback ``conn``
fixture from the project root conftest because the backend acquires
its own pooled connections. Instead, we open a function-scoped pool
and isolate tests by using fresh UUID-based project/actor ids.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass

import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from luplo.core.backend.local import LocalBackend


@dataclass(slots=True)
class _FreshProject:
    """A throwaway project row with a stable ``id`` attribute."""

    id: str


@pytest_asyncio.fixture
async def db_pool(db_url: str) -> AsyncConnectionPool:
    """Open a per-test psycopg AsyncConnectionPool against the test DB."""
    pool = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        yield pool  # type: ignore[misc]
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def local_backend(db_pool: AsyncConnectionPool) -> LocalBackend:
    """Yield a ``LocalBackend`` wired to the per-test connection pool."""
    yield LocalBackend(db_pool)  # type: ignore[misc]


@pytest_asyncio.fixture
async def fresh_project(db_pool: AsyncConnectionPool) -> _FreshProject:
    """Create a throwaway project row and return an object with ``.id``."""
    pid = f"test-{uuidlib.uuid4().hex[:12]}"
    async with db_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO projects (id, name, description) VALUES (%s, %s, %s)",
            (pid, f"test-project-{pid}", "import-pipeline test fixture"),
        )
    return _FreshProject(id=pid)


@pytest_asyncio.fixture
async def fresh_actor(db_pool: AsyncConnectionPool) -> str:
    """Create a throwaway actor row and return its UUID."""
    aid = str(uuidlib.uuid4())
    async with db_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
            (aid, "test-actor", f"{aid}@test.example"),
        )
    return aid
