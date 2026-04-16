"""CRUD operations for the items table.

Items are the central entity in luplo — decisions, knowledge, policies, and
documents all live here.  Edits create new rows via ``supersedes_id`` (the old
row is never mutated).  Deletes are soft (``deleted_at`` is set, row stays).
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from luplo.core import item_types as _item_types
from luplo.core.errors import ValidationError
from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import Item, ItemCreate

_ITEM_FIELDS: frozenset[str] = frozenset(f.name for f in dataclasses.fields(Item))

# Columns returned by every SELECT / RETURNING clause.
# Must stay in sync with the Item dataclass (excludes search_tsv, embedding).
_COLUMNS = (
    "id",
    "project_id",
    "item_type",
    "title",
    "body",
    "source_url",
    "parent_item_id",
    "work_unit_id",
    "source_ref",
    "actor_id",
    "system_ids",
    "tags",
    "rationale",
    "alternatives",
    "confidence",
    "supersedes_id",
    "deleted_at",
    "expires_at",
    "source_type",
    "source_page_id",
    "stable_section_key",
    "current_section_path",
    "start_anchor",
    "content_hash",
    "source_version",
    "last_synced_at",
    "created_at",
    "updated_at",
    "context",
)

_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_item(row: dict[str, Any]) -> Item:
    """Convert a dict-row from psycopg into an ``Item`` dataclass.

    Tolerates extra columns (e.g. ``search_tsv``, ``embedding``) returned
    by ``SELECT items.*`` by filtering to known dataclass fields.
    Normalises NULL arrays to empty lists, ensures ``source_version`` has
    a fallback default, coerces ``actor_id`` (UUID after 0002) to str, and
    falls back to an empty dict for ``context`` (NULL-safe).
    """
    filtered = {k: v for k, v in row.items() if k in _ITEM_FIELDS}
    filtered["system_ids"] = filtered.get("system_ids") or []
    filtered["tags"] = filtered.get("tags") or []
    filtered["source_version"] = filtered.get("source_version") or 1
    if filtered.get("actor_id") is not None:
        filtered["actor_id"] = str(filtered["actor_id"])
    filtered["context"] = filtered.get("context") or {}
    return Item(**filtered)


# ── Create ───────────────────────────────────────────────────────


async def create_item(conn: AsyncConnection[Any], data: ItemCreate) -> Item:
    """Insert a new item and return it.

    * Generates a UUID4 ``id`` automatically.
    * Populates ``search_tsv`` from title + body + rationale.
    * If ``data.supersedes_id`` is set the new row is treated as an edit
      of the referenced item (the old row is untouched).

    Args:
        conn: An async psycopg connection (inside an open transaction).
        data: Fields for the new item.

    Returns:
        The fully-populated ``Item`` as stored in the database.
    """
    # Validate context against the schema registered for this item_type.
    # Raises UnknownItemTypeError or ContextValidationError on failure;
    # both surface as 4xx in the route layer.
    await _item_types.validate_context(conn, data.item_type, data.context)

    # Research items must carry a source_url. DB has a CHECK constraint as
    # the ultimate guard, but raise early here for a clean error message.
    if data.item_type == "research" and not data.source_url:
        raise ValidationError("item_type='research' requires source_url (the cached URL)")

    item_id = str(uuid.uuid4())

    params: dict[str, Any] = {
        "id": item_id,
        "project_id": data.project_id,
        "item_type": data.item_type,
        "title": data.title,
        "body": data.body,
        "source_url": data.source_url,
        "parent_item_id": data.parent_item_id,
        "work_unit_id": data.work_unit_id,
        "source_ref": data.source_ref,
        "actor_id": data.actor_id,
        "system_ids": data.system_ids or None,
        "tags": data.tags or None,
        "rationale": data.rationale,
        "alternatives": Jsonb(data.alternatives) if data.alternatives else None,
        "confidence": data.confidence,
        "supersedes_id": data.supersedes_id,
        "expires_at": data.expires_at,
        "context": Jsonb(data.context or {}),
        "source_type": data.source_type,
        "source_page_id": data.source_page_id,
        "stable_section_key": data.stable_section_key,
        "current_section_path": data.current_section_path,
        "start_anchor": data.start_anchor,
        "content_hash": data.content_hash,
    }

    query = sql.SQL(
        "INSERT INTO items ("
        "  id, project_id, item_type, title, body, source_url,"
        "  parent_item_id, work_unit_id, source_ref, actor_id,"
        "  system_ids, tags, rationale, alternatives, confidence,"
        "  supersedes_id, expires_at, context, source_type, source_page_id,"
        "  stable_section_key, current_section_path, start_anchor,"
        "  content_hash, search_tsv"
        ") VALUES ("
        "  %(id)s, %(project_id)s, %(item_type)s, %(title)s, %(body)s, %(source_url)s,"
        "  %(parent_item_id)s, %(work_unit_id)s, %(source_ref)s, %(actor_id)s,"
        "  %(system_ids)s, %(tags)s, %(rationale)s, %(alternatives)s, %(confidence)s,"
        "  %(supersedes_id)s, %(expires_at)s, %(context)s,"
        "  %(source_type)s, %(source_page_id)s,"
        "  %(stable_section_key)s, %(current_section_path)s, %(start_anchor)s,"
        "  %(content_hash)s,"
        "  to_tsvector('simple',"
        "    %(title)s || ' ' || coalesce(%(body)s, '') || ' ' || coalesce(%(rationale)s, '')"
        "  )"
        ") RETURNING {returning}"
    ).format(returning=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        assert row is not None, "INSERT … RETURNING produced no row"
        return _row_to_item(row)


# ── Read ─────────────────────────────────────────────────────────


async def get_item(
    conn: AsyncConnection[Any],
    item_id: str,
    *,
    project_id: str | None = None,
) -> Item | None:
    """Fetch a single item by ID or hex prefix.

    Args:
        conn: Open async connection.
        item_id: Either a full UUID or a hex prefix of at least
            :data:`luplo.core.id_resolve.MIN_PREFIX_LENGTH` characters.
        project_id: Optional project scope for prefix lookups. Strongly
            recommended whenever the caller knows it; without it, prefix
            collisions are evaluated across every project in the
            database.

    Returns:
        The matching item, or ``None`` when no row exists / the row is
        soft-deleted.

    Raises:
        AmbiguousIdError: If the prefix matches multiple rows.
        IdTooShortError: If a hex prefix shorter than the minimum is
            supplied.
        InvalidIdFormatError: If the input is not a UUID or hex prefix.
    """
    resolved = await resolve_uuid_prefix(conn, "items", item_id, project_id=project_id)
    if resolved is None:
        return None

    query = sql.SQL("SELECT {columns} FROM items WHERE id = %(id)s AND deleted_at IS NULL").format(
        columns=_RETURNING
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_item(row) if row else None


async def get_item_including_deleted(
    conn: AsyncConnection[Any],
    item_id: str,
    *,
    project_id: str | None = None,
) -> Item | None:
    """Fetch a single item by ID or prefix, even if soft-deleted.

    See :func:`get_item` for argument and exception semantics. The only
    difference is that soft-deleted rows are still returned.
    """
    resolved = await resolve_uuid_prefix(conn, "items", item_id, project_id=project_id)
    if resolved is None:
        return None

    query = sql.SQL("SELECT {columns} FROM items WHERE id = %(id)s").format(columns=_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_item(row) if row else None


async def list_items(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    item_type: str | None = None,
    system_id: str | None = None,
    work_unit_id: str | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Item]:
    """List items for a project with optional filters.

    Args:
        conn: Async psycopg connection.
        project_id: Required project scope.
        item_type: Filter by ``item_type`` (e.g. ``"decision"``).
        system_id: Filter items whose ``system_ids`` array contains this value.
        work_unit_id: Filter by ``work_unit_id``.
        include_deleted: If ``True``, include soft-deleted items.
        limit: Maximum rows returned (default 100).
        offset: Pagination offset.

    Returns:
        List of ``Item`` ordered by ``created_at DESC``.
    """
    conditions: list[sql.Composable] = [
        sql.SQL("project_id = %(project_id)s"),
    ]
    params: dict[str, Any] = {
        "project_id": project_id,
        "limit": limit,
        "offset": offset,
    }

    if not include_deleted:
        conditions.append(sql.SQL("deleted_at IS NULL"))

    if item_type is not None:
        conditions.append(sql.SQL("item_type = %(item_type)s"))
        params["item_type"] = item_type

    if system_id is not None:
        conditions.append(sql.SQL("%(system_id)s = ANY(system_ids)"))
        params["system_id"] = system_id

    if work_unit_id is not None:
        conditions.append(sql.SQL("work_unit_id = %(work_unit_id)s"))
        params["work_unit_id"] = work_unit_id

    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL(
        "SELECT {columns} FROM items"
        " WHERE {where}"
        " ORDER BY created_at DESC, id DESC"
        " LIMIT %(limit)s OFFSET %(offset)s"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [_row_to_item(row) for row in await cur.fetchall()]


# ── Delete (soft) ────────────────────────────────────────────────


async def delete_item(conn: AsyncConnection[Any], item_id: str, *, actor_id: str) -> bool:
    """Soft-delete an item by setting ``deleted_at``.

    The row is never removed.  ``get_item`` will return ``None`` for it,
    but ``list_items(include_deleted=True)`` will still find it.

    Args:
        conn: Async psycopg connection.
        item_id: ID of the item to delete.
        actor_id: Who performed the deletion (for audit trail).

    Returns:
        ``True`` if the item existed and was deleted, ``False`` if it was
        already deleted or not found.
    """
    result = await conn.execute(
        "UPDATE items SET deleted_at = now(), updated_at = now()"
        " WHERE id = %(id)s AND deleted_at IS NULL",
        {"id": item_id},
    )
    return result.rowcount > 0


# ── Supersedes chain ─────────────────────────────────────────────


async def get_supersedes_chain(conn: AsyncConnection[Any], item_id: str) -> list[Item]:
    """Walk the ``supersedes_id`` chain from *item_id* back to the original.

    Returns the full chain ordered **oldest-first** (the original item is
    at index 0, the most recent version — *item_id* itself — is last).

    If *item_id* does not exist, returns an empty list.
    """
    _cols_aliased = sql.SQL(", ").join(sql.SQL("i.") + sql.Identifier(c) for c in _COLUMNS)
    query = sql.SQL(
        "WITH RECURSIVE chain AS ("
        "  SELECT {columns}, 0 AS depth FROM items WHERE id = %(id)s"
        "  UNION ALL"
        "  SELECT {columns_aliased}, c.depth + 1 FROM items i"
        "    JOIN chain c ON c.supersedes_id = i.id"
        ")"
        " SELECT {columns} FROM chain ORDER BY depth DESC"
    ).format(
        columns=_RETURNING,
        columns_aliased=_cols_aliased,
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": item_id})
        return [_row_to_item(row) for row in await cur.fetchall()]
