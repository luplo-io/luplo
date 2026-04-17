"""Task domain — a thin wrapper around items where ``item_type='task'``.

Tasks live in ``items`` (D3 — no separate table). Each state transition
creates a new row that supersedes the previous one (standard supersede
pattern); ``reorder_tasks`` is the one exception, which updates
``context.sort_order`` in place per P10.

User-facing task identity = supersede-chain head. Mutating helpers accept
*any* id in the chain and resolve to the head before acting; the returned
``Item`` is the new head.

Concurrency (P7): no DB-level UNIQUE for in-progress tasks. ``start_task``
takes a ``SELECT … FOR UPDATE`` on the candidate "current in-progress"
row(s) per work unit and raises ``TaskAlreadyInProgressError`` if any
exists. All start paths must go through this function.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.errors import (
    AmbiguousIdError,
    TaskAlreadyInProgressError,
    TaskNotFoundError,
    TaskStateTransitionError,
)
from luplo.core.id_resolve import build_seed_clause
from luplo.core.items import create_item, get_item_including_deleted, row_to_item
from luplo.core.models import Item, ItemCreate

ITEM_TYPE = "task"

# Legal status transitions. Terminal: 'done', 'skipped'.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"in_progress", "blocked", "skipped"},
    "in_progress": {"done", "blocked"},
    "blocked": {"in_progress", "skipped"},
    "done": set(),
    "skipped": set(),
}


def _check_transition(task_id: str, current: str, target: str) -> None:
    """Raise TaskStateTransitionError when *target* is not allowed."""
    if target not in _LEGAL_TRANSITIONS.get(current, set()):
        raise TaskStateTransitionError(task_id, current, target)


# ── Head resolution ─────────────────────────────────────────────


async def _resolve_head(
    conn: AsyncConnection[Any],
    any_chain_id: str,
    *,
    for_update: bool = False,
    project_id: str | None = None,
) -> Item:
    """Walk the supersede chain forward from *any_chain_id* and return the head.

    Accepts a full UUID or a hex prefix (≥8 chars). When a prefix matches
    multiple seed rows the recursive CTE walks each forward; rows in the
    same chain naturally collapse to one head, so prefix matches inside a
    single chain are not ambiguous. Truly distinct chain heads raise
    :class:`AmbiguousIdError`.

    Raises:
        TaskNotFoundError: When no row matches or the resolved head is
            not a task.
        AmbiguousIdError: When the prefix resolves to multiple heads
            across distinct chains.
    """
    params: dict[str, Any] = {}
    seed = build_seed_clause(any_chain_id, params)
    if project_id is not None:
        params["pid"] = project_id
        seed = sql.SQL("({seed}) AND project_id = %(pid)s").format(seed=seed)

    lock = sql.SQL("FOR UPDATE") if for_update else sql.SQL("")
    query = sql.SQL("""
        WITH RECURSIVE chain(id) AS (
            SELECT id FROM items WHERE {seed}
            UNION
            SELECT i.id FROM items i, chain c WHERE i.supersedes_id = c.id
        )
        SELECT items.* FROM items
        JOIN chain USING (id)
        WHERE items.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id
          )
        {lock}
        LIMIT 2
    """).format(seed=seed, lock=lock)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()
    if not rows:
        raise TaskNotFoundError(any_chain_id)
    task_rows = [r for r in rows if r["item_type"] == ITEM_TYPE]
    if not task_rows:
        raise TaskNotFoundError(any_chain_id)
    if len(task_rows) > 1:
        matches = [(str(r["id"]), str(r.get("title") or "")) for r in task_rows]
        raise AmbiguousIdError(any_chain_id, matches)
    return row_to_item(task_rows[0])


# ── Create ──────────────────────────────────────────────────────


async def create_task(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    work_unit_id: str,
    title: str,
    actor_id: str,
    sort_order: int | None = None,
    systems: list[str] | None = None,
    body: str | None = None,
    context_extra: dict[str, Any] | None = None,
) -> Item:
    """Create a new task in ``proposed`` status.

    If *sort_order* is None, it defaults to ``max(sort_order) + 10`` for
    the work unit (gap-strategy starting at 10).
    """
    if sort_order is None:
        sort_order = await _next_sort_order(conn, work_unit_id)

    context: dict[str, Any] = {"status": "proposed", "sort_order": sort_order}
    if systems:
        context["systems"] = systems
    if context_extra:
        context.update(context_extra)

    return await create_item(
        conn,
        ItemCreate(
            project_id=project_id,
            actor_id=actor_id,
            item_type=ITEM_TYPE,
            title=title,
            body=body,
            work_unit_id=work_unit_id,
            system_ids=systems or [],
            context=context,
        ),
    )


async def _next_sort_order(conn: AsyncConnection[Any], work_unit_id: str) -> int:
    """Return the next sort_order using gap-10 strategy."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COALESCE(MAX((context->>'sort_order')::int), 0) + 10"
            " FROM items"
            " WHERE work_unit_id = %s AND item_type = 'task' AND deleted_at IS NULL",
            (work_unit_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 10


# ── Read ────────────────────────────────────────────────────────


async def get_task(
    conn: AsyncConnection[Any],
    task_id: str,
    *,
    project_id: str | None = None,
) -> Item | None:
    """Fetch the head of the chain containing *task_id*.

    Accepts a full UUID or a hex prefix (≥8 chars). Returns ``None`` if
    no row matches; raises :class:`AmbiguousIdError` if a prefix matches
    distinct chains.
    """
    try:
        return await _resolve_head(conn, task_id, project_id=project_id)
    except TaskNotFoundError:
        return None


async def list_tasks(
    conn: AsyncConnection[Any],
    work_unit_id: str,
    *,
    status: str | None = None,
) -> list[Item]:
    """List the heads of every task chain in *work_unit_id*.

    Ordered by ``sort_order`` ASC, then ``created_at``.
    """
    conditions: list[sql.Composable] = [
        sql.SQL("work_unit_id = %(wu)s"),
        sql.SQL("item_type = 'task'"),
        sql.SQL("deleted_at IS NULL"),
        sql.SQL("NOT EXISTS (SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id)"),
    ]
    params: dict[str, Any] = {"wu": work_unit_id}
    if status is not None:
        conditions.append(sql.SQL("context->>'status' = %(status)s"))
        params["status"] = status
    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL(
        "SELECT items.* FROM items"
        " WHERE {where}"
        " ORDER BY (context->>'sort_order')::int NULLS LAST, created_at"
    ).format(where=where)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [row_to_item(r) for r in await cur.fetchall()]


async def get_in_progress_task(conn: AsyncConnection[Any], work_unit_id: str) -> Item | None:
    """Return the single in_progress task head for *work_unit_id*, or ``None``."""
    rows = await list_tasks(conn, work_unit_id, status="in_progress")
    return rows[0] if rows else None


# ── State transitions ───────────────────────────────────────────


async def _supersede_with_context(
    conn: AsyncConnection[Any],
    head: Item,
    new_context: dict[str, Any],
    actor_id: str,
) -> Item:
    """Create a new task row that supersedes *head* with *new_context*."""
    return await create_item(
        conn,
        ItemCreate(
            project_id=head.project_id,
            actor_id=actor_id,
            item_type=ITEM_TYPE,
            title=head.title,
            body=head.body,
            work_unit_id=head.work_unit_id,
            system_ids=head.system_ids,
            tags=head.tags,
            supersedes_id=head.id,
            context=new_context,
        ),
    )


async def start_task(
    conn: AsyncConnection[Any],
    task_id: str,
    *,
    actor_id: str,
    project_id: str | None = None,
) -> Item:
    """Transition a task to ``in_progress``.

    P7: enforces the "at most one in_progress per work_unit" invariant in
    the domain layer (no DB UNIQUE) by taking a row-level lock on any
    candidate in_progress heads in the same work unit.

    Passing *project_id* scopes prefix resolution to a single project, so
    an ``abc12345`` prefix that happens to match a task in a different
    project can never silently mutate that other row.

    Raises:
        TaskNotFoundError, TaskStateTransitionError, TaskAlreadyInProgressError.
    """
    head = await _resolve_head(conn, task_id, project_id=project_id)
    current_status = head.context.get("status", "proposed")
    _check_transition(head.id, current_status, "in_progress")

    # Lock any current in_progress heads in the same WU. The lock is held
    # for the rest of the transaction; concurrent start_task calls block
    # here and re-evaluate after the first commits.
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id FROM items"
            " WHERE work_unit_id = %s"
            "   AND item_type = 'task'"
            "   AND context->>'status' = 'in_progress'"
            "   AND deleted_at IS NULL"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id"
            "   )"
            " FOR UPDATE",
            (head.work_unit_id,),
        )
        rows = await cur.fetchall()
    if rows:
        raise TaskAlreadyInProgressError(head.work_unit_id or "", str(rows[0]["id"]))

    new_context = {**head.context, "status": "in_progress"}
    new_context.pop("blocked_reason", None)
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def complete_task(
    conn: AsyncConnection[Any],
    task_id: str,
    *,
    actor_id: str,
    summary: str | None = None,
    project_id: str | None = None,
) -> Item:
    """Transition a task to ``done``.

    Pass *project_id* to scope prefix resolution to a single project.
    """
    head = await _resolve_head(conn, task_id, project_id=project_id)
    _check_transition(head.id, head.context.get("status", ""), "done")
    new_context = {**head.context, "status": "done"}
    if summary:
        new_context["summary"] = summary
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def block_task(
    conn: AsyncConnection[Any],
    task_id: str,
    *,
    actor_id: str,
    reason: str,
    project_id: str | None = None,
) -> Item:
    """Transition a task to ``blocked`` with a reason.

    The associated decision item is created by ``LocalBackend.block_task``
    (cross-cutting), not here. Pass *project_id* to scope prefix
    resolution to a single project.
    """
    head = await _resolve_head(conn, task_id, project_id=project_id)
    _check_transition(head.id, head.context.get("status", ""), "blocked")
    new_context = {**head.context, "status": "blocked", "blocked_reason": reason}
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def skip_task(
    conn: AsyncConnection[Any],
    task_id: str,
    *,
    actor_id: str,
    reason: str | None = None,
    project_id: str | None = None,
) -> Item:
    """Transition a task to ``skipped``.

    Pass *project_id* to scope prefix resolution to a single project.
    """
    head = await _resolve_head(conn, task_id, project_id=project_id)
    _check_transition(head.id, head.context.get("status", ""), "skipped")
    new_context = {**head.context, "status": "skipped"}
    if reason:
        new_context["skip_reason"] = reason
    return await _supersede_with_context(conn, head, new_context, actor_id)


