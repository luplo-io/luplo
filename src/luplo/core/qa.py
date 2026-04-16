"""QA check domain — a thin wrapper around items where ``item_type='qa_check'``.

Tasks/items get verified by qa_checks. State changes initiated by users
(start/pass/fail/block/skip/assign) are supersede operations; the
revalidation trigger that demotes ``passed`` → ``pending`` after a target
item gets superseded is in-place + audit (P8) and lives in
``LocalBackend.create_item`` — not here.

Targets are stored as ``context.target_item_ids`` and ``context.target_task_ids``
arrays. GIN indexes from migration 0003 make reverse lookups fast.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.errors import (
    AmbiguousIdError,
    QACheckNotFoundError,
    QAStateTransitionError,
)
from luplo.core.id_resolve import build_seed_clause
from luplo.core.items import _row_to_item, create_item
from luplo.core.models import Item, ItemCreate

ITEM_TYPE = "qa_check"

# Legal user-initiated transitions. The revalidation trigger
# (passed → pending) is system-initiated and bypasses this matrix.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "passed", "failed", "blocked", "skipped"},
    "in_progress": {"passed", "failed", "blocked"},
    "failed": {"in_progress", "skipped"},
    "blocked": {"in_progress", "skipped"},
    "passed": set(),
    "skipped": set(),
}


def _check_transition(qa_id: str, current: str, target: str) -> None:
    if target not in _LEGAL_TRANSITIONS.get(current, set()):
        raise QAStateTransitionError(qa_id, current, target)


# ── Head resolution ─────────────────────────────────────────────


async def _resolve_head(
    conn: AsyncConnection[Any],
    any_chain_id: str,
    *,
    project_id: str | None = None,
) -> Item:
    """Walk the supersede chain forward and return the head qa_check row.

    Accepts a full UUID or hex prefix (≥8 chars). Multiple seed matches
    in the same supersede chain collapse to one head; matches across
    distinct chains raise :class:`AmbiguousIdError`.
    """
    params: dict[str, Any] = {}
    seed = build_seed_clause(any_chain_id, params)
    if project_id is not None:
        params["pid"] = project_id
        seed = sql.SQL("({seed}) AND project_id = %(pid)s").format(seed=seed)

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
        LIMIT 2
    """).format(seed=seed)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()
    qa_rows = [r for r in rows if r["item_type"] == ITEM_TYPE]
    if not qa_rows:
        raise QACheckNotFoundError(any_chain_id)
    if len(qa_rows) > 1:
        matches = [(str(r["id"]), str(r.get("title") or "")) for r in qa_rows]
        raise AmbiguousIdError(any_chain_id, matches)
    return _row_to_item(qa_rows[0])


# ── Create ──────────────────────────────────────────────────────


async def create_qa(
    conn: AsyncConnection[Any],
    *,
    project_id: str,
    title: str,
    actor_id: str,
    coverage: str,
    areas: list[str] | None = None,
    target_item_ids: list[str] | None = None,
    target_task_ids: list[str] | None = None,
    work_unit_id: str | None = None,
    body: str | None = None,
    context_extra: dict[str, Any] | None = None,
) -> Item:
    """Create a new qa_check in ``pending`` status.

    *coverage* must be one of ``auto_partial`` / ``human_only``.
    """
    context: dict[str, Any] = {
        "status": "pending",
        "coverage": coverage,
    }
    if areas:
        context["areas"] = areas
    if target_item_ids:
        context["target_item_ids"] = target_item_ids
    if target_task_ids:
        context["target_task_ids"] = target_task_ids
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
            context=context,
        ),
    )


# ── Read ────────────────────────────────────────────────────────


async def get_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    project_id: str | None = None,
) -> Item | None:
    """Fetch the head of the chain containing *qa_id*.

    Accepts a full UUID or hex prefix (≥8 chars). Returns ``None`` if
    nothing matches; raises :class:`AmbiguousIdError` if a prefix
    resolves to multiple distinct chains.
    """
    try:
        return await _resolve_head(conn, qa_id, project_id=project_id)
    except QACheckNotFoundError:
        return None


