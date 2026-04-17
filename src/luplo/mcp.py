"""luplo MCP server — stdio interface for Claude Desktop/Code.

Run with::

    uv run python -m luplo.mcp

Or configure in Claude Desktop's ``claude_desktop_config.json``::

    {
      "mcpServers": {
        "luplo": {
          "command": "uv",
          "args": ["run", "python", "-m", "luplo.mcp"],
          "env": {"LUPLO_DB_URL": "postgresql://localhost/luplo"}
        }
      }
    }
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from luplo.config import load_config
from luplo.core.backend.local import LocalBackend
from luplo.core.db import close_pool, create_pool
from luplo.core.models import ItemCreate

mcp = FastMCP(
    "luplo",
    instructions="""
luplo is a persistent store for engineering decisions, knowledge, policies,
documents, tasks, and QA checks across coding sessions. Use it to recall prior
context that would otherwise be lost between sessions.

# When to use luplo

Call SEARCH tools when:
- The user references prior work: "what did we decide about X", "the auth thing
  we discussed", "our approach to Y", "didn't we already...", "last time"
- The user starts designing or implementing something non-trivial — search for
  related prior decisions, policies, and knowledge BEFORE writing code or
  proposing a design. This is the most important trigger.
- The user mentions a system, component, or domain by name — check if luplo
  has knowledge entries for it
- The user asks "why is X like this" about code or architecture

Call WRITE tools when, AND ONLY WHEN, the user explicitly asks to record
something:
- "remember that...", "save this decision", "log that we decided...",
  "add a note that...", "기록해줘", "저장해줘"
- Never auto-extract decisions from conversation. Never write without an
  explicit instruction. If you think something is worth saving but the user
  didn't ask, suggest it in plain text — do not call a write tool.

# When NOT to use luplo

- General programming questions answerable from your own knowledge
- Questions about public libraries, language syntax, well-known patterns
- Simple code edits where no prior project context is needed
- Anything where you're not sure the user has used luplo before — luplo is
  per-project; an empty store will return nothing useful

# Tool routing

- Looking for a specific past decision or its rationale → search items with
  type=decision
- Looking for how a system works, conventions, gotchas → search items with
  type=knowledge
- Looking for organizational rules, must-do/must-not → search items with
  type=policy
- Looking for spec documents, RFCs → search items with type=document
- Looking for cached external web references (URLs) → search items with
  type=research. Research items carry source_url and an expires_at TTL;
  a stale/expired hit is still a useful pointer but flag it.
- Recording new information → use the appropriate create tool with the matching
  item_type. Always pass the user's exact words in the rationale/content field;
  do not paraphrase. When saving research, source_url is required (a research
  item without a URL is a silent error, rejected by the backend).

# How to present results

- When you use luplo data in your response, briefly note the source:
  "Based on a decision logged in luplo (item #123)..." so the user can verify.
- If a search returns nothing, say so explicitly. Do not fabricate prior
  decisions.
- If multiple items conflict (e.g., a newer decision supersedes an older one),
  surface the conflict to the user rather than picking silently.

# Editing semantics

- Human-authored items (decisions, knowledge, policies): use SUPERSEDE, never
  in-place edit. The history matters.
