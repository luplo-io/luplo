"""CRUD operations for the links table.

Links are typed, weighted edges between items — e.g. ``excludes``,
``synergizes_with``, ``interacts_with``.  The ``link_type`` is free-form
text (not an enum) so new relationship types can appear as systems grow.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.models import Link

_COLUMNS = (
    "from_item_id",
    "to_item_id",
    "link_type",
    "strength",
    "note",
    "created_by_actor_id",
    "created_at",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_link(row: dict[str, Any]) -> Link:
    """Convert a dict-row into a ``Link`` dataclass."""
    if row.get("created_by_actor_id") is not None:
        row["created_by_actor_id"] = str(row["created_by_actor_id"])
    return Link(**row)


async def create_link(
    conn: AsyncConnection[Any],
    *,
    from_item_id: str,
    to_item_id: str,
    link_type: str,
    strength: int = 5,
    note: str | None = None,
    actor_id: str | None = None,
) -> Link:
    """Create a typed edge between two items.

    Args:
        conn: Async psycopg connection.
        from_item_id: Source item.
        to_item_id: Target item.
        link_type: Relationship type (e.g. ``"excludes"``).
        strength: Weight 1–10, default 5.
        note: Optional annotation.
        actor_id: Who created this link.

    Returns:
        The newly created ``Link``.

    Raises:
        psycopg.errors.UniqueViolation: If the exact
            ``(from_item_id, to_item_id, link_type)`` triple already exists.
    """
    query = sql.SQL(
        "INSERT INTO links"
        " (from_item_id, to_item_id, link_type, strength, note, created_by_actor_id)"
        " VALUES (%(from)s, %(to)s, %(type)s, %(strength)s, %(note)s, %(actor)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "from": from_item_id,
                "to": to_item_id,
                "type": link_type,
                "strength": strength,
                "note": note,
                "actor": actor_id,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_link(row)


async def get_links(
    conn: AsyncConnection[Any],
    item_id: str,
    *,
    direction: str = "from",
    link_type: str | None = None,
) -> list[Link]:
    """Query links connected to an item.

    Args:
        conn: Async psycopg connection.
        item_id: The item to query links for.
        direction: ``"from"`` (outgoing), ``"to"`` (incoming),
            or ``"both"``.
        link_type: Optional filter by relationship type.

    Returns:
        List of matching ``Link`` objects ordered by ``created_at DESC``.
    """
    if direction == "from":
        condition = sql.SQL("from_item_id = %(item_id)s")
    elif direction == "to":
        condition = sql.SQL("to_item_id = %(item_id)s")
    else:
        condition = sql.SQL(
            "(from_item_id = %(item_id)s OR to_item_id = %(item_id)s)"
        )

    params: dict[str, Any] = {"item_id": item_id}

    conditions = [condition]
    if link_type is not None:
        conditions.append(sql.SQL("link_type = %(link_type)s"))
        params["link_type"] = link_type

    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL(
        "SELECT {columns} FROM links WHERE {where} ORDER BY created_at DESC"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [_row_to_link(row) for row in await cur.fetchall()]


async def delete_link(
    conn: AsyncConnection[Any],
    from_item_id: str,
    to_item_id: str,
    link_type: str,
) -> bool:
    """Delete a link by its composite primary key.

    Returns:
        ``True`` if the link existed and was deleted, ``False`` otherwise.
    """
    result = await conn.execute(
        "DELETE FROM links"
        " WHERE from_item_id = %(from)s AND to_item_id = %(to)s AND link_type = %(type)s",
        {"from": from_item_id, "to": to_item_id, "type": link_type},
    )
    return result.rowcount > 0
