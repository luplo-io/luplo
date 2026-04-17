"""Integration tests for core/sync/queue.py."""

from __future__ import annotations

import pytest
from psycopg.rows import dict_row

from luplo.core.sync.queue import (
    complete_sync_job,
    enqueue_sync,
    fail_sync_job,
    get_ready_sync_jobs,
)


@pytest.mark.asyncio
async def test_enqueue_creates_job(conn: object) -> None:
    job = await enqueue_sync(
        conn,  # type: ignore[arg-type]
        source_type="notion",
        source_page_id="page-1",
        payload="# Hello",
        source_event_id="evt-1",
        debounce_seconds=0,  # immediate for testing
    )

    assert job.id is not None
    assert job.source_type == "notion"
    assert job.source_page_id == "page-1"
    assert job.payload == "# Hello"
    assert job.status == "pending"
    assert job.attempts == 0


@pytest.mark.asyncio
async def test_enqueue_debounce_merges(conn: object) -> None:
    job1 = await enqueue_sync(
        conn,  # type: ignore[arg-type]
        source_type="notion",
        source_page_id="page-1",
        payload="Version 1",
        debounce_seconds=300,
    )
    job2 = await enqueue_sync(
        conn,  # type: ignore[arg-type]
        source_type="notion",
        source_page_id="page-1",
        payload="Version 2",
        debounce_seconds=300,
    )

    # Same job ID — merged, not duplicated
    assert job2.id == job1.id
    assert job2.payload == "Version 2"


@pytest.mark.asyncio
async def test_enqueue_different_pages_separate(conn: object) -> None:
    job1 = await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="page-1",
        debounce_seconds=0,  # type: ignore[arg-type]
    )
    job2 = await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="page-2",
        debounce_seconds=0,  # type: ignore[arg-type]
    )

    assert job1.id != job2.id


@pytest.mark.asyncio
async def test_get_ready_returns_mature_jobs(conn: object) -> None:
    await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="ready",
        debounce_seconds=0,  # type: ignore[arg-type]
    )

    jobs = await get_ready_sync_jobs(conn, limit=10)  # type: ignore[arg-type]
    assert len(jobs) == 1
    assert jobs[0].source_page_id == "ready"
    assert jobs[0].status == "processing"


@pytest.mark.asyncio
async def test_get_ready_skips_future_jobs(conn: object) -> None:
    await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="future",
        debounce_seconds=9999,  # type: ignore[arg-type]
    )

    jobs = await get_ready_sync_jobs(conn, limit=10)  # type: ignore[arg-type]
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_get_ready_skips_already_processing(conn: object) -> None:
    await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="p1",
        debounce_seconds=0,  # type: ignore[arg-type]
    )
    # Claim it
    claimed = await get_ready_sync_jobs(conn, limit=1)  # type: ignore[arg-type]
    assert len(claimed) == 1

    # Second call should find nothing
    more = await get_ready_sync_jobs(conn, limit=1)  # type: ignore[arg-type]
    assert len(more) == 0


@pytest.mark.asyncio
async def test_complete_sync_job(conn: object) -> None:
    job = await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="done",
        debounce_seconds=0,  # type: ignore[arg-type]
    )
    await complete_sync_job(conn, job.id)  # type: ignore[arg-type]

    async with conn.cursor(row_factory=dict_row) as cur:  # type: ignore[union-attr]
        await cur.execute("SELECT status FROM sync_jobs WHERE id = %s", (job.id,))
        row = await cur.fetchone()
        assert row is not None
        assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_fail_sync_job_retry(conn: object) -> None:
    job = await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="retry",
        debounce_seconds=0,  # type: ignore[arg-type]
    )
    await fail_sync_job(conn, job.id, error="timeout")  # type: ignore[arg-type]

    async with conn.cursor(row_factory=dict_row) as cur:  # type: ignore[union-attr]
        await cur.execute(
            "SELECT status, attempts, last_error FROM sync_jobs WHERE id = %s",
            (job.id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["status"] == "pending"  # back to retryable
        assert row["attempts"] == 1
        assert row["last_error"] == "timeout"


@pytest.mark.asyncio
async def test_fail_sync_job_permanent_after_3(conn: object) -> None:
    job = await enqueue_sync(
        conn,
        source_type="notion",
        source_page_id="dead",
        debounce_seconds=0,  # type: ignore[arg-type]
    )
    for i in range(3):
        await fail_sync_job(conn, job.id, error=f"fail {i}")  # type: ignore[arg-type]

    async with conn.cursor(row_factory=dict_row) as cur:  # type: ignore[union-attr]
        await cur.execute("SELECT status, attempts FROM sync_jobs WHERE id = %s", (job.id,))
        row = await cur.fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert row["attempts"] == 3