- System-derived state (task status, qa results): in-place update is fine.
""",
)

# ── Backend lifecycle ────────────────────────────────────────────

_backend: LocalBackend | None = None


async def _get_backend() -> LocalBackend:
    """Lazy-initialise the backend on first tool call."""
    global _backend  # noqa: PLW0603
    if _backend is None:
        db_url = os.environ.get("LUPLO_DB_URL", "postgresql://localhost/luplo")
        pool = await create_pool(db_url)
        _backend = LocalBackend(pool)
    return _backend


def _resolve_actor(actor_id: str) -> str:
    """Resolve the actor UUID.

    The literal string ``"claude"`` is treated as a sentinel for "use the
    configured default" — after 0002 migration actors.id is a UUID, so a
    non-UUID fallback must resolve to the local ``.luplo`` actor.id
    before hitting the DB.
    """
    if actor_id and actor_id != "claude":
        return actor_id
    cfg = load_config()
    if cfg.actor_id:
        return cfg.actor_id
    raise ValueError(
        "No actor_id configured. Set LUPLO_ACTOR_ID or run `lp init`."
    )


# ── Work Units ───────────────────────────────────────────────────


@mcp.tool()
async def luplo_work_open(
    title: str,
    project_id: str,
    description: str = "",
    system_ids: list[str] | None = None,
    actor_id: str = "claude",
) -> str:
    """Open a new work unit to group related decisions.

    Args:
        title: What this work unit is about (e.g. "Vendor system design").
        project_id: Project to scope this work unit to.
        description: Optional longer description.
        system_ids: Systems this work touches.
        actor_id: Who is opening this (defaults to "claude").
    """
    b = await _get_backend()
    wu = await b.open_work_unit(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title=title,
        description=description or None,
        system_ids=system_ids,
        created_by=_resolve_actor(actor_id),
    )
    return f"Opened work unit: {wu.title} (id: {wu.id})"


@mcp.tool()
async def luplo_work_resume(query: str, project_id: str) -> str:
    """Find in-progress work units by title keyword + their open tasks/QA.

    Returns a markdown brief per matching work unit including the current
    in_progress task, pending tasks (sort_order ASC), and pending qa_checks.

    Args:
        query: Keyword to search in work unit titles.
        project_id: Project scope.
    """
    from luplo.core.work_units import find_work_units

    b = await _get_backend()
    async with b.pool.connection() as conn:
        results = await find_work_units(conn, project_id, query)

    if not results:
        return "No matching work units in progress."

    lines: list[str] = []
    for wu in results:
        systems = f" [{', '.join(wu.system_ids)}]" if wu.system_ids else ""
        lines.append(f"## {wu.title}{systems}")
        lines.append(f"id: {wu.id}")

        # Tasks
        in_progress = await b.get_in_progress_task(wu.id)
        proposed = await b.list_tasks(wu.id, status="proposed")
        if in_progress is not None:
            lines.append(
                f"- in_progress: [{in_progress.id[:8]}] {in_progress.title}"
            )
        if proposed:
            lines.append("- pending tasks:")
            for t in proposed:
                order = t.context.get("sort_order", "?")
                lines.append(f"    - (#{order}) [{t.id[:8]}] {t.title}")
        if in_progress is None and not proposed:
            lines.append("- tasks: (none)")

        # QA
        pending_qa = await b.list_pending_qa_for_wu(wu.id)
        if pending_qa:
            lines.append("- pending qa:")
            for q in pending_qa:
                areas = ",".join(q.context.get("areas") or []) or "—"
                lines.append(f"    - [{q.id[:8]}] {q.title} ({areas})")
        lines.append("")
    return "\n".join(lines).rstrip()


@mcp.tool()
async def luplo_work_close(
    work_unit_id: str,
    actor_id: str = "claude",
) -> str:
    """Close a work unit.

    Args:
        work_unit_id: ID of the work unit to close.
        actor_id: Who is closing this.
    """
    b = await _get_backend()
    result = await b.close_work_unit(work_unit_id, actor_id=_resolve_actor(actor_id))
    if result:
        return f"Closed: {result.title} -> {result.status}"
    return "Work unit not found or already closed."


# ── Items ────────────────────────────────────────────────────────


@mcp.tool()
async def luplo_item_upsert(
    title: str,
    project_id: str,
    item_type: str = "decision",
    body: str = "",
    rationale: str = "",
    system_ids: list[str] | None = None,
    tags: list[str] | None = None,
    work_unit_id: str = "",
    supersedes_id: str = "",
    source_url: str = "",
    expires_at: str = "",
    actor_id: str = "claude",
) -> str:
    """Create or update (supersede) an item.

    To edit an existing item, pass its ID as supersedes_id — a new
    version is created and the old one is preserved.

    Args:
        title: Item title.
        project_id: Project scope.
        item_type: One of decision, knowledge, policy, document, research.
        body: Item body text.
        rationale: Why this decision was made.
        system_ids: Systems this item relates to.
        tags: Free-form tags.
        work_unit_id: Link to an active work unit.
        supersedes_id: ID of item this supersedes (for edits).
        source_url: Required when item_type='research' (the cached URL).
            Optional for other types.
        expires_at: ISO-8601 timestamp for cache expiry. When omitted and
            item_type='research', defaults to now + research_ttl_days from
            config (90 days default).
        actor_id: Who created this.
    """
    b = await _get_backend()

    expires_dt: datetime | None = None
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    elif item_type == "research":
        cfg = load_config()
        expires_dt = datetime.now(timezone.utc) + timedelta(
            days=cfg.research_ttl_days
        )

    item = await b.create_item(ItemCreate(
        project_id=project_id,
        actor_id=_resolve_actor(actor_id),
        item_type=item_type,
        title=title,
        body=body or None,
        rationale=rationale or None,
        system_ids=system_ids or [],
        tags=tags or [],
        work_unit_id=work_unit_id or None,
        supersedes_id=supersedes_id or None,
        source_url=source_url or None,
        expires_at=expires_dt,
    ))
    action = "Updated" if supersedes_id else "Created"
    return f"{action} {item.item_type}: {item.title} (id: {item.id})"


@mcp.tool()
async def luplo_item_search(
    query: str,
    project_id: str,
    item_types: list[str] | None = None,
    system_ids: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search items using glossary-expanded full-text search.

    The query is automatically expanded using the project's glossary
    (e.g. "vendor" may also match "shop", "NPC merchant").

    Args:
        query: Search query string.
        project_id: Project scope.
        item_types: Filter by item types (e.g. ["decision"]).
        system_ids: Filter by systems.
        limit: Maximum results.
    """
    b = await _get_backend()
    results = await b.search(
        query, project_id,
        item_types=item_types, system_ids=system_ids, limit=limit,
    )

    if not results:
        return "No results found."

    lines = [f"Found {len(results)} result(s):"]
    for r in results:
        systems = f" [{', '.join(r.item.system_ids)}]" if r.item.system_ids else ""
        lines.append(f"- [{r.item.id[:8]}] {r.item.title}{systems}")
        if r.item.body:
            lines.append(f"  {r.item.body[:150]}")
        if r.item.rationale:
            lines.append(f"  Rationale: {r.item.rationale[:150]}")
    return "\n".join(lines)


