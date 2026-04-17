"""Integration tests for core/audit.py."""

from __future__ import annotations

import pytest
from psycopg.rows import dict_row

from luplo.core.audit import record_audit


async def _count_audit(conn: object, action: str) -> int:
    """Count audit_log rows with a given action."""
    async with conn.cursor(row_factory=dict_row) as cur:  # type: ignore[union-attr]
        await cur.execute("SELECT count(*) AS cnt FROM audit_log WHERE action = %s", (action,))
        row = await cur.fetchone()
        return row["cnt"] if row else 0


@pytest.mark.asyncio
async def test_record_audit_basic(conn: object, seed_actor: str) -> None:
    await record_audit(
        conn,
        actor_id=seed_actor,
        action="create",
        target_type="item",
        target_id="i-1",  # type: ignore[arg-type]
    )
    assert await _count_audit(conn, "create") == 1


@pytest.mark.asyncio
async def test_record_audit_with_metadata(conn: object, seed_actor: str) -> None:
    await record_audit(
        conn,  # type: ignore[arg-type]
        actor_id=seed_actor,
        action="sync",
        metadata={"source": "notion", "page_id": "abc123"},
    )
    assert await _count_audit(conn, "sync") == 1


@pytest.mark.asyncio
async def test_record_audit_minimal(conn: object, seed_actor: str) -> None:
    await record_audit(conn, actor_id=seed_actor, action="login")  # type: ignore[arg-type]
    assert await _count_audit(conn, "login") == 1


@pytest.mark.asyncio
async def test_record_audit_multiple(conn: object, seed_actor: str) -> None:
    for _ in range(3):
        await record_audit(conn, actor_id=seed_actor, action="view")  # type: ignore[arg-type]
    assert await _count_audit(conn, "view") == 3
