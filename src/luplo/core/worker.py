"""Unified background worker for sync jobs and glossary term extraction.

Runs as ``lp worker start`` (Local mode) or inside the FastAPI server
lifespan (Remote mode).  Uses PG LISTEN/NOTIFY with a 60-second fallback
poll to pick up work.

Channels:
- ``luplo_sync_jobs`` — notified when ``enqueue_sync`` creates/updates a job.
- ``luplo_new_items`` — notified when a new item is created (for glossary
  candidate extraction).  Post-v0.5.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from luplo.core.sync.queue import (
    complete_sync_job,
    fail_sync_job,
    get_ready_sync_jobs,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


async def run_worker(pool: AsyncConnectionPool) -> None:
    """Main worker loop.  Runs until cancelled.

    Listens for PG notifications on ``luplo_sync_jobs`` and falls back
    to polling every 60 seconds.  Each iteration claims ready sync jobs
    and processes them.

    Args:
        pool: Open connection pool to use for job queries.
    """
    logger.info("Worker starting — listening on luplo_sync_jobs")

    # Dedicated connection for LISTEN (not from pool — held long-term).
    # pool.conninfo is typed as AsyncConninfoParam (str | callable); our
    # pools are always constructed from a str URL so the narrow is safe.
    conninfo = pool.conninfo
    if not isinstance(conninfo, str):
        raise TypeError("Worker requires a connection pool built from a str URL")
    listen_conn: AsyncConnection[Any] = await AsyncConnection.connect(
        conninfo, autocommit=True
    )

    try:
        await listen_conn.execute("LISTEN luplo_sync_jobs")

        while True:
            # Process all ready jobs
            await _process_ready_jobs(pool)

            # Wait for notification or timeout
            try:
                gen = listen_conn.notifies(timeout=POLL_INTERVAL_SECONDS)
                async for notify in gen:
                    logger.debug("Received NOTIFY: %s", notify.channel)
                    break  # Got a notification, go process
            except TimeoutError:
                pass  # Fallback poll

    except asyncio.CancelledError:
        logger.info("Worker shutting down")
        raise
    finally:
        await listen_conn.close()


async def _process_ready_jobs(pool: AsyncConnectionPool) -> None:
    """Claim and process all mature sync jobs."""
    while True:
        async with pool.connection() as conn:
            jobs = await get_ready_sync_jobs(conn, limit=5)

        if not jobs:
            break

        for job in jobs:
            await _process_one_job(pool, job.id, job.payload)


async def _process_one_job(
    pool: AsyncConnectionPool, job_id: int, payload: str | None
) -> None:
    """Process a single sync job.

    v0.5: logs the job and marks it complete.  Actual Notion/Confluence
    sync logic (LLM-based section splitting, stable key matching) is
    deferred to v0.6.
    """
    try:
        logger.info("Processing sync job %d (%d bytes payload)", job_id, len(payload or ""))

        # v0.5 stub: no actual processing.
        # Post-v0.5 this will:
        #   1. Parse payload (markdown)
        #   2. LLM semantic segmentation
        #   3. Stable section key matching
        #   4. Upsert changed sections as items
        #   5. Record items_history
        #   6. Classify semantic_impact

        async with pool.connection() as conn:
            await complete_sync_job(conn, job_id)

        logger.info("Sync job %d completed", job_id)

    except Exception:
        logger.exception("Sync job %d failed", job_id)
        try:
            async with pool.connection() as conn:
                await fail_sync_job(conn, job_id, error=str(Exception))
        except Exception:
            logger.exception("Failed to record failure for job %d", job_id)