# ── Brief ────────────────────────────────────────────────────────


@mcp.tool()
async def luplo_brief(
    project_id: str,
    system_id: str = "",
    keyword: str = "",
) -> str:
    """Get a project context brief — active work units + recent decisions.

    Use this at the start of a session to load context.

    Args:
        project_id: Project scope.
        system_id: Optional system filter.
        keyword: Optional keyword filter for items.
    """
    b = await _get_backend()

    lines: list[str] = []

    # Active work units
    active = await b.list_work_units(project_id, status="in_progress")
    if active:
        lines.append("## Active Work Units")
        for wu in active:
            systems = f" [{', '.join(wu.system_ids)}]" if wu.system_ids else ""
            lines.append(f"- {wu.title}{systems} (id: {wu.id})")
    else:
        lines.append("No active work units.")

    lines.append("")

    # Recent items
    if keyword:
        results = await b.search(keyword, project_id, system_ids=[system_id] if system_id else None, limit=10)
        items = [r.item for r in results]
        lines.append(f"## Items matching '{keyword}'")
    else:
        items = await b.list_items(project_id, system_id=system_id or None, limit=10)
        lines.append("## Recent Items")

    if items:
        for item in items:
            lines.append(f"- [{item.item_type}] {item.title}")
            if item.rationale:
                lines.append(f"  Rationale: {item.rationale[:100]}")
    else:
        lines.append("No items yet.")

    return "\n".join(lines)


# ── Tasks ────────────────────────────────────────────────────────


@mcp.tool()
async def luplo_task_add(
    title: str,
    project_id: str,
    work_unit_id: str,
    body: str = "",
    system_ids: list[str] | None = None,
    sort_order: int | None = None,
    actor_id: str = "claude",
) -> str:
    """Create a new task in 'proposed' status (item_type='task')."""
    b = await _get_backend()
    t = await b.create_task(
        project_id=project_id,
        work_unit_id=work_unit_id,
        title=title,
        actor_id=_resolve_actor(actor_id),
        body=body or None,
        systems=system_ids,
        sort_order=sort_order,
    )
    return f"Created task: {t.title} (id: {t.id}, status: proposed)"


