"""CRUD operations for the work_units table.

Work units are the user-facing grouping of intent — "vendor system design",
"karma rework", etc.  They replace the old sessions concept and live across
multiple Claude sessions.  A→B developer handoff is the core use case:
``created_by`` and ``closed_by`` can differ naturally.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import WorkUnit

_COLUMNS = (
    "id",
    "project_id",
    "title",
    "description",
    "system_ids",
    "status",
    "created_by",
    "created_at",
    "closed_at",
    "closed_by",
)

_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_work_unit(row: dict[str, Any]) -> WorkUnit:
    """Convert a dict-row into a ``WorkUnit`` dataclass.

    Normalises NULL arrays to empty lists; coerces UUID FKs to strings.
    """
    row["system_ids"] = row.get("system_ids") or []
    for col in ("created_by", "closed_by"):
        if row.get(col) is not None:
            row[col] = str(row[col])
    return WorkUnit(**row)


# ── Open ─────────────────────────────────────────────────────────


async def open_work_unit(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    title: str,
    description: str | None = None,
    system_ids: list[str] | None = None,
    created_by: str | None = None,
    id: str | None = None,
) -> WorkUnit:
    """Create a new work unit in ``in_progress`` status.

    Args:
        conn: Async psycopg connection.
        project_id: Project this work unit belongs to.
        title: Human-readable title (e.g. "Vendor system design").
        description: Optional longer description.
        system_ids: Systems this work unit touches.
        created_by: Actor ID of who opened it.

    Returns:
        The newly created ``WorkUnit``.
    """
    wu_id = id or str(uuid.uuid4())

    query = sql.SQL(
        "INSERT INTO work_units (id, project_id, title, description, system_ids, created_by)"
        " VALUES (%(id)s, %(project_id)s, %(title)s, %(description)s, %(system_ids)s, %(created_by)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": wu_id,
                "project_id": project_id,
                "title": title,
                "description": description,
                "system_ids": system_ids or None,
                "created_by": created_by,
            },
        )
        row = await cur.fetchone()
        assert row is not None, "INSERT … RETURNING produced no row"
        return _row_to_work_unit(row)


# ── Read ─────────────────────────────────────────────────────────


async def get_work_unit(
    conn: AsyncConnection[Any],
    wu_id: str,
    *,
    project_id: str | None = None,
) -> WorkUnit | None:
    """Fetch a single work unit by ID or hex prefix (≥8 chars).

    Args:
        conn: Open async connection.
        wu_id: Full UUID or hex prefix.
        project_id: Optional scope; strongly recommended whenever the
            caller knows the project to avoid cross-project collisions.

    Returns:
        The work unit, or ``None`` when nothing matches.

    Raises:
        AmbiguousIdError: If the prefix matches multiple rows.
        IdTooShortError: If the prefix is shorter than the minimum.
        InvalidIdFormatError: If the input is not a UUID or hex prefix.
    """
    resolved = await resolve_uuid_prefix(conn, "work_units", wu_id, project_id=project_id)
    if resolved is None:
        return None

    query = sql.SQL("SELECT {columns} FROM work_units WHERE id = %(id)s").format(
        columns=_RETURNING
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_work_unit(row) if row else None


async def list_work_units(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    status: str | None = None,
) -> list[WorkUnit]:
    """List work units for a project, optionally filtered by status.

    Args:
        conn: Async psycopg connection.
        project_id: Required project scope.
        status: Filter by status (e.g. ``"in_progress"``).

    Returns:
        List of ``WorkUnit`` ordered by ``created_at DESC``.
    """
    conditions: list[sql.Composable] = [
        sql.SQL("project_id = %(project_id)s"),
    ]
    params: dict[str, Any] = {"project_id": project_id}

    if status is not None:
        conditions.append(sql.SQL("status = %(status)s"))
        params["status"] = status

    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL(
        "SELECT {columns} FROM work_units WHERE {where} ORDER BY created_at DESC"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [_row_to_work_unit(row) for row in await cur.fetchall()]


async def find_work_units(
    conn: AsyncConnection[Any],
    project_id: str,
    query: str,
) -> list[WorkUnit]:
    """Search in-progress work units by title substring (case-insensitive).

    Used by ``luplo_work_resume`` to find a work unit to continue.
    Only returns ``in_progress`` work units.

    Args:
        conn: Async psycopg connection.
        project_id: Required project scope.
        query: Substring to match against title.

    Returns:
        Matching work units ordered by ``created_at DESC``.
    """
    sql_query = sql.SQL(
        "SELECT {columns} FROM work_units"
        " WHERE project_id = %(project_id)s"
        "   AND status = 'in_progress'"
        "   AND title ILIKE %(pattern)s"
        " ORDER BY created_at DESC"
    ).format(columns=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql_query,
            {"project_id": project_id, "pattern": f"%{query}%"},
        )
        return [_row_to_work_unit(row) for row in await cur.fetchall()]


# ── Close ────────────────────────────────────────────────────────


async def close_work_unit(
    conn: AsyncConnection[Any],
    wu_id: str,
    *,
    actor_id: str,
    status: str = "done",
) -> WorkUnit | None:
    """Close a work unit by setting its status, ``closed_at``, and ``closed_by``.

    ``closed_by`` may differ from ``created_by`` — this is the natural
    record of an A→B developer handoff.

    Args:
        conn: Async psycopg connection.
        wu_id: ID of the work unit to close.
        actor_id: Who is closing it.
        status: Target status (``"done"`` or ``"abandoned"``).

    Returns:
        The updated ``WorkUnit``, or ``None`` if it was not found or
        already closed.
    """
    query = sql.SQL(
        "UPDATE work_units"
        " SET status = %(status)s, closed_at = now(), closed_by = %(actor_id)s"
        " WHERE id = %(id)s AND status = 'in_progress'"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {"id": wu_id, "status": status, "actor_id": actor_id},
        )
        row = await cur.fetchone()
        return _row_to_work_unit(row) if row else None
