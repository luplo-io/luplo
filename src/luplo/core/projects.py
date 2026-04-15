"""CRUD operations for the projects table.

Projects are the top-level scope for all luplo data.  Every item, system,
work unit, and glossary group belongs to exactly one project.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.models import Project

_COLUMNS = ("id", "name", "description", "created_at")
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_project(row: dict[str, Any]) -> Project:
    """Convert a dict-row into a ``Project`` dataclass."""
    return Project(**row)


async def create_project(
    conn: AsyncConnection[Any],
    *,
    name: str,
    description: str | None = None,
    id: str | None = None,
) -> Project:
    """Create a new project.

    Args:
        conn: Async psycopg connection.
        name: Unique project name.
        description: Optional description.
        id: Optional ID override; auto-generated UUID4 if omitted.

    Returns:
        The newly created ``Project``.

    Raises:
        psycopg.errors.UniqueViolation: If *name* already exists.
    """
    project_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO projects (id, name, description)"
        " VALUES (%(id)s, %(name)s, %(description)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {"id": project_id, "name": name, "description": description},
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_project(row)


async def get_project(
    conn: AsyncConnection[Any], project_id: str
) -> Project | None:
    """Fetch a project by ID.  Returns ``None`` if not found."""
    query = sql.SQL("SELECT {columns} FROM projects WHERE id = %(id)s").format(
        columns=_RETURNING
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": project_id})
        row = await cur.fetchone()
        return _row_to_project(row) if row else None


async def list_projects(conn: AsyncConnection[Any]) -> list[Project]:
    """List all projects ordered by creation date (newest first)."""
    query = sql.SQL(
        "SELECT {columns} FROM projects ORDER BY created_at DESC"
    ).format(columns=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        return [_row_to_project(row) for row in await cur.fetchall()]