@mcp.tool()
async def luplo_task_list(
    work_unit_id: str,
    status: str = "",
) -> str:
    """List tasks for a work unit (chain heads, ordered by sort_order)."""
    b = await _get_backend()
    rows = await b.list_tasks(work_unit_id, status=status or None)
    if not rows:
        return "No tasks."
    lines = [f"Found {len(rows)} task(s):"]
    for r in rows:
        st = r.context.get("status", "?")
        order = r.context.get("sort_order", "?")
        lines.append(f"- [{r.id[:8]}] (#{order}) [{st}] {r.title}")
    return "\n".join(lines)


@mcp.tool()
async def luplo_task_start(task_id: str, actor_id: str = "claude") -> str:
    """Transition a task to 'in_progress'. Fails if another task is in_progress."""
    from luplo.core.errors import TaskAlreadyInProgressError, TaskNotFoundError

    b = await _get_backend()
    try:
        t = await b.start_task(task_id, actor_id=_resolve_actor(actor_id))
    except TaskAlreadyInProgressError as e:
        return f"Error: {e.message}"
    except TaskNotFoundError as e:
        return f"Error: {e.message}"
    return f"Started task: {t.title} (new id: {t.id})"


@mcp.tool()
async def luplo_task_done(
    task_id: str,
    summary: str = "",
    actor_id: str = "claude",
) -> str:
    """Transition a task to 'done'."""
    b = await _get_backend()
    t = await b.complete_task(
        task_id, actor_id=_resolve_actor(actor_id), summary=summary or None,
    )
    return f"Completed task: {t.title} (new id: {t.id})"


@mcp.tool()
async def luplo_task_block(
    task_id: str,
    reason: str,
    actor_id: str = "claude",
) -> str:
    """Transition a task to 'blocked'. Auto-creates a decision item."""
    b = await _get_backend()
    t = await b.block_task(
        task_id, actor_id=_resolve_actor(actor_id), reason=reason,
    )
    return (
        f"Blocked task: {t.title} (new id: {t.id}). "
        "Auto-created a decision item with the reason."
    )


# ── QA Checks ────────────────────────────────────────────────────


@mcp.tool()
async def luplo_qa_add(
    title: str,
    project_id: str,
    coverage: str,
    areas: list[str] | None = None,
    target_task_ids: list[str] | None = None,
    target_item_ids: list[str] | None = None,
    work_unit_id: str = "",
    actor_id: str = "claude",
) -> str:
    """Create a qa_check in 'pending' status. coverage = auto_partial|human_only."""
    b = await _get_backend()
    q = await b.create_qa(
        project_id=project_id,
        title=title,
        actor_id=_resolve_actor(actor_id),
        coverage=coverage,
        areas=areas,
        target_task_ids=target_task_ids,
        target_item_ids=target_item_ids,
        work_unit_id=work_unit_id or None,
    )
    return f"Created qa_check: {q.title} (id: {q.id}, status: pending)"


@mcp.tool()
async def luplo_qa_pass(
    qa_id: str,
    evidence: str = "",
    actor_id: str = "claude",
) -> str:
    """Transition a qa_check to 'passed' with optional evidence."""
    b = await _get_backend()
    q = await b.pass_qa(
        qa_id, actor_id=_resolve_actor(actor_id), evidence=evidence or None,
    )
    return f"Passed qa_check: {q.title} (new id: {q.id})"


@mcp.tool()
async def luplo_qa_fail(
    qa_id: str,
    reason: str,
    actor_id: str = "claude",
) -> str:
    """Transition a qa_check to 'failed'."""
    b = await _get_backend()
    q = await b.fail_qa(qa_id, actor_id=_resolve_actor(actor_id), reason=reason)
    return f"Failed qa_check: {q.title} (new id: {q.id}, reason: {reason})"


