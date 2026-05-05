"""CRUD operations for the ``ideas`` table.

Ideas are append-only ideation notes attached to a work unit — separate
from ``items`` because their lifecycle and intent differ. There is
intentionally **no** ``update_idea`` or ``delete_idea`` here: mistakes
are recovered via :func:`redact_idea`, which preserves the audit row.

The Python API surface is the policy boundary; the database has no
triggers enforcing append-only. Direct SQL is still allowed for admin
cleanup.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import Idea

_COLUMNS = (
    "id",
    "work_unit_id",
    "project_id",
    "text",
    "created_at",
    "created_by",
    "redacted_at",
    "redacted_by",
)

_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_idea(row: dict[str, Any]) -> Idea:
    for col in ("created_by", "redacted_by"):
        if row.get(col) is not None:
            row[col] = str(row[col])
    return Idea(**row)


# ── Add ──────────────────────────────────────────────────────────


async def add_idea(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    work_unit_id: str,
    text: str,
    created_by: str | None = None,
    id: str | None = None,
) -> Idea:
    """Insert an idea attached to a work unit.

    The work unit must exist, belong to ``project_id``, and not be
    ``archived`` or ``abandoned``. ``done`` is allowed (retro notes).

    Raises:
        ValueError: empty text, missing WU, cross-project WU, or WU in
            a status that rejects new ideas.
    """
    if not text.strip():
        raise ValueError("idea text must not be empty")

    idea_id = id or str(uuid.uuid4())

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT project_id, status FROM work_units WHERE id = %(id)s",
            {"id": work_unit_id},
        )
        wu_row = await cur.fetchone()
        if wu_row is None:
            raise ValueError(f"work_unit not found: {work_unit_id}")
        if wu_row["project_id"] != project_id:
            raise ValueError(
                f"work_unit {work_unit_id} belongs to a different project"
            )
        if wu_row["status"] in ("archived", "abandoned"):
            raise ValueError(
                f"work_unit {work_unit_id} is {wu_row['status']}; cannot add ideas"
            )

        query = sql.SQL(
            "INSERT INTO ideas"
            " (id, work_unit_id, project_id, text, created_by)"
            " VALUES (%(id)s, %(wu)s, %(pid)s, %(text)s, %(created_by)s)"
            " RETURNING {returning}"
        ).format(returning=_RETURNING)

        await cur.execute(
            query,
            {
                "id": idea_id,
                "wu": work_unit_id,
                "pid": project_id,
                "text": text,
                "created_by": created_by,
            },
        )
        row = await cur.fetchone()
        assert row is not None, "INSERT … RETURNING produced no row"
        return _row_to_idea(row)


# ── Read ─────────────────────────────────────────────────────────


async def list_ideas(
    conn: AsyncConnection[Any],
    *,
    work_unit_id: str,
    limit: int = 100,
    include_redacted: bool = False,
) -> list[Idea]:
    """List ideas for a work unit, newest first.

    Redacted rows are excluded by default; ``include_redacted=True``
    opts back in (admin / audit flows).
    """
    conditions: list[sql.Composable] = [sql.SQL("work_unit_id = %(wu)s")]
    if not include_redacted:
        conditions.append(sql.SQL("redacted_at IS NULL"))
    where = sql.SQL(" AND ").join(conditions)

    query = sql.SQL(
        "SELECT {columns} FROM ideas"
        " WHERE {where}"
        " ORDER BY created_at DESC"
        " LIMIT %(limit)s"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"wu": work_unit_id, "limit": limit})
        rows = await cur.fetchall()
        return [_row_to_idea(r) for r in rows]


async def get_idea(
    conn: AsyncConnection[Any],
    idea_id: str,
) -> Idea | None:
    """Fetch a single idea by id (or hex prefix). Includes redacted rows.

    Saas-side permission checks need to fetch the row before deciding
    whether redact is allowed — hence this is a separate helper rather
    than relying on list/search.
    """
    resolved = await resolve_uuid_prefix(
        conn, "ideas", idea_id, label_column="text"
    )
    if resolved is None:
        return None
    query = sql.SQL("SELECT {columns} FROM ideas WHERE id = %(id)s").format(
        columns=_RETURNING
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_idea(row) if row else None
