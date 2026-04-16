"""CRUD operations for the systems table.

Systems represent game systems or software components within a project
(e.g. "karma", "vendor", "banking").  The ``depends_on_system_ids`` array
tracks cross-system dependencies for impact analysis.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import System

_COLUMNS = (
    "id",
    "project_id",
    "name",
    "description",
    "depends_on_system_ids",
    "status",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)

_SENTINEL: Any = object()
"""Sentinel to distinguish 'not passed' from ``None`` in update calls."""


def _row_to_system(row: dict[str, Any]) -> System:
    """Convert a dict-row into a ``System`` dataclass."""
    row["depends_on_system_ids"] = row.get("depends_on_system_ids") or []
    return System(**row)


async def create_system(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    name: str,
    description: str | None = None,
    depends_on_system_ids: list[str] | None = None,
    id: str | None = None,
) -> System:
    """Create a new system within a project.

    Args:
        conn: Async psycopg connection.
        project_id: Owning project.
        name: Unique name within the project.
        description: Optional description.
        depends_on_system_ids: IDs of systems this one depends on.
        id: Optional ID override; auto-generated UUID4 if omitted.

    Returns:
        The newly created ``System``.

    Raises:
        psycopg.errors.UniqueViolation: If *(project_id, name)* already exists.
    """
    system_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO systems (id, project_id, name, description, depends_on_system_ids)"
        " VALUES (%(id)s, %(project_id)s, %(name)s, %(description)s, %(depends_on)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": system_id,
                "project_id": project_id,
                "name": name,
                "description": description,
                "depends_on": depends_on_system_ids or None,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_system(row)


async def get_system(
    conn: AsyncConnection[Any],
    system_id: str,
    *,
    project_id: str | None = None,
) -> System | None:
    """Fetch a system by ID or hex prefix (≥8 chars).

    Returns ``None`` when nothing matches; raises
    :class:`AmbiguousIdError` when a prefix matches multiple rows.
    Pass *project_id* to scope prefix lookups to a single project.
    """
    resolved = await resolve_uuid_prefix(
        conn, "systems", system_id, project_id=project_id, label_column="name"
    )
    if resolved is None:
        return None
    query = sql.SQL("SELECT {columns} FROM systems WHERE id = %(id)s").format(columns=_RETURNING)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_system(row) if row else None


async def list_systems(conn: AsyncConnection[Any], project_id: str) -> list[System]:
    """List all systems for a project, ordered by name."""
    query = sql.SQL(
        "SELECT {columns} FROM systems WHERE project_id = %(project_id)s ORDER BY name"
    ).format(columns=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"project_id": project_id})
        return [_row_to_system(row) for row in await cur.fetchall()]


async def update_system(
    conn: AsyncConnection[Any],
    system_id: str,
    *,
    description: Any = _SENTINEL,
    depends_on_system_ids: Any = _SENTINEL,
    status: Any = _SENTINEL,
) -> System | None:
    """Update a system.  Only fields explicitly passed are changed.

    Pass ``None`` to clear a field.  Omit (or pass nothing) to leave it
    unchanged.

    Args:
        conn: Async psycopg connection.
        system_id: ID of the system to update.
        description: New description, ``None`` to clear, or omit.
        depends_on_system_ids: New dependency list, ``None`` to clear, or omit.
        status: New status, ``None`` to clear, or omit.

    Returns:
        The updated ``System``, or ``None`` if not found.
    """
    clauses: list[sql.Composable] = []
    params: dict[str, Any] = {"id": system_id}

    if description is not _SENTINEL:
        clauses.append(sql.SQL("description = %(description)s"))
        params["description"] = description

    if depends_on_system_ids is not _SENTINEL:
        clauses.append(sql.SQL("depends_on_system_ids = %(depends_on)s"))
        params["depends_on"] = depends_on_system_ids

    if status is not _SENTINEL:
        clauses.append(sql.SQL("status = %(status)s"))
        params["status"] = status

    if not clauses:
        return await get_system(conn, system_id)

    query = sql.SQL("UPDATE systems SET {sets} WHERE id = %(id)s RETURNING {returning}").format(
        sets=sql.SQL(", ").join(clauses),
        returning=_RETURNING,
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        return _row_to_system(row) if row else None