# ── Reorder (in-place per P10) ──────────────────────────────────


async def reorder_tasks(
    conn: AsyncConnection[Any],
    work_unit_id: str,
    task_ids: list[str],
    *,
    actor_id: str,
    project_id: str | None = None,
) -> list[Item]:
    """Set sort_order for a list of tasks (gap-10 strategy).

    Per P10, this is an in-place UPDATE: no new supersede rows, no
    items_history entries. The audit trail is a single ``item.update``
    entry recorded by the LocalBackend wrapper.

    *task_ids* may include any id in each chain — they are resolved to
    heads internally. The returned list mirrors the input order with the
    refreshed head rows.

    Raises ``TaskNotFoundError`` if any id cannot be resolved or its head
    does not belong to *work_unit_id*.
    """
    if not task_ids:
        return []

    heads: list[Item] = []
    for tid in task_ids:
        head = await _resolve_head(conn, tid, project_id=project_id)
        if head.work_unit_id != work_unit_id:
            raise TaskNotFoundError(tid)
        heads.append(head)

    # Single-statement update for atomicity. CASE WHEN keeps one round-trip.
    new_orders = {h.id: (i + 1) * 10 for i, h in enumerate(heads)}
    case_clauses = sql.SQL(" ").join(
        sql.SQL("WHEN id = {hid} THEN {n}").format(hid=sql.Literal(hid), n=sql.Literal(n))
        for hid, n in new_orders.items()
    )
    ids_list = sql.SQL(", ").join(sql.Literal(h.id) for h in heads)
    query = sql.SQL("""
        UPDATE items
           SET context = jsonb_set(
                   context,
                   '{{sort_order}}',
                   to_jsonb((CASE {cases} END)::int),
                   true
               ),
               updated_at = now()
         WHERE id IN ({ids})
    """).format(cases=case_clauses, ids=ids_list)
    await conn.execute(query)

    # Re-fetch heads with updated sort_order.
    refreshed: list[Item] = []
    for h in heads:
        fresh = await get_item_including_deleted(conn, h.id)
        assert fresh is not None
        refreshed.append(fresh)
    return refreshed
