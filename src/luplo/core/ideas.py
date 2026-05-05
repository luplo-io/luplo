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
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.errors import (
    InvalidIdFormatError,
    NotFoundError,
    ValidationError,
)
from luplo.core.glossary import fetch_glossary_map
from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import Idea
from luplo.core.search.tsquery import OrGroup, Term, build_tsquery, parse_user_query

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

# Statuses that reject new ideas. Surfaced both in the INSERT predicate
# and in the diagnostic SELECT below — single source of truth.
_FORBIDDEN_WU_STATUSES: tuple[str, ...] = ("archived", "abandoned")
_FORBIDDEN_WU_STATUSES_SQL = sql.SQL(", ").join(sql.Literal(s) for s in _FORBIDDEN_WU_STATUSES)

_LIMIT_MAX = 1000


def _row_to_idea(row: dict[str, Any]) -> Idea:
    """Coerce a psycopg ``dict_row`` into an :class:`Idea`.

    UUID columns become strings without mutating the input dict — search
    callers may slice the row before passing it in.
    """
    return Idea(
        id=row["id"],
        work_unit_id=row["work_unit_id"],
        project_id=row["project_id"],
        text=row["text"],
        created_at=row["created_at"],
        created_by=str(row["created_by"]) if row.get("created_by") is not None else None,
        redacted_at=row["redacted_at"],
        redacted_by=str(row["redacted_by"]) if row.get("redacted_by") is not None else None,
    )


def _validate_limit(limit: int) -> None:
    if limit <= 0 or limit > _LIMIT_MAX:
        raise ValidationError(f"limit must be between 1 and {_LIMIT_MAX}, got {limit}")


