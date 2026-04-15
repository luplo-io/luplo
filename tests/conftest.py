"""Shared fixtures for luplo integration tests.

Every test runs inside a PG transaction that rolls back on teardown,
so tests never interfere with each other and the DB stays clean.
"""

from __future__ import annotations

import os
import subprocess

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

TEST_DB_NAME = "luplo_test"
DEFAULT_DB_URL = f"postgresql://postgres:localdb@localhost/{TEST_DB_NAME}"
DEFAULT_ADMIN_URL = "postgresql://postgres:localdb@localhost/postgres"

# ── Session-scoped: DB lifecycle ─────────────────────────────────


@pytest.fixture(scope="session")
def db_url() -> str:
    """Create a fresh test database and run all migrations.

    Yields the connection URL. Drops the database on teardown.
    Override with ``LUPLO_TEST_DB_URL`` env var to skip create/drop
    (useful for CI with pre-provisioned databases).
    """
    url = os.environ.get("LUPLO_TEST_DB_URL", "")
    managed = not url
    if not url:
        url = DEFAULT_DB_URL

    if managed:
        db_name = url.rsplit("/", 1)[-1]
        with psycopg.connect(
            DEFAULT_ADMIN_URL, autocommit=True
        ) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
            )
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    # Run alembic migrations
    project_root = os.path.dirname(os.path.dirname(__file__))
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=project_root,
        env={**os.environ, "LUPLO_DB_URL": url},
        check=True,
        capture_output=True,
    )

    yield url

    if managed:
        db_name = url.rsplit("/", 1)[-1]
        with psycopg.connect(
            DEFAULT_ADMIN_URL, autocommit=True
        ) as conn:
            # Terminate lingering connections before dropping
            conn.execute(
                sql.SQL(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = {} AND pid <> pg_backend_pid()"
                ).format(sql.Literal(db_name))
            )
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
            )


# ── Function-scoped: per-test isolation ──────────────────────────


@pytest_asyncio.fixture
async def conn(db_url: str) -> psycopg.AsyncConnection:  # type: ignore[type-arg]
    """Async PG connection wrapped in a transaction.

    Every test gets a clean view of the DB. All writes are rolled back
    after the test completes — no cleanup needed.
    """
    aconn = await psycopg.AsyncConnection.connect(db_url)
    try:
        yield aconn  # type: ignore[misc]
    finally:
        await aconn.rollback()
        await aconn.close()


# ── Helpers ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seed_project(conn: psycopg.AsyncConnection) -> str:  # type: ignore[type-arg]
    """Insert a default project and return its ID."""
    project_id = "test-project"
    await conn.execute(
        "INSERT INTO projects (id, name, description) VALUES (%s, %s, %s)"
        " ON CONFLICT (id) DO NOTHING",
        (project_id, "Test Project", "Fixture project for tests"),
    )
    return project_id


@pytest_asyncio.fixture
async def seed_actor(conn: psycopg.AsyncConnection) -> str:  # type: ignore[type-arg]
    """Insert a default actor and return its UUID.

    After 0002, actors.id is UUID. Use a fixed UUID so tests are deterministic.
    """
    actor_id = "00000000-0000-0000-0000-000000000001"
    await conn.execute(
        "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)"
        " ON CONFLICT (id) DO NOTHING",
        (actor_id, "Test User", "test@luplo.io"),
    )
    return actor_id


@pytest_asyncio.fixture
async def seed_item(
    conn: psycopg.AsyncConnection, seed_project: str, seed_actor: str  # type: ignore[type-arg]
) -> str:
    """Insert a default item and return its ID."""
    item_id = "test-item"
    await conn.execute(
        "INSERT INTO items (id, project_id, item_type, title, actor_id, search_tsv)"
        " VALUES (%s, %s, %s, %s, %s, to_tsvector('simple', %s))"
        " ON CONFLICT (id) DO NOTHING",
        (item_id, seed_project, "decision", "Test Decision", seed_actor, "Test Decision"),
    )
    return item_id
