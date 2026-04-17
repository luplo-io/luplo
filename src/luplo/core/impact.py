"""Impact analysis — traverse typed edges to find an item's blast radius.

Given an item, walk outgoing ``links`` edges whose ``link_type`` is one of
``depends`` / ``blocks`` / ``supersedes`` / ``conflicts`` up to a fixed
depth ceiling, and return the set of items reachable through those edges.

The ceiling (:data:`MAX_IMPACT_DEPTH`) is a product-level design
principle, enforced server-side: there is no config knob, no ``--deep``
override, no per-tenant exception. If a caller needs more than five
hops, the model needs decomposing — not this limit raising.

Traversal is **outgoing only** (``links.from_item_id = parent``). Edge
direction has an intended meaning for each type; the traversal layer
does not second-guess it.

Cycles are handled inside the recursive CTE via a path array: an item
that is already on the current walk is not traversed a second time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core import items as _items
from luplo.core.errors import NotFoundError, ValidationError
from luplo.core.items import ITEM_COLUMNS, row_to_item
from luplo.core.models import Item

TRAVERSABLE_LINK_TYPES: frozenset[str] = frozenset(
    {"depends", "blocks", "supersedes", "conflicts"}
)
"""Edge types that ``impact`` will walk. Other link types are ignored."""

MAX_IMPACT_DEPTH: int = 5
"""Hard ceiling on traversal depth. Not user-configurable."""

MIN_IMPACT_DEPTH: int = 1
"""Depth ``0`` would return only the root, so the smallest useful value is ``1``."""


@dataclass(slots=True, frozen=True)
class ImpactEdge:
    """One hop in an impact traversal, from ``parent_id`` to ``child_id``."""

    parent_id: str
    child_id: str
    link_type: str
    depth: int


@dataclass(slots=True, frozen=True)
class ImpactNode:
    """An item reached by traversal, together with the edge that first reached it.

    ``depth`` is the shortest-path depth from the root (``1`` means the
    item is a direct neighbour of the root).
    """

    item: Item
    depth: int
    via: ImpactEdge


@dataclass(slots=True)
class ImpactResult:
    """Structured output of :func:`impact`.

    ``nodes`` is deduplicated: every item appears once, at its
    shortest-path depth. Ordering is ``(depth ASC, title ASC,
    link_type ASC)`` — stable across runs so diffs are readable.
    """

    root: Item
    nodes: list[ImpactNode]
    depth_requested: int


async def impact(
    conn: AsyncConnection[Any],
    item_id: str,
    project_id: str,
    *,
    depth: int = MAX_IMPACT_DEPTH,
) -> ImpactResult:
    """Run an impact analysis from *item_id*.

    Args:
        conn: Async psycopg connection.
        item_id: Root item (full ID or hex prefix — resolved via
            :func:`luplo.core.id_resolve.resolve_uuid_prefix`).
        project_id: Project scope. Traversal never crosses projects; any
            edge pointing at an item outside this project is dropped.
        depth: Maximum hops to traverse. Clamped to
            ``[MIN_IMPACT_DEPTH, MAX_IMPACT_DEPTH]`` — out-of-range values
            raise :class:`ValidationError`.

    Returns:
        An :class:`ImpactResult` carrying the root item and the list of
        reachable items ordered by ``(depth, title, link_type)``.

    Raises:
        ValidationError: If ``depth`` is outside the allowed range.
        NotFoundError: If the root item does not exist in this project
            or is soft-deleted.
    """
    if depth < MIN_IMPACT_DEPTH or depth > MAX_IMPACT_DEPTH:
        raise ValidationError(
            f"depth must be between {MIN_IMPACT_DEPTH} and {MAX_IMPACT_DEPTH}, got {depth}"
        )

    root = await _items.get_item(conn, item_id, project_id=project_id)
    if root is None:
        raise NotFoundError(f"Item {item_id!r} not found in project {project_id!r}")

    item_columns_aliased = sql.SQL(", ").join(
        sql.SQL("i.") + sql.Identifier(c) for c in ITEM_COLUMNS
    )

    query = sql.SQL(
        "WITH RECURSIVE traversal AS ("
        "  SELECT"
        "    %(root_id)s::text AS item_id,"
        "    0 AS depth,"
        "    ARRAY[%(root_id)s::text] AS path,"
        "    NULL::text AS parent_id,"
        "    NULL::text AS link_type"
        "  UNION ALL"
        "  SELECT"
        "    l.to_item_id,"
        "    t.depth + 1,"
        "    t.path || l.to_item_id,"
        "    l.from_item_id,"
        "    l.link_type"
        "  FROM traversal t"
        "  JOIN links l ON l.from_item_id = t.item_id"
        "  WHERE t.depth < %(max_depth)s"
        "    AND l.link_type = ANY(%(types)s::text[])"
        "    AND NOT (l.to_item_id = ANY(t.path))"
        ")"
        " SELECT t.depth, t.parent_id, t.link_type, {columns}"
        " FROM traversal t"
        " JOIN items i ON i.id = t.item_id"
        " WHERE i.project_id = %(project_id)s"
        "   AND i.deleted_at IS NULL"
        "   AND t.depth > 0"
        " ORDER BY t.depth, i.title, t.link_type"
    ).format(columns=item_columns_aliased)

    params: dict[str, Any] = {
        "root_id": root.id,
        "max_depth": depth,
        "types": sorted(TRAVERSABLE_LINK_TYPES),
        "project_id": project_id,
    }

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()

    seen: set[str] = set()
    nodes: list[ImpactNode] = []
    for row in rows:
        child_id: str = row["id"]
        if child_id in seen:
            continue
        seen.add(child_id)

        parent_id: str = row["parent_id"]
        link_type: str = row["link_type"]
        hop_depth: int = row["depth"]

        edge = ImpactEdge(
            parent_id=parent_id,
            child_id=child_id,
            link_type=link_type,
            depth=hop_depth,
        )
        nodes.append(
            ImpactNode(
                item=row_to_item(row),
                depth=hop_depth,
                via=edge,
            )
        )

    return ImpactResult(root=root, nodes=nodes, depth_requested=depth)
