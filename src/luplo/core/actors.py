"""CRUD operations for the actors table.

Actors represent people (and eventually AI agents) who interact with luplo.
After 0002 migration, ``actors.id`` is a UUID (string representation in Python).

OAuth fields (``oauth_provider``, ``oauth_subject``) are set by the server
auth layer — not exposed in create. Password fields likewise set by
``server/auth`` helpers.
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
    "oauth_provider",
    "oauth_subject",
    "external_ids",
    "joined_at",
    "password_hash",
    "is_admin",
    "last_login_at",
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
    password_hash: str | None = None,
    is_admin: bool = False,
    oauth_provider: str | None = None,
    oauth_subject: str | None = None,
) -> Actor:
    """Create a new actor.

    Args:
        conn: Async psycopg connection.
        name: Display name.
        email: Unique email (required after 0002).
        role: Optional role description.
        external_ids: Optional mapping of external system IDs.
        id: Optional UUID string; auto-generated UUID4 if omitted.
        password_hash: Pre-hashed password (argon2id). Never pass plain text.
        is_admin: Whether this actor has admin privileges.
        oauth_provider: OAuth provider name (``github``, ``google``).
        oauth_subject: Provider-assigned subject id (e.g. GitHub user id).

    Returns:
        The newly created ``Actor``.

    Raises:
        psycopg.errors.UniqueViolation: If *email* already exists.
    """
    actor_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO actors"
        " (id, name, email, role, external_ids,"
        "  password_hash, is_admin, oauth_provider, oauth_subject)"
        " VALUES (%(id)s, %(name)s, %(email)s, %(role)s, %(external_ids)s,"
        "         %(password_hash)s, %(is_admin)s, %(oauth_provider)s, %(oauth_subject)s)"
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
                "password_hash": password_hash,
                "is_admin": is_admin,
                "oauth_provider": oauth_provider,
                "oauth_subject": oauth_subject,
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


async def set_password(conn: AsyncConnection[Any], actor_id: str, password_hash: str) -> None:
    """Update an actor's password hash. Caller is responsible for hashing."""
    await conn.execute(
        "UPDATE actors SET password_hash = %s WHERE id = %s",
        (password_hash, actor_id),
    )


async def set_admin(conn: AsyncConnection[Any], actor_id: str, is_admin: bool) -> None:
    """Grant or revoke admin privileges."""
    await conn.execute(
        "UPDATE actors SET is_admin = %s WHERE id = %s",
        (is_admin, actor_id),
    )


async def touch_login(conn: AsyncConnection[Any], actor_id: str) -> None:
    """Record a successful login."""
    await conn.execute(
        "UPDATE actors SET last_login_at = now() WHERE id = %s",
        (actor_id,),
    )