async def _resolve_wu_id(
    conn: AsyncConnection[Any], wu_id: str, project_id: str | None
) -> str | None:
    """Resolve a work_unit_id (full UUID or 8+ hex prefix) to its full id.

    ``project_id`` scopes prefix resolution so prefixes from other projects
    do not collide. Returns ``None`` when no row matches; an invalid-format
    input is treated as not-found rather than a hard error so callers can
    surface a single "not found" message.
    """
    try:
        return await resolve_uuid_prefix(conn, "work_units", wu_id, project_id=project_id)
    except InvalidIdFormatError:
        return None


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

    Accepts a full UUID or 8+ hex prefix for ``work_unit_id``. The work
    unit must exist, belong to ``project_id``, and not be ``archived``
    or ``abandoned``. ``done`` is allowed (retro notes).

    Status check + INSERT happen in a single SQL statement — no TOCTOU
    window between "I checked archived" and "I inserted".

    Raises:
        ValidationError: empty text, cross-project WU, or WU in a status
            that rejects new ideas.
        NotFoundError: ``work_unit_id`` does not resolve to any row.
    """
    if not text.strip():
        raise ValidationError("idea text must not be empty")

    resolved_wu = await _resolve_wu_id(conn, work_unit_id, project_id)
    if resolved_wu is None:
        raise NotFoundError(f"work_unit not found: {work_unit_id}")

    idea_id = id or str(uuid.uuid4())

    async with conn.cursor(row_factory=dict_row) as cur:
        # Single statement: insert iff WU is in this project AND has an
        # acceptable status. No TOCTOU race.
        await cur.execute(
            sql.SQL(
                "INSERT INTO ideas"
                " (id, work_unit_id, project_id, text, created_by)"
                " SELECT %(id)s, id, project_id, %(text)s, %(created_by)s"
                " FROM work_units"
                " WHERE id = %(wu)s"
                "   AND project_id = %(pid)s"
                "   AND status NOT IN ({forbidden})"
                " RETURNING {returning}"
            ).format(returning=_RETURNING, forbidden=_FORBIDDEN_WU_STATUSES_SQL),
            {
                "id": idea_id,
                "wu": resolved_wu,
                "pid": project_id,
                "text": text,
                "created_by": created_by,
            },
        )
        row = await cur.fetchone()
        if row is not None:
            return _row_to_idea(row)

        # Insert refused. Diagnose for a precise error — separate trip
        # is fine here, this is the cold path.
        #
        # Cross-project mismatches collapse to a plain "not found" so a
        # caller cannot probe another project's WU ids by feeding random
        # UUIDs and reading the error message. Within-project status
        # rejection still surfaces a precise reason.
        await cur.execute(
            "SELECT project_id, status FROM work_units WHERE id = %(id)s",
            {"id": resolved_wu},
        )
        wu_row = await cur.fetchone()
        if wu_row is None or wu_row["project_id"] != project_id:
            raise NotFoundError(f"work_unit not found: {work_unit_id}")
        raise ValidationError(
            f"work_unit {work_unit_id} is {wu_row['status']}; cannot add ideas"
        )


# ── Read ─────────────────────────────────────────────────────────


async def list_ideas(
    conn: AsyncConnection[Any],
    *,
    work_unit_id: str,
    project_id: str | None = None,
    limit: int = 100,
    include_redacted: bool = False,
) -> list[Idea]:
    """List ideas for a work unit, newest first.

    Accepts a full UUID or 8+ hex prefix for ``work_unit_id``. ``project_id``
    scopes prefix resolution and is also enforced at the SELECT level so a
    full UUID from another project returns ``[]`` instead of leaking rows.
    Redacted rows are excluded by default; ``include_redacted=True`` opts
    back in (admin / audit flows).
    """
    _validate_limit(limit)
    resolved_wu = await _resolve_wu_id(conn, work_unit_id, project_id)
    if resolved_wu is None:
        return []

    conditions: list[sql.Composable] = [sql.SQL("work_unit_id = %(wu)s")]
    params: dict[str, Any] = {"wu": resolved_wu, "limit": limit}
    if project_id is not None:
        conditions.append(sql.SQL("project_id = %(pid)s"))
        params["pid"] = project_id
    if not include_redacted:
        conditions.append(sql.SQL("redacted_at IS NULL"))
    where = sql.SQL(" AND ").join(conditions)

    query = sql.SQL(
        "SELECT {columns} FROM ideas WHERE {where} ORDER BY created_at DESC LIMIT %(limit)s"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()
        return [_row_to_idea(r) for r in rows]


async def search_ideas(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    query: str | None = None,
    tsquery: str | None = None,
    work_unit_id: str | None = None,
    author: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_redacted: bool = False,
    limit: int = 50,
) -> list[Idea]:
    """Full-text search over ideas, project-scoped.

    Two query modes (mutually exclusive):

    * ``query`` — simple dialect, glossary-expanded. Same dialect as
      :func:`luplo.core.search.pipeline.search` for items.
    * ``tsquery`` — raw ``to_tsquery`` expression. Caller owns synonym
      coverage and validity. Malformed expressions surface as
      ``psycopg.errors.SyntaxError`` from Postgres.

    Filters: ``work_unit_id`` (narrow scope, accepts UUID or hex
    prefix), ``author`` (actor id), ``since`` / ``until`` (datetime —
    caller does string parsing). Both ``query`` and ``tsquery`` may be
    ``None`` for a filter-only search (e.g. "내가 이번 주 적은 아이디어").
    Redacted rows excluded unless ``include_redacted=True``.

    ``include_redacted=True`` cannot be combined with ``query`` /
    ``tsquery`` — the body is masked at the response layer, but a text
    predicate on redacted rows would leak via match/no-match (a keyword
    oracle). Use filter-only mode for audit flows, or fetch raw text
    via the SaaS-side admin path.
    """
    if query is not None and tsquery is not None:
        raise ValidationError("pass either query or tsquery, not both")
    if include_redacted and (query is not None or tsquery is not None):
        raise ValidationError(
            "include_redacted=True cannot be combined with a text query — "
            "match/no-match leaks the redacted body via a keyword oracle. "
            "Filter by author/since/work_unit_id only, or use a SaaS-side "
            "admin path for raw text access."
        )
    _validate_limit(limit)

    conditions: list[sql.Composable] = [sql.SQL("project_id = %(pid)s")]
    params: dict[str, Any] = {"pid": project_id, "limit": limit}

    if not include_redacted:
        conditions.append(sql.SQL("redacted_at IS NULL"))

    if work_unit_id is not None:
        resolved_wu = await _resolve_wu_id(conn, work_unit_id, project_id)
        if resolved_wu is None:
            return []
        conditions.append(sql.SQL("work_unit_id = %(wu)s"))
        params["wu"] = resolved_wu

    if author is not None:
        conditions.append(sql.SQL("created_by = %(author)s"))
        params["author"] = author

    if since is not None:
        conditions.append(sql.SQL("created_at >= %(since_at)s"))
        params["since_at"] = since
    if until is not None:
        conditions.append(sql.SQL("created_at < %(until_at)s"))
        params["until_at"] = until

    rank_expr: sql.Composable = sql.SQL("0::float4")
    if tsquery is not None:
        if not tsquery.strip():
            return []
        params["tsq"] = tsquery
        conditions.append(sql.SQL("to_tsvector('simple', text) @@ to_tsquery('simple', %(tsq)s)"))
        rank_expr = sql.SQL("ts_rank(to_tsvector('simple', text), to_tsquery('simple', %(tsq)s))")
    elif query is not None:
        if not query.strip():
            return []
        clauses = parse_user_query(query)
        if not clauses:
            return []
        expandable: list[str] = []
        for clause in clauses:
            if isinstance(clause, Term) and not clause.phrase and not clause.negated:
                expandable.append(clause.text)
            elif isinstance(clause, OrGroup):
                for m in clause.members:
                    if not m.phrase and not m.negated:
                        expandable.append(m.text)
        glossary_map = await fetch_glossary_map(conn, expandable, project_id)
        tsquery_str = build_tsquery(clauses, glossary_map)
        if not tsquery_str:
            return []
        params["tsq"] = tsquery_str
        conditions.append(sql.SQL("to_tsvector('simple', text) @@ to_tsquery('simple', %(tsq)s)"))
        rank_expr = sql.SQL("ts_rank(to_tsvector('simple', text), to_tsquery('simple', %(tsq)s))")

    where = sql.SQL(" AND ").join(conditions)
    # Compute rank inside a subquery so the outer projection is clean —
    # no per-row dict-comprehension to strip an alias column.
    full = sql.SQL(
        "SELECT {columns} FROM ("
        " SELECT {columns}, {rank} AS _rank FROM ideas"
        " WHERE {where}"
        ") ranked"
        " ORDER BY _rank DESC, created_at DESC"
        " LIMIT %(limit)s"
    ).format(columns=_RETURNING, rank=rank_expr, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(full, params)
        rows = await cur.fetchall()
        return [_row_to_idea(r) for r in rows]


async def redact_idea(
    conn: AsyncConnection[Any],
    *,
    idea_id: str,
    redacted_by: str,
    project_id: str | None = None,
) -> tuple[Idea, bool]:
    """Mark an idea as redacted (idempotent — no-op if already redacted).

    Append-only invariant preserved: the row remains, ``text`` is not
    cleared, and downstream readers filter on ``redacted_at IS NULL``
    by default.

    ``project_id`` (when provided) scopes prefix resolution **and** is
    enforced in the UPDATE/SELECT predicate so a full UUID from another
    project cannot mutate or read this row. Ambiguity errors surface
    only the matched ``id`` values, never the text content.

    Returns ``(idea, newly_redacted)``: ``newly_redacted=True`` on first
    transition to redacted, ``False`` on idempotent retry. Callers can
    skip side-effects (audit, notifications) when ``False``.

    Raises:
        NotFoundError: when ``idea_id`` does not resolve to an existing
            row in this project.
    """
    resolved = await resolve_uuid_prefix(
        conn, "ideas", idea_id, project_id=project_id, label_column="id"
    )
    if resolved is None:
        raise NotFoundError(f"idea not found: {idea_id}")

    update_conditions: list[sql.Composable] = [
        sql.SQL("id = %(id)s"),
        sql.SQL("redacted_at IS NULL"),
    ]
    params: dict[str, Any] = {"id": resolved, "by": redacted_by}
    if project_id is not None:
        update_conditions.append(sql.SQL("project_id = %(pid)s"))
        params["pid"] = project_id
    update_where = sql.SQL(" AND ").join(update_conditions)

    update_query = sql.SQL(
        "UPDATE ideas"
        " SET redacted_at = now(),"
        "     redacted_by = %(by)s"
        " WHERE {where}"
        " RETURNING {columns}"
    ).format(columns=_RETURNING, where=update_where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(update_query, params)
        row = await cur.fetchone()
        if row is not None:
            return _row_to_idea(row), True

        # No row updated → either already redacted (idempotent no-op) or
        # not in this project. Disambiguate via SELECT scoped to project.
        select_conditions: list[sql.Composable] = [sql.SQL("id = %(id)s")]
        select_params: dict[str, Any] = {"id": resolved}
        if project_id is not None:
            select_conditions.append(sql.SQL("project_id = %(pid)s"))
            select_params["pid"] = project_id
        select_where = sql.SQL(" AND ").join(select_conditions)
        select_query = sql.SQL(
            "SELECT {columns} FROM ideas WHERE {where}"
        ).format(columns=_RETURNING, where=select_where)
        await cur.execute(select_query, select_params)
        existing = await cur.fetchone()
        if existing is None:
            # Row exists by id but not in this project — treat as not-found
            # to avoid leaking other-project membership.
            raise NotFoundError(f"idea not found: {idea_id}")
        return _row_to_idea(existing), False


async def get_idea(
    conn: AsyncConnection[Any],
    idea_id: str,
    *,
    project_id: str | None = None,
) -> Idea | None:
    """Fetch a single idea by id (or hex prefix). Includes redacted rows.

    SaaS-side permission checks need to fetch the row before deciding
    whether redact is allowed — hence this is a separate helper rather
    than relying on list/search.

    ``project_id`` scopes prefix resolution **and** is enforced in the
    SELECT predicate so a full UUID from another project returns ``None``
    instead of leaking the row. Ambiguity errors surface only the matched
    ``id`` values.
    """
    resolved = await resolve_uuid_prefix(
        conn, "ideas", idea_id, project_id=project_id, label_column="id"
    )
    if resolved is None:
        return None
    conditions: list[sql.Composable] = [sql.SQL("id = %(id)s")]
    params: dict[str, Any] = {"id": resolved}
    if project_id is not None:
        conditions.append(sql.SQL("project_id = %(pid)s"))
        params["pid"] = project_id
    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL("SELECT {columns} FROM ideas WHERE {where}").format(
        columns=_RETURNING, where=where
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        return _row_to_idea(row) if row else None