async def _list_heads(
    conn: AsyncConnection[Any],
    extra_conditions: list[sql.Composable],
    params: dict[str, Any],
) -> list[Item]:
    conditions: list[sql.Composable] = [
        sql.SQL("item_type = 'qa_check'"),
        sql.SQL("deleted_at IS NULL"),
        sql.SQL("NOT EXISTS (SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id)"),
        *extra_conditions,
    ]
    where = sql.SQL(" AND ").join(conditions)
    query = sql.SQL("SELECT items.* FROM items WHERE {where} ORDER BY created_at DESC").format(
        where=where
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return [_row_to_item(r) for r in await cur.fetchall()]


async def list_qa(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    status: str | None = None,
    work_unit_id: str | None = None,
) -> list[Item]:
    """List qa_check heads in *project_id*, optionally filtered."""
    extra: list[sql.Composable] = [sql.SQL("project_id = %(pid)s")]
    params: dict[str, Any] = {"pid": project_id}
    if status is not None:
        extra.append(sql.SQL("context->>'status' = %(status)s"))
        params["status"] = status
    if work_unit_id is not None:
        extra.append(sql.SQL("work_unit_id = %(wu)s"))
        params["wu"] = work_unit_id
    return await _list_heads(conn, extra, params)


async def list_pending_for_task(conn: AsyncConnection[Any], task_id: str) -> list[Item]:
    """qa_checks targeting *task_id* that are not yet passed (GIN-hit)."""
    extra: list[sql.Composable] = [
        sql.SQL("context->'target_task_ids' ? %(tid)s"),
        sql.SQL("context->>'status' = 'pending'"),
    ]
    return await _list_heads(conn, extra, {"tid": task_id})


async def list_pending_for_item(conn: AsyncConnection[Any], item_id: str) -> list[Item]:
    """qa_checks targeting *item_id* that are not yet passed (GIN-hit)."""
    extra: list[sql.Composable] = [
        sql.SQL("context->'target_item_ids' ? %(iid)s"),
        sql.SQL("context->>'status' = 'pending'"),
    ]
    return await _list_heads(conn, extra, {"iid": item_id})


async def list_pending_for_wu(conn: AsyncConnection[Any], work_unit_id: str) -> list[Item]:
    """All pending qa_checks attached to *work_unit_id*."""
    extra: list[sql.Composable] = [
        sql.SQL("work_unit_id = %(wu)s"),
        sql.SQL("context->>'status' = 'pending'"),
    ]
    return await _list_heads(conn, extra, {"wu": work_unit_id})


# ── State transitions ───────────────────────────────────────────


async def _supersede_with_context(
    conn: AsyncConnection[Any],
    head: Item,
    new_context: dict[str, Any],
    actor_id: str,
) -> Item:
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


async def start_qa(conn: AsyncConnection[Any], qa_id: str, *, actor_id: str) -> Item:
    head = await _resolve_head(conn, qa_id)
    _check_transition(head.id, head.context.get("status", ""), "in_progress")
    new_context = {**head.context, "status": "in_progress"}
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def pass_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    actor_id: str,
    evidence: str | None = None,
) -> Item:
    head = await _resolve_head(conn, qa_id)
    _check_transition(head.id, head.context.get("status", ""), "passed")
    from datetime import UTC, datetime

    new_context = {**head.context, "status": "passed", "passed_at": datetime.now(UTC).isoformat()}
    if evidence:
        new_context["evidence"] = evidence
    new_context.pop("revalidation_reason", None)
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def fail_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    actor_id: str,
    reason: str,
) -> Item:
    head = await _resolve_head(conn, qa_id)
    _check_transition(head.id, head.context.get("status", ""), "failed")
    new_context = {**head.context, "status": "failed", "fail_reason": reason}
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def block_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    actor_id: str,
    reason: str,
) -> Item:
    head = await _resolve_head(conn, qa_id)
    _check_transition(head.id, head.context.get("status", ""), "blocked")
    new_context = {**head.context, "status": "blocked", "blocked_reason": reason}
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def skip_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    actor_id: str,
) -> Item:
    head = await _resolve_head(conn, qa_id)
    _check_transition(head.id, head.context.get("status", ""), "skipped")
    new_context = {**head.context, "status": "skipped"}
    return await _supersede_with_context(conn, head, new_context, actor_id)


async def assign_qa(
    conn: AsyncConnection[Any],
    qa_id: str,
    *,
    actor_id: str,
    assignee_actor_id: str,
) -> Item:
    """Assign a qa_check to *assignee_actor_id*. ``actor_id`` ≠ assignee
    by design (the actor performing the assignment is rarely the assignee)."""
    head = await _resolve_head(conn, qa_id)
    new_context = {**head.context, "assignee": assignee_actor_id}
    return await _supersede_with_context(conn, head, new_context, actor_id)
