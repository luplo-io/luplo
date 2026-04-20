"""CRUD operations for the actors table.

Actors are attribution labels — "who wrote this" metadata referenced as
FK on items, history, and audit rows. They are not authenticated
principals: luplo core does not know about passwords, sessions, or
OAuth. A deployment that needs authentication layers it on top and
translates its own user identities into ``actor_id`` before calling
luplo.

After 0002 migration, ``actors.id`` is a UUID (string in Python).
After 0006 migration, ``password_hash`` / ``is_admin`` / ``last_login_at``
/ ``oauth_provider`` / ``oauth_subject`` are removed.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from luplo.core.models import Actor

_COLUMNS = (
    "id",
    "name",
    "email",
    "role",
    "external_ids",
    "joined_at",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_actor(row: dict[str, Any]) -> Actor:
    """Convert a dict-row into an ``Actor`` dataclass."""
    row["external_ids"] = row.get("external_ids") or {}
    actor_id = row["id"]
    row["id"] = str(actor_id) if actor_id is not None else ""
    return Actor(**row)


async def create_actor(
    conn: AsyncConnection[Any],
    *,
    name: str,
    email: str,
    role: str | None = None,
    external_ids: dict[str, str] | None = None,
    id: str | None = None,
) -> Actor:
    """Create a new actor.

    Args:
        conn: Async psycopg connection.
        name: Display name.
        email: Unique email (required after 0002). Used as an attribution
            label, not an authentication identifier.
        role: Optional role description.
        external_ids: Optional mapping of external system IDs.
        id: Optional UUID string; auto-generated UUID4 if omitted.

    Returns:
        The newly created ``Actor``.

    Raises:
        psycopg.errors.UniqueViolation: If *email* already exists.
    """
    actor_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO actors (id, name, email, role, external_ids)"
        " VALUES (%(id)s, %(name)s, %(email)s, %(role)s, %(external_ids)s)"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": actor_id,
                "name": name,
                "email": email,
                "role": role,
                "external_ids": Jsonb(external_ids) if external_ids else Jsonb({}),
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_actor(row)


async def get_actor(conn: AsyncConnection[Any], actor_id: str) -> Actor | None:
    """Fetch an actor by ID. Returns ``None`` if not found."""
    query = sql.SQL("SELECT {columns} FROM actors WHERE id = %(id)s").format(columns=_RETURNING)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": actor_id})
        row = await cur.fetchone()
        return _row_to_actor(row) if row else None


async def get_actor_by_email(conn: AsyncConnection[Any], email: str) -> Actor | None:
    """Look up an actor by email. Returns ``None`` if not found."""
    query = sql.SQL("SELECT {columns} FROM actors WHERE email = %(email)s").format(
        columns=_RETURNING
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"email": email})
        row = await cur.fetchone()
        return _row_to_actor(row) if row else None
