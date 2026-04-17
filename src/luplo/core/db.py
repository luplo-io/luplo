"""Database connection management.

Provides a thin wrapper around ``psycopg_pool.AsyncConnectionPool`` so the
rest of the codebase doesn't import pool internals directly.
"""

from __future__ import annotations

import os

from psycopg import AsyncConnection
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

DEFAULT_DB_URL = "postgresql://localhost/luplo"

# Type alias: the default pool type used throughout luplo.  Pools hand
# out ``AsyncConnection[TupleRow]`` which callers then rebind to
# ``dict_row`` via ``cursor(row_factory=dict_row)`` as needed.
Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]


async def create_pool(
    db_url: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> Pool:
    """Create and open an async connection pool.

    Args:
        db_url: PostgreSQL connection string.  Falls back to
            ``LUPLO_DB_URL`` env var, then ``postgresql://localhost/luplo``.
        min_size: Minimum connections kept open.
        max_size: Maximum concurrent connections.

    Returns:
        An open ``AsyncConnectionPool`` ready for use.
    """
    url = db_url or os.environ.get("LUPLO_DB_URL", DEFAULT_DB_URL)
    pool: Pool = AsyncConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True},
    )
    await pool.open()
    return pool


async def close_pool(pool: Pool) -> None:
    """Gracefully close a connection pool."""
    await pool.close()
