"""Debounce queue for external document sync jobs.

When a page is updated multiple times in rapid succession (e.g. a writer
editing a Notion doc), only a single sync job runs after a configurable
debounce window.  The ``sync_jobs`` table enforces at most one active
(pending or processing) job per ``(source_type, source_page_id)`` via a
partial unique index.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.models import SyncJob

_COLUMNS = (
    "id",
    "source_type",
    "source_page_id",
    "source_event_id",
    "payload",
    "scheduled_at",
    "status",
    "attempts",
    "last_error",
    "created_at",
    "updated_at",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_job(row: dict[str, Any]) -> SyncJob:
    """Convert a dict-row into a ``SyncJob`` dataclass."""
    return SyncJob(**row)


async def enqueue_sync(
    conn: AsyncConnection[Any],
    *,
    source_type: str,
    source_page_id: str,
    payload: str | None = None,
    source_event_id: str | None = None,
    debounce_seconds: int = 300,
) -> SyncJob:
    """Add or merge a sync job into the debounce queue.

    If a pending/processing job already exists for the same page, its
    ``scheduled_at`` is bumped and ``payload`` is replaced (the latest
    content wins).  Otherwise a new job is inserted.

    Args:
        conn: Async psycopg connection.
        source_type: Origin system (e.g. ``"notion"``, ``"slack"``).
        source_page_id: External page/channel identifier.
        payload: Latest page content (markdown or raw text).
        source_event_id: External event ID for idempotency.
        debounce_seconds: Seconds to wait before processing (default 300).

    Returns:
        The created or updated ``SyncJob``.
    """
    params: dict[str, Any] = {
        "source_type": source_type,
        "source_page_id": source_page_id,
        "payload": payload,
        "source_event_id": source_event_id,
        "debounce": debounce_seconds,
    }

    # Try to merge into existing pending/processing job
    update_query = sql.SQL(
        "UPDATE sync_jobs SET"
        "  payload = %(payload)s,"
        "  source_event_id = %(source_event_id)s,"
        "  scheduled_at = now() + make_interval(secs => %(debounce)s),"
        "  updated_at = now()"
        " WHERE source_type = %(source_type)s"
        "   AND source_page_id = %(source_page_id)s"
        "   AND status IN ('pending', 'processing')"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(update_query, params)
        row = await cur.fetchone()
        if row:
            return _row_to_job(row)

    # No existing job — insert new one
    insert_query = sql.SQL(
        "INSERT INTO sync_jobs"
        " (source_type, source_page_id, payload, source_event_id, scheduled_at)"
        " VALUES (%(source_type)s, %(source_page_id)s, %(payload)s,"
        "  %(source_event_id)s, now() + make_interval(secs => %(debounce)s))"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(insert_query, params)
        row = await cur.fetchone()
        assert row is not None
        return _row_to_job(row)


async def get_ready_sync_jobs(
    conn: AsyncConnection[Any],
    *,
    limit: int = 1,
) -> list[SyncJob]:
    """Fetch and atomically claim sync jobs whose debounce window has passed.

    Claimed jobs are moved to ``processing`` status.  Uses
    ``FOR UPDATE SKIP LOCKED`` so multiple workers can run safely.

    Args:
        conn: Async psycopg connection.
        limit: Maximum jobs to claim (default 1).

    Returns:
        List of claimed ``SyncJob`` objects.
    """
    query = sql.SQL(
        "UPDATE sync_jobs SET status = 'processing', updated_at = now()"
        " WHERE id IN ("
        "   SELECT id FROM sync_jobs"
        "   WHERE status = 'pending' AND scheduled_at <= now()"
        "   ORDER BY scheduled_at"
        "   LIMIT %(limit)s"
        "   FOR UPDATE SKIP LOCKED"
        " )"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"limit": limit})
        return [_row_to_job(row) for row in await cur.fetchall()]


async def complete_sync_job(conn: AsyncConnection[Any], job_id: int) -> None:
    """Mark a sync job as successfully completed."""
    await conn.execute(
        "UPDATE sync_jobs SET status = 'completed', updated_at = now() WHERE id = %(id)s",
        {"id": job_id},
    )


async def fail_sync_job(
    conn: AsyncConnection[Any],
    job_id: int,
    *,
    error: str,
) -> None:
    """Record a sync job failure.

    Increments ``attempts`` and sets ``last_error``.  If the job has
    reached 3 attempts, its status is set to ``failed`` (permanently).
    Otherwise it goes back to ``pending`` for retry.
    """
    await conn.execute(
        "UPDATE sync_jobs SET"
        "  attempts = attempts + 1,"
        "  last_error = %(error)s,"
        "  status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END,"
        "  updated_at = now()"
        " WHERE id = %(id)s",
        {"id": job_id, "error": error},
    )
