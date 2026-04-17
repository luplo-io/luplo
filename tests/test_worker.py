"""Tests for core/worker.py — sync job processing."""

from __future__ import annotations

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from luplo.core.sync.queue import enqueue_sync
from luplo.core.worker import _process_ready_jobs


@pytest_asyncio.fixture
async def pool(db_url: str) -> AsyncConnectionPool:
    """Create a connection pool for worker tests."""
    p = AsyncConnectionPool(db_url, min_size=1, max_size=3, open=False)
    await p.open()
    try:
        yield p  # type: ignore[misc]
    finally:
        await p.close()


@pytest.mark.asyncio
async def test_worker_processes_ready_job(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        job = await enqueue_sync(
            conn,
            source_type="notion",
            source_page_id="worker-test-1",
            payload="# Test content",
            debounce_seconds=0,
        )

    await _process_ready_jobs(pool)

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT status FROM sync_jobs WHERE id = %s", (job.id,))
        row = await cur.fetchone()
        assert row is not None
        assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_worker_skips_future_jobs(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        job = await enqueue_sync(
            conn,
            source_type="notion",
            source_page_id="worker-test-2",
            debounce_seconds=9999,
        )

    await _process_ready_jobs(pool)

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT status FROM sync_jobs WHERE id = %s", (job.id,))
        row = await cur.fetchone()
        assert row is not None
        assert row["status"] == "pending"  # not processed
