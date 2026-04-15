"""item_types registry — DB is the source of truth.

Each ``items.item_type`` value must be a key in this registry (FK
enforced after migration 0003). The registry stores a JSON Schema for
``items.context`` per type; ``validate_context`` runs that schema via
the ``jsonschema`` library at create_item time.

System types (decision, knowledge, policy, document, task, qa_check)
are seeded by the migration. User-defined types may be added at any
time:

    INSERT INTO item_types (key, display_name, schema, owner)
    VALUES ('sprint', 'Sprint', '{...}'::jsonb, 'user');

(P6) Strictness — ``additionalProperties`` — is set per-type by intent,
not by owner. ``task`` and ``qa_check`` are strict; the others permissive.
"""

from __future__ import annotations

import time
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import (
    SchemaError as _JSONSchemaSchemaError,
    ValidationError as _JSONSchemaError,
)
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from luplo.core.errors import ContextValidationError, UnknownItemTypeError
from luplo.core.models import ItemType

# Re-export for callers who already import these from item_types.
__all__ = [
    "ContextValidationError",
    "UnknownItemTypeError",
    "create_item_type",
    "get_item_type",
    "invalidate_cache",
    "list_item_types",
    "validate_context",
]

_COLUMNS = ("key", "display_name", "schema", "owner", "created_at", "updated_at")
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


# ── Registry cache ───────────────────────────────────────────────
# Process-local TTL cache of (key → schema dict). Validation happens
# many times per request and the registry changes rarely.

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 60.0


def _row_to_item_type(row: dict[str, Any]) -> ItemType:
    """Convert a dict-row into an ``ItemType`` dataclass."""
    return ItemType(**row)


async def _load_schema(conn: AsyncConnection[Any], key: str) -> dict[str, Any] | None:
    """Fetch a schema from the DB without using the cache."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT schema FROM item_types WHERE key = %s", (key,)
        )
        row = await cur.fetchone()
    if not row:
        return None
    schema = row["schema"]
    return schema if isinstance(schema, dict) else None


async def _get_cached_schema(
    conn: AsyncConnection[Any], key: str
) -> dict[str, Any] | None:
    """Return the cached schema for *key*, refreshing if stale or missing."""
    cached = _CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    schema = await _load_schema(conn, key)
    if schema is None:
        return None
    _CACHE[key] = (now, schema)
    return schema


def invalidate_cache(key: str | None = None) -> None:
    """Drop a single key (or the whole cache when ``key`` is None)."""
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)


# ── Public API ───────────────────────────────────────────────────


async def get_item_type(
    conn: AsyncConnection[Any], key: str
) -> ItemType | None:
    """Fetch a registry entry by key. Returns ``None`` if not found."""
    query = sql.SQL("SELECT {cols} FROM item_types WHERE key = %s").format(
        cols=_RETURNING
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, (key,))
        row = await cur.fetchone()
        return _row_to_item_type(row) if row else None


async def list_item_types(conn: AsyncConnection[Any]) -> list[ItemType]:
    """Return all registry entries, ordered by key."""
    query = sql.SQL("SELECT {cols} FROM item_types ORDER BY key").format(
        cols=_RETURNING
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query)
        rows = await cur.fetchall()
        return [_row_to_item_type(r) for r in rows]


async def create_item_type(
    conn: AsyncConnection[Any],
    *,
    key: str,
    display_name: str,
    schema: dict[str, Any],
    owner: str = "user",
) -> ItemType:
    """Register a new item_type.

    The default *owner* is ``"user"``; callers seeding system types
    (e.g. migrations) should pass ``owner="system"``.

    The provided *schema* is validated structurally by Draft7Validator
    before insertion — a malformed schema raises ``ContextValidationError``
    immediately rather than at first use.
    """
    try:
        Draft7Validator.check_schema(schema)
    except (_JSONSchemaSchemaError, _JSONSchemaError) as e:
        raise ContextValidationError(key, f"invalid schema: {e.message}") from e

    query = sql.SQL(
        "INSERT INTO item_types (key, display_name, schema, owner)"
        " VALUES (%s, %s, %s, %s)"
        " RETURNING {cols}"
    ).format(cols=_RETURNING)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query, (key, display_name, Jsonb(schema), owner)
        )
        row = await cur.fetchone()
    assert row is not None
    invalidate_cache(key)
    return _row_to_item_type(row)


async def validate_context(
    conn: AsyncConnection[Any],
    item_type: str,
    context: dict[str, Any],
) -> None:
    """Validate *context* against the schema registered for *item_type*.

    Raises:
        UnknownItemTypeError: If *item_type* is not in the registry.
        ContextValidationError: If *context* violates the schema.
    """
    schema = await _get_cached_schema(conn, item_type)
    if schema is None:
        raise UnknownItemTypeError(item_type)
    try:
        Draft7Validator(schema).validate(context)
    except _JSONSchemaError as e:
        # Build a path-aware message: "context.status: 'foo' is not one of ..."
        path = ".".join(str(p) for p in e.absolute_path)
        prefix = f"context.{path}" if path else "context"
        raise ContextValidationError(
            item_type, f"{prefix}: {e.message}"
        ) from e
