"""CRUD + query expansion for the glossary tables.

The glossary is luplo's strict-first terminology layer.  Terms are extracted
from items, normalised, and grouped.  Approved groups power the search
pipeline's query expansion — e.g. ``"vendor"`` expands to
``(vendor | shop | NPC벤더)``.

Three tables: ``glossary_groups``, ``glossary_terms``, ``glossary_rejections``.
No aggressive clustering — strict LLM matching only, with a human curation
queue for anything uncertain.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.id_resolve import resolve_uuid_prefix
from luplo.core.models import GlossaryGroup, GlossaryRejection, GlossaryTerm

# ── Column definitions ───────────────────────────────────────────

_GROUP_COLUMNS = (
    "id",
    "project_id",
    "scope",
    "scope_id",
    "canonical",
    "definition",
    "created_at",
    "created_by",
    "last_reviewed_at",
    "last_reviewed_by",
)
_GROUP_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _GROUP_COLUMNS)

_TERM_COLUMNS = (
    "id",
    "group_id",
    "surface",
    "normalized",
    "is_protected",
    "status",
    "source_item_id",
    "context_snippet",
    "decided_by",
    "decided_at",
    "created_at",
)
_TERM_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _TERM_COLUMNS)


def _row_to_group(row: dict[str, Any]) -> GlossaryGroup:
    for col in ("created_by", "last_reviewed_by"):
        if row.get(col) is not None:
            row[col] = str(row[col])
    return GlossaryGroup(**row)


def _row_to_term(row: dict[str, Any]) -> GlossaryTerm:
    if row.get("decided_by") is not None:
        row["decided_by"] = str(row["decided_by"])
    return GlossaryTerm(**row)


# ── Groups ───────────────────────────────────────────────────────


async def create_glossary_group(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    canonical: str,
    definition: str | None = None,
    scope: str = "project",
    scope_id: str | None = None,
    created_by: str | None = None,
    id: str | None = None,
) -> GlossaryGroup:
    """Create a glossary group (a semantic unit with one canonical term).

    Args:
        conn: Async psycopg connection.
        project_id: Owning project.
        canonical: The canonical surface form for this concept.
        definition: Optional one-line definition.
        scope: Scope level — ``"project"`` (default) or ``"system"``.
        scope_id: System ID when scope is ``"system"``.
        created_by: Actor who created this group.
        id: Optional ID override.

    Returns:
        The new ``GlossaryGroup``.
    """
    group_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO glossary_groups"
        " (id, project_id, scope, scope_id, canonical, definition, created_by)"
        " VALUES (%(id)s, %(project_id)s, %(scope)s, %(scope_id)s,"
        "  %(canonical)s, %(definition)s, %(created_by)s)"
        " RETURNING {returning}"
    ).format(returning=_GROUP_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": group_id,
                "project_id": project_id,
                "scope": scope,
                "scope_id": scope_id,
                "canonical": canonical,
                "definition": definition,
                "created_by": created_by,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_group(row)


async def get_glossary_group(
    conn: AsyncConnection[Any],
    group_id: str,
    *,
    project_id: str | None = None,
) -> GlossaryGroup | None:
    """Fetch a glossary group by ID or hex prefix (≥8 chars).

    Returns ``None`` when nothing matches; raises
    :class:`AmbiguousIdError` when a prefix matches multiple groups.
    Pass *project_id* to scope prefix lookups.
    """
    resolved = await resolve_uuid_prefix(
        conn,
        "glossary_groups",
        group_id,
        project_id=project_id,
        label_column="canonical",
    )
    if resolved is None:
        return None
    query = sql.SQL("SELECT {columns} FROM glossary_groups WHERE id = %(id)s").format(
        columns=_GROUP_RETURNING
    )

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": resolved})
        row = await cur.fetchone()
        return _row_to_group(row) if row else None


async def list_glossary_groups(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    needs_review: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[GlossaryGroup]:
    """List glossary groups, optionally filtering to those needing review.

    ``needs_review=True`` returns groups that have pending terms.
    """
    if needs_review:
        query = sql.SQL(
            "SELECT DISTINCT {columns} FROM glossary_groups gg"
            " JOIN glossary_terms gt ON gt.group_id = gg.id"
            " WHERE gg.project_id = %(project_id)s AND gt.status = 'pending'"
            " ORDER BY gg.created_at DESC"
            " LIMIT %(limit)s OFFSET %(offset)s"
        ).format(
            columns=sql.SQL(", ").join(sql.SQL("gg.") + sql.Identifier(c) for c in _GROUP_COLUMNS)
        )
    else:
        query = sql.SQL(
            "SELECT {columns} FROM glossary_groups"
            " WHERE project_id = %(project_id)s"
            " ORDER BY canonical"
            " LIMIT %(limit)s OFFSET %(offset)s"
        ).format(columns=_GROUP_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
            },
        )
        return [_row_to_group(row) for row in await cur.fetchall()]


# ── Terms ────────────────────────────────────────────────────────


async def create_glossary_term(
    conn: AsyncConnection[Any],
    *,
    group_id: str | None,
    surface: str,
    normalized: str,
    is_protected: bool = False,
    status: str = "pending",
    source_item_id: str | None = None,
    context_snippet: str | None = None,
    id: str | None = None,
) -> GlossaryTerm:
    """Create a glossary term (a surface form belonging to a group)."""
    term_id = id or str(uuid.uuid4())
    query = sql.SQL(
        "INSERT INTO glossary_terms"
        " (id, group_id, surface, normalized, is_protected, status,"
        "  source_item_id, context_snippet)"
        " VALUES (%(id)s, %(group_id)s, %(surface)s, %(normalized)s,"
        "  %(is_protected)s, %(status)s, %(source_item_id)s, %(context_snippet)s)"
        " RETURNING {returning}"
    ).format(returning=_TERM_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": term_id,
                "group_id": group_id,
                "surface": surface,
                "normalized": normalized,
                "is_protected": is_protected,
                "status": status,
                "source_item_id": source_item_id,
                "context_snippet": context_snippet,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_term(row)


async def list_pending_terms(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    limit: int = 50,
) -> list[GlossaryTerm]:
    """List terms awaiting human curation.

    Includes both grouped pending terms (via group → project) and orphan
    pending terms (via source_item → project).
    """
    t_cols = sql.SQL(", ").join(sql.SQL("gt.") + sql.Identifier(c) for c in _TERM_COLUMNS)
    query = sql.SQL(
        "SELECT {columns} FROM glossary_terms gt"
        " LEFT JOIN glossary_groups gg ON gt.group_id = gg.id"
        " LEFT JOIN items i ON gt.source_item_id = i.id"
        " WHERE gt.status = 'pending'"
        "   AND (gg.project_id = %(project_id)s OR i.project_id = %(project_id)s)"
        " ORDER BY gt.created_at DESC"
        " LIMIT %(limit)s"
    ).format(columns=t_cols)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"project_id": project_id, "limit": limit})
        return [_row_to_term(row) for row in await cur.fetchall()]


# ── Curation actions ─────────────────────────────────────────────


async def approve_term(
    conn: AsyncConnection[Any],
    term_id: str,
    *,
    group_id: str,
    actor_id: str,
    as_canonical: bool = False,
) -> GlossaryTerm | None:
    """Approve a pending term into a group.

    Args:
        conn: Async psycopg connection.
        term_id: The term to approve.
        group_id: Target group.
        actor_id: Who approved.
        as_canonical: If ``True``, set status to ``"canonical"``
            (group should have at most one). Otherwise ``"alias"``.

    Returns:
        The updated term, or ``None`` if not found.
    """
    new_status = "canonical" if as_canonical else "alias"
    query = sql.SQL(
        "UPDATE glossary_terms SET"
        "  group_id = %(group_id)s,"
        "  status = %(status)s,"
        "  decided_by = %(actor_id)s,"
        "  decided_at = now()"
        " WHERE id = %(term_id)s"
        " RETURNING {returning}"
    ).format(returning=_TERM_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "term_id": term_id,
                "group_id": group_id,
                "status": new_status,
                "actor_id": actor_id,
            },
        )
        row = await cur.fetchone()
        return _row_to_term(row) if row else None


async def reject_term(
    conn: AsyncConnection[Any],
    term_id: str,
    *,
    actor_id: str,
    reason: str | None = None,
) -> GlossaryRejection | None:
    """Reject a term — the system will never re-propose this match.

    Sets the term's status to ``"rejected"`` and inserts a permanent
    record into ``glossary_rejections``.

    Returns:
        The rejection record, or ``None`` if the term was not found.
    """
    # Get term info for the rejection record
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "UPDATE glossary_terms SET"
            "  status = 'rejected', decided_by = %(actor)s, decided_at = now()"
            " WHERE id = %(id)s"
            " RETURNING group_id, surface",
            {"id": term_id, "actor": actor_id},
        )
        term_row = await cur.fetchone()
        if not term_row or not term_row["group_id"]:
            return None

        # Record permanent rejection
        await cur.execute(
            "INSERT INTO glossary_rejections (group_id, rejected_term, rejected_by, reason)"
            " VALUES (%(group_id)s, %(term)s, %(actor)s, %(reason)s)"
            " ON CONFLICT (group_id, rejected_term) DO NOTHING",
            {
                "group_id": term_row["group_id"],
                "term": term_row["surface"],
                "actor": actor_id,
                "reason": reason,
            },
        )

        return GlossaryRejection(
            group_id=term_row["group_id"],
            rejected_term=term_row["surface"],
            rejected_by=actor_id,
            rejected_at=None,  # type: ignore[arg-type]  # filled by DB default
            reason=reason,
        )


async def merge_groups(
    conn: AsyncConnection[Any],
    source_group_id: str,
    target_group_id: str,
    *,
    actor_id: str,
) -> GlossaryGroup | None:
    """Merge source group into target — move all terms, delete source.

    Returns:
        The target ``GlossaryGroup`` after merge, or ``None`` if
        either group was not found.
    """
    # Move all terms from source to target
    result = await conn.execute(
        "UPDATE glossary_terms SET group_id = %(target)s WHERE group_id = %(source)s",
        {"source": source_group_id, "target": target_group_id},
    )
    if result.rowcount == 0:
        # Source had no terms or doesn't exist — check if target exists
        target = await get_glossary_group(conn, target_group_id)
        if not target:
            return None

    # Delete source group
    await conn.execute(
        "DELETE FROM glossary_groups WHERE id = %(id)s",
        {"id": source_group_id},
    )

    # Update review timestamp on target
    query = sql.SQL(
        "UPDATE glossary_groups SET"
        "  last_reviewed_at = now(), last_reviewed_by = %(actor)s"
        " WHERE id = %(id)s"
        " RETURNING {returning}"
    ).format(returning=_GROUP_RETURNING)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"id": target_group_id, "actor": actor_id})
        row = await cur.fetchone()
        return _row_to_group(row) if row else None


async def split_term(
    conn: AsyncConnection[Any],
    term_id: str,
    *,
    new_canonical: str,
    actor_id: str,
) -> GlossaryGroup | None:
    """Split a term out of its group into a new group.

    The term becomes the canonical member of the new group.

    Args:
        conn: Async psycopg connection.
        term_id: The term to split out.
        new_canonical: Canonical name for the new group.
        actor_id: Who performed the split.

    Returns:
        The new ``GlossaryGroup``, or ``None`` if the term was not found.
    """
    # Get term's current group to inherit project_id
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT gt.id, gg.project_id FROM glossary_terms gt"
            " JOIN glossary_groups gg ON gt.group_id = gg.id"
            " WHERE gt.id = %(id)s",
            {"id": term_id},
        )
        row = await cur.fetchone()
        if not row:
            return None
        project_id = row["project_id"]

    # Create new group
    new_group = await create_glossary_group(
        conn,
        project_id=project_id,
        canonical=new_canonical,
        created_by=actor_id,
    )

    # Move term to new group as canonical
    await conn.execute(
        "UPDATE glossary_terms SET"
        "  group_id = %(group_id)s,"
        "  status = 'canonical',"
        "  decided_by = %(actor)s,"
        "  decided_at = now()"
        " WHERE id = %(id)s",
        {"id": term_id, "group_id": new_group.id, "actor": actor_id},
    )

    return new_group


# ── Query expansion ──────────────────────────────────────────────


async def expand_query(
    conn: AsyncConnection[Any],
    query: str,
    project_id: str,
) -> str:
    """Expand a search query using the glossary.

    Each word in *query* is looked up in approved glossary terms.  If a
    match is found, all approved surface forms in the same group are
    OR'd together.  Unmatched words pass through unchanged.  Groups are
    AND'd.

    Example::

        >>> await expand_query(conn, "vendor budget", "proj-1")
        "(vendor | shop | NPC벤더) & budget"

    Args:
        conn: Async psycopg connection.
        query: Raw user query string.
        project_id: Project scope for glossary lookup.

    Returns:
        Expanded tsquery-compatible string.
    """
    words = query.strip().split()
    if not words:
        return ""

    normalised = [w.lower() for w in words]

    # Step 1: Find group_id for each input word
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT gt.normalized, gt.group_id"
            " FROM glossary_terms gt"
            " JOIN glossary_groups gg ON gt.group_id = gg.id"
            " WHERE gt.normalized = ANY(%(words)s)"
            "   AND gt.status IN ('canonical', 'alias')"
            "   AND gg.project_id = %(project_id)s",
            {"words": normalised, "project_id": project_id},
        )
        word_to_group: dict[str, str] = {}
        for row in await cur.fetchall():
            word_to_group[row["normalized"]] = row["group_id"]

    group_ids = list(set(word_to_group.values()))

    # Step 2: Get all approved surfaces per group
    group_surfaces: dict[str, list[str]] = {}
    if group_ids:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT group_id, surface FROM glossary_terms"
                " WHERE group_id = ANY(%(ids)s)"
                "   AND status IN ('canonical', 'alias')",
                {"ids": group_ids},
            )
            for row in await cur.fetchall():
                group_surfaces.setdefault(row["group_id"], []).append(row["surface"])

    # Step 3: Build expanded query parts
    parts: list[str] = []
    for word, norm in zip(words, normalised):
        gid = word_to_group.get(norm)
        if gid and gid in group_surfaces:
            surfaces = group_surfaces[gid]
            if len(surfaces) > 1:
                parts.append("(" + " | ".join(sorted(surfaces)) + ")")
            else:
                parts.append(surfaces[0])
        else:
            parts.append(word)

    return " & ".join(parts)