@mcp.tool()
async def luplo_qa_list_pending(
    project_id: str,
    task_id: str = "",
    item_id: str = "",
    work_unit_id: str = "",
) -> str:
    """List pending qa_checks. Filter by task / item / work_unit (one of)."""
    b = await _get_backend()
    if task_id:
        rows = await b.list_pending_qa_for_task(task_id)
    elif item_id:
        rows = await b.list_pending_qa_for_item(item_id)
    elif work_unit_id:
        rows = await b.list_pending_qa_for_wu(work_unit_id)
    else:
        rows = await b.list_qa(project_id, status="pending")
    if not rows:
        return "No pending qa_checks."
    lines = [f"Found {len(rows)} pending qa_check(s):"]
    for r in rows:
        areas = ",".join(r.context.get("areas") or []) or "—"
        lines.append(f"- [{r.id[:8]}] {r.title} ({areas})")
    return "\n".join(lines)


# ── Sync ─────────────────────────────────────────────────────────


@mcp.tool()
async def luplo_page_sync(
    source_type: str,
    source_page_id: str,
    full_content: str,
    project_id: str,
    source_event_id: str = "",
) -> str:
    """Queue an external page for sync (debounced).

    Used by Notion/Confluence custom agents to push page updates.
    The sync job is debounced — rapid consecutive calls for the same
    page are merged into one.

    Args:
        source_type: Origin system (e.g. "notion", "confluence").
        source_page_id: External page identifier.
        full_content: Full page content (markdown).
        project_id: Project scope.
        source_event_id: Optional external event ID for idempotency.
    """
    b = await _get_backend()
    job = await b.enqueue_sync(
        source_type=source_type,
        source_page_id=source_page_id,
        payload=full_content,
        source_event_id=source_event_id or None,
    )
    return f"Sync job queued (id: {job.id}, scheduled: {job.scheduled_at})"


@mcp.tool()
async def luplo_history_query(
    project_id: str,
    item_id: str = "",
    since: str = "",
    semantic_impacts: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Query change history for items.

    Args:
        project_id: Project scope.
        item_id: Optional specific item to query.
        since: Optional ISO timestamp to filter from.
        semantic_impacts: Filter by impact types (e.g. ["numeric_change", "rule_addition"]).
        limit: Maximum entries.
    """
    from datetime import datetime, timezone

    b = await _get_backend()
    since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else None

    entries = await b.query_history(
        project_id=project_id,
        item_id=item_id or None,
        since=since_dt,
        semantic_impacts=semantic_impacts,
        limit=limit,
    )

    if not entries:
        return "No history entries found."

    lines = [f"Found {len(entries)} change(s):"]
    for e in entries:
        impact = f" [{e.semantic_impact}]" if e.semantic_impact else ""
        summary = e.diff_summary or "(no summary)"
        lines.append(f"- {e.changed_at:%Y-%m-%d %H:%M} {summary}{impact}")
    return "\n".join(lines)


# ── Save Decisions (stub) ────────────────────────────────────────


@mcp.tool()
async def luplo_save_decisions(
    transcript: str,
    project_id: str,
    work_unit_id: str = "",
    actor_id: str = "claude",
) -> str:
    """Extract and save decisions from a conversation transcript.

    v0.5: Returns a stub response. LLM extraction integration is
    planned for post-v0.5.

    Args:
        transcript: Conversation text to extract decisions from.
        project_id: Project scope.
        work_unit_id: Optional work unit to attach extracted items to.
        actor_id: Who authored the transcript.
    """
    from luplo.core.extract import extract_decisions

    items = await extract_decisions(
        transcript,
        project_id=project_id,
        actor_id=_resolve_actor(actor_id),
        work_unit_id=work_unit_id or None,
    )

    if not items:
        return (
            "v0.5: Decision extraction is not yet implemented. "
            "Use luplo_item_upsert to save decisions manually."
        )

    # Post-v0.5: batch create items and return summary
    b = await _get_backend()
    saved = []
    for item_data in items:
        item = await b.create_item(item_data)
        saved.append(item)

    return f"Saved {len(saved)} decision(s)."


# ── Entrypoint ───────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
