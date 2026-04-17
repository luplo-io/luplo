"""Integration tests for core/history.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from luplo.core.history import query_history, record_history


@pytest.mark.asyncio
async def test_record_history(conn: object, seed_item: str, seed_actor: str) -> None:
    entry = await record_history(
        conn,  # type: ignore[arg-type]
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,
        content_before="old text",
        content_after="new text",
        diff_summary="Changed body",
        semantic_impact="rewording",
    )

    assert entry.id is not None
    assert entry.item_id == seed_item
    assert entry.version == 1
    assert entry.content_before == "old text"
    assert entry.content_after == "new text"
    assert entry.diff_summary == "Changed body"
    assert entry.semantic_impact == "rewording"
    assert entry.notification_sent is False


@pytest.mark.asyncio
async def test_record_history_minimal(conn: object, seed_item: str, seed_actor: str) -> None:
    entry = await record_history(
        conn,
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,  # type: ignore[arg-type]
    )
    assert entry.content_before is None
    assert entry.diff_summary is None


@pytest.mark.asyncio
async def test_query_history_by_item(conn: object, seed_item: str, seed_actor: str) -> None:
    await record_history(
        conn,
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,  # type: ignore[arg-type]
    )
    await record_history(
        conn,
        item_id=seed_item,
        version=2,
        changed_by=seed_actor,  # type: ignore[arg-type]
    )

    entries = await query_history(conn, item_id=seed_item)  # type: ignore[arg-type]
    assert len(entries) == 2
    assert entries[0].version == 2  # newest first


@pytest.mark.asyncio
async def test_query_history_by_project(
    conn: object, seed_item: str, seed_project: str, seed_actor: str
) -> None:
    await record_history(
        conn,
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,  # type: ignore[arg-type]
    )

    entries = await query_history(conn, project_id=seed_project)  # type: ignore[arg-type]
    assert len(entries) == 1
    assert entries[0].item_id == seed_item


@pytest.mark.asyncio
async def test_query_history_by_semantic_impact(
    conn: object, seed_item: str, seed_actor: str
) -> None:
    await record_history(
        conn,  # type: ignore[arg-type]
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,
        semantic_impact="numeric_change",
    )
    await record_history(
        conn,  # type: ignore[arg-type]
        item_id=seed_item,
        version=2,
        changed_by=seed_actor,
        semantic_impact="typo_fix",
    )

    entries = await query_history(
        conn,
        item_id=seed_item,
        semantic_impacts=["numeric_change"],  # type: ignore[arg-type]
    )
    assert len(entries) == 1
    assert entries[0].semantic_impact == "numeric_change"


@pytest.mark.asyncio
async def test_query_history_since(conn: object, seed_item: str, seed_actor: str) -> None:
    await record_history(
        conn,
        item_id=seed_item,
        version=1,
        changed_by=seed_actor,  # type: ignore[arg-type]
    )

    # Query with a future timestamp should return nothing
    future = datetime(2099, 1, 1, tzinfo=UTC)
    entries = await query_history(
        conn,
        item_id=seed_item,
        since=future,  # type: ignore[arg-type]
    )
    assert entries == []


@pytest.mark.asyncio
async def test_query_history_limit(conn: object, seed_item: str, seed_actor: str) -> None:
    for v in range(5):
        await record_history(
            conn,
            item_id=seed_item,
            version=v,
            changed_by=seed_actor,  # type: ignore[arg-type]
        )

    entries = await query_history(conn, item_id=seed_item, limit=2)  # type: ignore[arg-type]
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_query_history_empty(conn: object) -> None:
    entries = await query_history(conn, item_id="nonexistent")  # type: ignore[arg-type]
    assert entries == []
