"""UUID prefix resolution for human-typed identifiers.

luplo identifies most rows by UUIDv4 primary keys; the CLI displays them
as 8-character prefixes (``id[:8]``) and accepts the same prefixes back
on input. This module is the single place where prefix → full UUID
resolution happens.

Behaviour:

* A 36-character canonical UUID is returned as-is (fast path; no DB call).
* A hex prefix of at least :data:`MIN_PREFIX_LENGTH` characters is looked
  up against ``<table>.id::text LIKE prefix || '%'`` with ``LIMIT 2``.
  Dashes in the input are ignored so users can paste partially-formatted
  ids.
* Zero matches → :class:`NotFoundError` is the caller's job; this
  function returns ``None`` instead so callers keep their existing
  not-found shapes.
* One match → the full UUID is returned.
* Two or more matches → :class:`AmbiguousIdError` is raised carrying the
  sampled rows. The caller never has to choose silently.

The module is intentionally generic: it takes a table name, an optional
project scope, and a label column used only for ambiguity messages. Each
domain module wraps this with its own ``resolve_*_id`` helper.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.errors import (
    AmbiguousIdError,
    IdTooShortError,
    InvalidIdFormatError,
)

MIN_PREFIX_LENGTH = 8
"""Minimum hex characters required for a prefix lookup.

8 hex characters = 32 bits, which keeps birthday-paradox collision
probability under ~1% for project-scoped tables holding fewer than
~10,000 rows. Below this threshold, requiring more characters is
cheaper than relying on collision luck.
"""

_HEX_RE = re.compile(r"\A[0-9a-f]+\Z")


def _strip(value: str) -> str:
    """Lowercase and remove dashes; everything else is kept as-is."""
    return value.replace("-", "").lower()


def _is_full_uuid(value: str) -> bool:
    """Return True if *value* is a canonical 36-character UUID string."""
    if len(value) != 36:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def resolve_uuid_prefix(
    conn: AsyncConnection[Any],
    table: str,
    value: str,
    *,
    project_id: str | None = None,
    label_column: str = "title",
    project_column: str = "project_id",
) -> str | None:
    """Resolve a UUID or hex prefix against ``<table>.id``.

    Args:
        conn: Open async connection.
        table: Unquoted table name (e.g. ``"items"``).
        value: Either a full canonical UUID string or a hex prefix.
        project_id: Optional project scope. If supplied, the lookup is
            constrained to ``project_column = project_id`` so prefixes
            from other projects do not collide.
        label_column: Column used to label sampled rows in the
            :class:`AmbiguousIdError` message. Tables without a useful
            label can pass ``"id"`` to get the id back as the label.
        project_column: Column name to scope by; defaults to
            ``"project_id"``.

    Returns:
        The full UUID string when exactly one row matches, or ``None``
        when no row matches.

    Raises:
        InvalidIdFormatError: When *value* is neither a full UUID nor a
            valid hex prefix (after stripping dashes).
        IdTooShortError: When *value* is a hex prefix shorter than
            :data:`MIN_PREFIX_LENGTH`.
        AmbiguousIdError: When the prefix matches more than one row.
    """
    if _is_full_uuid(value):
        return value

    stripped = _strip(value)
    if not stripped or not _HEX_RE.fullmatch(stripped):
        raise InvalidIdFormatError(value)
    if len(stripped) > 32:
        raise InvalidIdFormatError(value)
    if len(stripped) < MIN_PREFIX_LENGTH:
        raise IdTooShortError(value, MIN_PREFIX_LENGTH)

    # Build canonical-form prefix for LIKE: insert dashes so the prefix
    # aligns with the way Postgres stringifies UUIDs.
    like_pattern = _to_canonical_prefix(stripped) + "%"

    where: list[sql.Composable] = [sql.SQL("id LIKE %(p)s")]
    params: dict[str, Any] = {"p": like_pattern}
    if project_id is not None:
        where.append(sql.SQL("{col} = %(pid)s").format(col=sql.Identifier(project_column)))
        params["pid"] = project_id

    query = sql.SQL("SELECT id, {label} AS label FROM {table} WHERE {where} LIMIT 2").format(
        label=sql.Identifier(label_column),
        table=sql.Identifier(table),
        where=sql.SQL(" AND ").join(where),
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()

    if not rows:
        return None
    if len(rows) == 1:
        return str(rows[0]["id"])
    matches = [(str(r["id"]), str(r["label"]) if r["label"] is not None else "") for r in rows]
    raise AmbiguousIdError(value, matches)


def build_seed_clause(
    value: str,
    params: dict[str, Any],
) -> sql.Composable:
    """Build a SQL fragment that selects rows matching *value* by id.

    Returns a clause suitable for a WHERE position (no leading ``WHERE``).
    Mutates *params* in place: adds the binding under the key ``"seed"``.

    Use this when the caller needs to embed prefix matching inside a
    larger query (e.g. a recursive CTE that walks a supersede chain
    forward from any matching seed). For standalone lookups, prefer
    :func:`resolve_uuid_prefix`.

    Raises:
        InvalidIdFormatError: When *value* is not a UUID or hex prefix.
        IdTooShortError: When the hex prefix is shorter than the minimum.
    """
    if _is_full_uuid(value):
        params["seed"] = value
        return sql.SQL("id = %(seed)s")

    stripped = _strip(value)
    if not stripped or not _HEX_RE.fullmatch(stripped):
        raise InvalidIdFormatError(value)
    if len(stripped) > 32:
        raise InvalidIdFormatError(value)
    if len(stripped) < MIN_PREFIX_LENGTH:
        raise IdTooShortError(value, MIN_PREFIX_LENGTH)

    params["seed"] = _to_canonical_prefix(stripped) + "%"
    return sql.SQL("id LIKE %(seed)s")


def _to_canonical_prefix(stripped_hex: str) -> str:
    """Insert dashes into *stripped_hex* at the canonical UUID positions.

    UUID canonical form is ``8-4-4-4-12`` (32 hex chars + 4 dashes).
    For shorter inputs we insert only the dashes that fall inside the
    prefix length, so ``"a85a455532"`` becomes ``"a85a4555-32"`` and
    matches Postgres' UUID text rendering at LIKE time.
    """
    boundaries = (8, 12, 16, 20)
    out: list[str] = []
    for i, ch in enumerate(stripped_hex):
        if i in boundaries:
            out.append("-")
        out.append(ch)
    return "".join(out)
