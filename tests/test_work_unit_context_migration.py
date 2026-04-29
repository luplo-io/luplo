"""Tests for the ``work_units.context`` JSONB column added in 0007.

The column mirrors the shape of ``items.context`` (added in 0003) and is
required so the upcoming ``lp import`` feature can stash dedup metadata
(source paths + content hashes) on a per-work-unit basis without a new
table.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import TupleRow


@pytest.mark.asyncio
async def test_work_units_has_context_column(
    conn: psycopg.AsyncConnection[TupleRow],
) -> None:
    """``work_units.context`` exists with type=jsonb and default empty object."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'work_units' AND column_name = 'context'"
        )
        row = await cur.fetchone()
    assert row is not None, (
        "work_units.context missing — migration 0007_work_units_context not applied"
    )
    column_name, data_type, is_nullable, column_default = row
    assert column_name == "context"
    assert data_type == "jsonb"
    # NOT NULL with default '{}'::jsonb mirrors items.context (0003).
    assert is_nullable == "NO"
    assert "{}" in (column_default or "")


@pytest.mark.asyncio
async def test_work_units_context_gin_index_on_content_hash_set(
    conn: psycopg.AsyncConnection[TupleRow],
) -> None:
    """A GIN index on ``context->'content_hash_set'`` exists for fast dedup lookups.

    Content-hash-based dedup (vs the original path-based key) is what
    makes the import pipeline cwd-independent and cloud-friendly: the
    server has no concept of the agent's filesystem layout, so paths
    are unreliable.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT indexname, indexdef "
            "FROM pg_indexes "
            "WHERE tablename = 'work_units' "
            "  AND indexname = 'idx_work_units_context_content_hash_set'"
        )
        row = await cur.fetchone()
    assert row is not None, (
        "GIN index idx_work_units_context_content_hash_set missing — migration 0007 incomplete"
    )
    _, indexdef = row
    assert "using gin" in indexdef.lower()
    assert "content_hash_set" in indexdef
