"""Operations for the items_history table.

Every meaningful change to an item (content edit, sync update) is recorded
here with before/after snapshots, a diff summary, and a semantic impact
classification.  This powers the ``luplo_history_query`` MCP tool and the
future compliance audit view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.models import HistoryEntry

_COLUMNS = (
    "id",
    "item_id",
    "version",
    "content_before",
    "content_after",
    "content_hash_before",
    "content_hash_after",
    "diff_summary",
    "semantic_impact",
    "changed_at",
    "changed_by",
    "source_event_id",
    "notification_sent",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_entry(row: dict[str, Any]) -> HistoryEntry:
    """Convert a dict-row into a ``HistoryEntry`` dataclass."""
    if row.get("changed_by") is not None:
        row["changed_by"] = str(row["changed_by"])
    return HistoryEntry(**row)


async def record_history(
    conn: AsyncConnection[Any],
    *,
    item_id: str,
    version: int,
    changed_by: str,
    content_before: str | None = None,
    content_after: str | None = None,
    content_hash_before: str | None = None,
    content_hash_after: str | None = None,
    diff_summary: str | None = None,
    semantic_impact: str | None = None,
    source_event_id: str | None = None,
) -> HistoryEntry:
    """Record a change to an item.

    Args:
        conn: Async psycopg connection.
        item_id: The item that was changed.
        version: Monotonically increasing version number for this item.
        changed_by: Actor ID of who made the change.
        content_before: Previous content snapshot (optional).
        content_after: New content snapshot (optional).
        content_hash_before: SHA256 of previous content (optional).
        content_hash_after: SHA256 of new content (optional).
        diff_summary: Human-readable change summary (optional).
        semantic_impact: Change classification — ``numeric_change``,
            ``rule_addition``, ``rule_removal``, ``rewording``,
            ``formatting``, ``typo_fix``, ``structural`` (optional).
        source_event_id: External event ID for idempotency (optional).

    Returns:
        The recorded ``HistoryEntry`` with auto-generated ``id``.
    """
    query = sql.SQL(
        "INSERT INTO items_history"
        " (item_id, version, content_before, content_after,"
        "  content_hash_before, content_hash_after,"
        "  diff_summary, semantic_impact, changed_by, source_event_id)"
        " VALUES (%(item_id)s, %(version)s, %(content_before)s, %(content_after)s,"
        "  %(hash_before)s, %(hash_after)s,"
        "  %(diff_summary)s, %(semantic_impact)s, %(changed_by)s, %(source_event_id)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "item_id": item_id,
                "version": version,
                "content_before": content_before,
                "content_after": content_after,
                "hash_before": content_hash_before,
                "hash_after": content_hash_after,
                "diff_summary": diff_summary,
                "semantic_impact": semantic_impact,
                "changed_by": changed_by,
                "source_event_id": source_event_id,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_entry(row)


async def query_history(
    conn: AsyncConnection[Any],
    *,
    project_id: str | None = None,
    item_id: str | None = None,
    since: datetime | None = None,
    semantic_impacts: list[str] | None = None,
    limit: int = 50,
) -> list[HistoryEntry]:
    """Query change history with optional filters.

    At least one of ``project_id`` or ``item_id`` should be provided;
    otherwise an unscoped query may return too many rows.

    Args:
        conn: Async psycopg connection.
        project_id: Filter by project (requires JOIN to items).
        item_id: Filter by specific item.
        since: Only return entries after this timestamp.
        semantic_impacts: Filter by impact types (e.g.
            ``["numeric_change", "rule_addition"]``).
        limit: Maximum rows (default 50).

    Returns:
        List of ``HistoryEntry`` ordered by ``changed_at DESC``.
    """
    # Build FROM clause — JOIN items only if project_id filter is used
    if project_id is not None:
        from_clause = sql.SQL("items_history h JOIN items i ON h.item_id = i.id")
    else:
        from_clause = sql.SQL("items_history h")

    conditions: list[sql.Composable] = []
    params: dict[str, Any] = {"limit": limit}

    if project_id is not None:
        conditions.append(sql.SQL("i.project_id = %(project_id)s"))
        params["project_id"] = project_id

    if item_id is not None:
        conditions.append(sql.SQL("h.item_id = %(item_id)s"))
        params["item_id"] = item_id

    if since is not None:
        conditions.append(sql.SQL("h.changed_at >= %(since)s"))
        params["since"] = since

    if semantic_impacts:
        conditions.append(sql.SQL("h.semantic_impact = ANY(%(impacts)s)"))
        params["impacts"] = semantic_impacts

    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")

    # Prefix all column refs with h. to avoid ambiguity on the JOIN
    h_columns = sql.SQL(", ").join(sql.SQL("h.") + sql.Identifier(c) for c in _COLUMNS)

    query = sql.SQL(
        "SELECT {columns} FROM {from_clause}{where} ORDER BY h.changed_at DESC LIMIT %(limit)s"
    ).format(columns=h_columns, from_clause=from_clause, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [_row_to_entry(row) for row in await cur.fetchall()]
