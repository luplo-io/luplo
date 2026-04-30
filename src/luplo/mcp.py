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
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from luplo.config import load_config
from luplo.core.backend.local import LocalBackend
from luplo.core.backend.protocol import Backend
from luplo.core.backend.remote import RemoteBackend
from luplo.core.db import create_pool
from luplo.core.import_pipeline.manifest import SourceFile
from luplo.core.models import Item, ItemCreate

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

_backend: Backend | None = None


class _RemoteAuthMissing(RuntimeError):
    """Raised when a remote-mode backend is requested but no token is on hand.

    The MCP server cannot prompt interactively, so we surface a clear,
    actionable error string in the first tool response rather than crashing
    deep inside an HTTP call with a 401.
    """


_KEYRING_SERVICE = "luplo-cloud"
_KEYRING_SLOT = "access"


def _read_keyring_token() -> str | None:
    """Best-effort read of the access token ``lps login`` stores.

    Returns ``None`` if ``keyring`` isn't installed (it's an optional dep —
    headless installs typically skip it), if the OS has no keyring backend,
    or if no token is stored. The caller falls through to a friendly error.
    """
    try:
        import keyring  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    try:
        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_SLOT)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    except Exception:
        # NoKeyringError, locked keyring, etc — same outcome: no token.
        return None
    return (value or "").strip() or None  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


def _remote_token() -> str:
    """Resolve the bearer for remote mode.

    Priority (high → low):
      1. ``LUPLO_CLOUD_API_KEY`` env var (long-lived ``lupk_…`` API key — the
         path used by servers, CI, and IaC)
      2. OS keyring entry written by ``lps login`` (short-lived OAuth access
         JWT — convenient for desktop sessions)

    Note: keyring access tokens are JWTs with ~15-minute TTL. If the JWT
    expires mid-session, tool calls will start returning 401 and the user
    must re-run ``lps login`` and restart ``lp mcp``. A future cycle can add
    refresh-on-401 inside RemoteBackend; for now, env-based API keys are
    the recommended path for long-running MCP servers.
    """
    token = os.environ.get("LUPLO_CLOUD_API_KEY", "").strip()
    if token:
        return token
    keyring_token = _read_keyring_token()
    if keyring_token:
        return keyring_token
    raise _RemoteAuthMissing(
        'Remote backend selected (.luplo: backend.type = "remote") but '
        "no credential found. Either run `lps login` (desktop) or set "
        "LUPLO_CLOUD_API_KEY=lupk_... (server / CI). "
        "Issue a key at https://app.luplo.io/settings/api-keys."
    )


async def _get_backend() -> Backend:
    """Lazy-initialise the backend on first tool call.

    Selection (priority high→low):
      1. ``.luplo`` ``[backend] type = "remote"`` + ``server_url`` → RemoteBackend
         with bearer from ``LUPLO_CLOUD_API_KEY``.
      2. Otherwise → LocalBackend on ``LUPLO_DB_URL`` (or default).
    """
    global _backend
    if _backend is None:
        cfg = load_config()
        if cfg.backend_type == "remote" and cfg.server_url:
            _backend = RemoteBackend(cfg.server_url, token=_remote_token())  # pyright: ignore[reportAssignmentType]
        else:
            db_url = os.environ.get("LUPLO_DB_URL", "postgresql://localhost/luplo")
            pool = await create_pool(db_url)
            _backend = LocalBackend(pool)
    assert _backend is not None
    return _backend


def _resolve_actor(actor_id: str) -> str:
    """Resolve the actor UUID.

    The literal string ``"claude"`` is treated as a sentinel for "use the
    configured default" — after 0002 migration actors.id is a UUID, so a
    non-UUID fallback must resolve to the local ``.luplo`` actor.id
    before hitting the DB.

    In ``backend.type = "remote"`` mode the SaaS server resolves the
    caller from its bearer token, so an unconfigured actor is *not* an
    error here — we return an empty string and let ``RemoteBackend``
    omit the actor field from outgoing payloads.
    """
    if actor_id and actor_id != "claude":
        return actor_id
    cfg = load_config()
    if cfg.actor_id:
        return cfg.actor_id
    if cfg.backend_type == "remote":
        return ""
    raise ValueError("No actor_id configured. Set LUPLO_ACTOR_ID or run `lp init`.")


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
async def luplo_work_list(project_id: str, status: str = "") -> str:
    """List work units in a project, ordered by created_at DESC.

    Use this to recall recently closed work units (e.g. to re-open a
    follow-up task) or to inspect the backlog of in_progress units. For
    keyword search across in_progress units, prefer ``luplo_work_resume``.

    Args:
        project_id: Project scope.
        status: Optional filter — "in_progress", "done", or "abandoned".
            Empty string returns all statuses.
    """
    b = await _get_backend()
    rows = await b.list_work_units(project_id, status=status or None)
    if not rows:
        return "No work units."
    lines = [f"Found {len(rows)} work unit(s):"]
    for wu in rows:
        systems = f" [{', '.join(wu.system_ids)}]" if wu.system_ids else ""
        lines.append(
            f"- [{wu.id[:8]}] [{wu.status}] {wu.title}{systems} ({wu.created_at:%Y-%m-%d})"
        )
    return "\n".join(lines)


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
    async with b.pool.connection() as conn:  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownVariableType]
        results = await find_work_units(conn, project_id, query)  # pyright: ignore[reportUnknownArgumentType]

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
            lines.append(f"- in_progress: [{in_progress.id[:8]}] {in_progress.title}")
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
            expires_dt = expires_dt.replace(tzinfo=UTC)
    elif item_type == "research":
        cfg = load_config()
        expires_dt = datetime.now(UTC) + timedelta(days=cfg.research_ttl_days)

    item = await b.create_item(
        ItemCreate(
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
        )
    )
    action = "Updated" if supersedes_id else "Created"
    return f"{action} {item.item_type}: {item.title} (id: {item.id})"


@mcp.tool()
async def luplo_item_search(
    query: str,
    project_id: str,
    item_types: list[str] | None = None,
    system_ids: list[str] | None = None,
    limit: int = 10,
    tsquery: str | None = None,
) -> str:
    """Search items using glossary-expanded full-text search.

    Two modes:

    1. **Simple** (``query=``) — small dialect designed for humans:
       plain words AND together, ``"exact phrase"``, ``OR`` (uppercase),
       ``-negation``. Glossary auto-expands required terms (e.g. "vendor"
       also matches "shop", "NPC merchant"). No parentheses, no prefix,
       no ``&|!`` operators — those are passed through as literal chars.
    2. **Raw tsquery** (``tsquery=``) — escape hatch for callers (LLMs,
       advanced users) that want PostgreSQL's full
       `to_tsquery <https://www.postgresql.org/docs/current/textsearch-controls.html>`_
       grammar: ``&`` (AND), ``|`` (OR), ``!`` (NOT), ``:*`` (prefix),
       ``<->`` (phrase distance), parentheses for grouping. Glossary is
       **not** applied — caller is responsible for synonym coverage.
       Bad syntax raises an error.

    Pick one — when ``tsquery`` is set, ``query`` is ignored.

    Examples::

        # Simple
        query="inventory slot OR 인벤토리"
        query="\\"InventoryWindow\\" -deprecated"

        # Raw tsquery
        tsquery="(inventory | 인벤토리) & slot & !deprecated"
        tsquery="hearth:* & ward & decision"

    Args:
        query: Simple-dialect search string. Used unless *tsquery* is set.
        project_id: Project scope.
        item_types: Filter by item types (e.g. ["decision"]).
        system_ids: Filter by systems.
        limit: Maximum results.
        tsquery: Raw PostgreSQL ``to_tsquery`` expression. When set,
            bypasses the simple parser and glossary expansion entirely.
    """
    b = await _get_backend()
    results = await b.search(
        query,
        project_id,
        item_types=item_types,
        system_ids=system_ids,
        limit=limit,
        tsquery=tsquery,
    )

    if not results:
        return "No results found."

    lines = [f"Found {len(results)} result(s):"]
    for r in results:
        systems = f" [{', '.join(r.item.system_ids)}]" if r.item.system_ids else ""
        lines.append(f"- {r.item.title} (id: {r.item.id}){systems}")
        if r.item.body:
            lines.append(f"  {r.item.body[:150]}")
        if r.item.rationale:
            lines.append(f"  Rationale: {r.item.rationale[:150]}")
    lines.append("")
    lines.append("Pass any `id` above to luplo_item_show for full body + rationale.")
    return "\n".join(lines)


@mcp.tool()
async def luplo_item_show(item_id: str, project_id: str) -> str:
    """Return the full body, rationale, and metadata of a single item.

    Use this when a ``luplo_item_search`` preview is truncated and the
    full text is needed to reason about a decision, knowledge entry, or
    document. Accepts a full UUID or ≥8-char hex prefix; prefix lookups
    are scoped to *project_id*. Soft-deleted items return "not found".

    Args:
        item_id: Full UUID or ≥8-char hex prefix of the item.
        project_id: Project scope for prefix disambiguation and safety.

    Returns:
        Markdown text with a title header, a metadata block, and
        untruncated Body / Rationale sections. Empty sections are
        skipped.
    """
    b = await _get_backend()
    item = await b.get_item(item_id, project_id=project_id)
    if item is None:
        return f"Item {item_id!r} not found in project {project_id!r}."

    lines = [f"# {item.title}", ""]
    meta: list[str] = [
        f"- id: {item.id}",
        f"- type: {item.item_type}",
    ]
    if item.system_ids:
        meta.append(f"- systems: {', '.join(item.system_ids)}")
    if item.tags:
        meta.append(f"- tags: {', '.join(item.tags)}")
    if item.work_unit_id:
        meta.append(f"- work_unit_id: {item.work_unit_id}")
    if item.supersedes_id:
        meta.append(f"- supersedes_id: {item.supersedes_id}")
    meta.append(f"- created_at: {item.created_at.isoformat()}")
    meta.append(f"- updated_at: {item.updated_at.isoformat()}")
    lines.extend(meta)

    if item.body:
        lines.extend(["", "## Body", "", item.body])
    if item.rationale:
        lines.extend(["", "## Rationale", "", item.rationale])

    return "\n".join(lines)


@mcp.tool()
async def luplo_check(
    project_id: str,
    rule: str = "",
    severity: str = "warn",
) -> str:
    """Run the deterministic rule pack and return findings as markdown.

    Rules are project-local, SQL+Python only, and never call an LLM.
    The set is fixed per release — there is no plugin runtime.

    Args:
        project_id: Project to check.
        rule: If set, run only this rule (name). Empty means all
            enabled rules.
        severity: Show findings at or above this level — "error",
            "warn" (default), or "info".

    Returns:
        Markdown listing each finding with its severity, rule name,
        item id prefix, and message. Empty state returns a short "no
        findings" line.
    """
    from luplo.core.errors import ValidationError

    severity_order = {"info": 0, "warn": 1, "error": 2}
    if severity not in severity_order:
        return f"Error: severity must be error/warn/info (got {severity!r})."

    b = await _get_backend()
    try:
        findings = await b.run_checks(
            project_id,
            rule_names=[rule] if rule else None,
        )
    except ValidationError as exc:
        return f"Error: {exc.message}"

    threshold = severity_order[severity]
    shown = [f for f in findings if severity_order[f.severity] >= threshold]

    if not shown:
        return f"No findings at severity ≥ {severity}."

    lines = [f"Found {len(shown)} finding(s):"]
    for f in shown:
        target = f" [{f.item_id[:8]}]" if f.item_id else ""
        lines.append(f"- [{f.severity}] {f.rule_name}{target} — {f.message}")
    return "\n".join(lines)


@mcp.tool()
async def luplo_impact(
    item_id: str,
    project_id: str,
    depth: int = 5,
) -> str:
    """Traverse typed edges to find an item's blast radius.

    Walks outgoing ``depends`` / ``blocks`` / ``supersedes`` / ``conflicts``
    edges from the given item up to *depth* hops and returns every reachable
    item, each labelled with the edge type that first reached it at its
    shortest-path depth. Traversal never crosses project boundaries; cycles
    are broken automatically; items appear once.

    Depth is capped at 5 server-side. Requesting deeper is not supported
    and is not a performance limit — it reflects a model-hygiene principle.
    If impact analysis needs more than five hops, the model should be
    decomposed.

    Args:
        item_id: Full UUID or 8+ char hex prefix of the root item.
        project_id: Project scope. Impact is project-local.
        depth: Max traversal depth, 1..5. Default 5.

    Returns:
        Markdown text listing the root and each impacted item with its
        depth and edge type. Item IDs are 8-char prefixes suitable for
        citing back in follow-up tool calls.
    """
    from luplo.core.errors import NotFoundError, ValidationError

    b = await _get_backend()
    try:
        result = await b.impact(item_id, project_id, depth=depth)
    except NotFoundError as exc:
        return f"Error: {exc.message}"
    except ValidationError as exc:
        return f"Error: {exc.message}"

    if not result.nodes:
        return (
            f"[{result.root.id[:8]}] {result.root.title}\n"
            f"No impact edges at depth ≤ {result.depth_requested}."
        )

    lines = [
        f"[{result.root.id[:8]}] {result.root.title}",
        f"{len(result.nodes)} impacted item(s) within depth {result.depth_requested}:",
    ]
    for node in result.nodes:
        lines.append(
            f"- depth={node.depth} via={node.via.link_type} "
            f"parent=[{node.via.parent_id[:8]}] "
            f"[{node.item.id[:8]}] {node.item.title}"
        )
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
        results = await b.search(
            keyword, project_id, system_ids=[system_id] if system_id else None, limit=10
        )
        items = [r.item for r in results]
        lines.append(f"## Items matching '{keyword}'")
    else:
        items = await b.list_items(project_id, system_id=system_id or None, limit=10)
        lines.append("## Recent Items")

    if items:
        for item in items:
            lines.append(f"- [{item.item_type}] {item.title} (id: {item.id})")
            if item.rationale:
                lines.append(f"  Rationale: {item.rationale[:100]}")
        lines.append("")
        lines.append("Pass any `id` above to luplo_item_show for full body + rationale.")
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
async def luplo_task_start(task_id: str, actor_id: str = "claude", project_id: str = "") -> str:
    """Transition a task to 'in_progress'. Fails if another task is in_progress.

    Pass *project_id* (the active project) whenever it is known. It scopes
    prefix resolution so a short ``task_id`` prefix cannot accidentally
    match a task in a different project.
    """
    from luplo.core.errors import TaskAlreadyInProgressError, TaskNotFoundError

    b = await _get_backend()
    try:
        t = await b.start_task(
            task_id,
            actor_id=_resolve_actor(actor_id),
            project_id=project_id or None,
        )
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
    project_id: str = "",
    propose_decision: bool = False,
) -> str:
    """Transition a task to 'done'.

    Pass *project_id* to scope prefix resolution. When
    *propose_decision* is true, the response is followed by a draft
    decision item derived from this task — never inserted. The draft
    is a suggestion for the caller to show the human, who then decides
    whether to save it via ``luplo_item_upsert``.
    """
    b = await _get_backend()
    t = await b.complete_task(
        task_id,
        actor_id=_resolve_actor(actor_id),
        summary=summary or None,
        project_id=project_id or None,
    )
    out = f"Completed task: {t.title} (new id: {t.id})"

    if propose_decision:
        draft = await b.suggest_decision_from_task(t.id, project_id=project_id or None)
        if draft is None:
            out += "\n\nNo decision draft suggested (task has no body or summary)."
        else:
            out += "\n\n-- Suggested decision (NOT saved) --"
            out += f"\ntitle: {draft.title}"
            if draft.body:
                out += f"\nbody: {draft.body}"
            if draft.rationale:
                out += f"\nrationale: {draft.rationale}"
            if draft.tags:
                out += f"\ntags: {', '.join(draft.tags)}"
            out += "\n\nTo save, call luplo_item_upsert with these fields."

    return out


@mcp.tool()
async def luplo_task_edit(
    task_id: str,
    title: str = "",
    body: str = "",
    sort_order: int = -1,
    actor_id: str = "claude",
    project_id: str = "",
) -> str:
    """Edit a task's title / body / sort_order via supersede.

    Status is preserved (call luplo_task_start / luplo_task_done etc. to
    change status). Pass empty strings / sort_order=-1 for fields you do
    not want to change. ``project_id`` scopes prefix resolution.
    """
    b = await _get_backend()
    t = await b.edit_task(
        task_id,
        actor_id=_resolve_actor(actor_id),
        title=title or None,
        body=body or None,
        sort_order=sort_order if sort_order >= 0 else None,
        project_id=project_id or None,
    )
    return f"Edited task: {t.title} (new id: {t.id}, supersedes={t.supersedes_id})"


@mcp.tool()
async def luplo_task_block(
    task_id: str,
    reason: str,
    actor_id: str = "claude",
    project_id: str = "",
) -> str:
    """Transition a task to 'blocked'. Auto-creates a decision item.

    Pass *project_id* to scope prefix resolution.
    """
    b = await _get_backend()
    t = await b.block_task(
        task_id,
        actor_id=_resolve_actor(actor_id),
        reason=reason,
        project_id=project_id or None,
    )
    return (
        f"Blocked task: {t.title} (new id: {t.id}). Auto-created a decision item with the reason."
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
    project_id: str = "",
) -> str:
    """Transition a qa_check to 'passed' with optional evidence.

    Pass *project_id* to scope prefix resolution.
    """
    b = await _get_backend()
    q = await b.pass_qa(
        qa_id,
        actor_id=_resolve_actor(actor_id),
        evidence=evidence or None,
        project_id=project_id or None,
    )
    return f"Passed qa_check: {q.title} (new id: {q.id})"


@mcp.tool()
async def luplo_qa_fail(
    qa_id: str,
    reason: str,
    actor_id: str = "claude",
    project_id: str = "",
) -> str:
    """Transition a qa_check to 'failed'.

    Pass *project_id* to scope prefix resolution.
    """
    b = await _get_backend()
    q = await b.fail_qa(
        qa_id,
        actor_id=_resolve_actor(actor_id),
        reason=reason,
        project_id=project_id or None,
    )
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
    b = await _get_backend()
    since_dt = datetime.fromisoformat(since).replace(tzinfo=UTC) if since else None

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
    saved: list[Item] = []
    for item_data in items:
        item = await b.create_item(item_data)
        saved.append(item)

    return f"Saved {len(saved)} decision(s)."


# ── Import (spec/plan → items) ───────────────────────────────────


@mcp.tool()
async def luplo_import_begin(
    project_id: str,
    sources: list[dict[str, str]],
    dest_lang: str | None = None,
    force: bool = False,
    repo_root: str = "",
    actor_id: str = "claude",
) -> dict[str, Any]:
    """Stage a new import bundle from spec/plan markdown content.

    The agent reads the spec/plan markdown files **before** invoking this
    tool and passes their contents inline via ``sources``. This keeps the
    pipeline filesystem-free on the server, which is what allows it to
    run on the multi-tenant cloud MCP. Local-mode invocations follow the
    same pattern for consistency.

    Returns one of two response shapes:

    - **manifest** (success): the full ImportManifest JSON. The agent must
      now read the manifest, extract candidate items per the protocol
      rules, verify each candidate's status against the repository code
      (using parallel small-model subagents recommended), then call
      ``luplo_import_finalize`` with the assembled results.
    - **refusal** (``status="refused"``): a 3-layer self-documenting
      refusal carrying ``why``, ``override``, and ``agent_hint`` fields.
      The agent MUST surface the refusal to the user and explicitly ask
      before retrying with ``force=true``. Do not silently retry.

    Rules the agent must enforce on extracted items:

    - Chunk meaningfully (decisions/knowledge granularity, not
      per-checkbox).
    - No fenced code blocks in body — replace with a placeholder.
    - Translate to *dest_lang* if set; preserve source language otherwise.
    - Rejected proposals with known rationale → standalone decision items.

    Args:
        project_id: Project owning the bundle.
        sources: Non-empty list of source files. Each entry is a dict
            with three string keys:

            * ``kind``: ``"spec"`` or ``"plan"``.
            * ``path``: caller-supplied identifier (filesystem path or
              other label). Stored verbatim; never opened by the server.
            * ``content``: the file's UTF-8 markdown content.

            At most one ``"spec"`` and one ``"plan"`` may be supplied.
        dest_lang: ISO 639-1 target language. ``None`` preserves source
            language verbatim.
        force: When True, archive any prior import for the same content
            set and stage a fresh bundle. Default False — duplicates
            return a refusal payload.
        repo_root: Repository root path the agent will use during code
            verification. Stored verbatim in the manifest; the server
            never resolves or opens it. Empty string is allowed when
            verification will run elsewhere (e.g. the cloud).
        actor_id: UUID of the actor opening the bundle. The literal
            ``"claude"`` resolves to the configured ``.luplo`` actor in
            local mode; in remote/cloud mode the server resolves the
            actor from the bearer token regardless.

    Returns:
        Either a manifest dict (with ``bundle_id``, ``dest_lang``,
        ``sources``, ``protocol`` keys) or a refusal dict with
        ``status="refused"`` plus ``why`` / ``override`` / ``agent_hint``.
    """
    from luplo.core.import_pipeline.begin import begin_import
    from luplo.core.import_pipeline.sources import make_source_file

    aid = _resolve_actor(actor_id)

    spec: SourceFile | None = None
    plan: SourceFile | None = None
    for s in sources:
        kind = s.get("kind")
        path = s.get("path", "")
        content = s.get("content", "")
        if kind == "spec":
            if spec is not None:
                raise ValueError("at most one source with kind='spec' is allowed")
            spec = make_source_file(path=path, content=content)
        elif kind == "plan":
            if plan is not None:
                raise ValueError("at most one source with kind='plan' is allowed")
            plan = make_source_file(path=path, content=content)
        else:
            raise ValueError(f"unknown source kind: {kind!r}")

    b = await _get_backend()
    result = await begin_import(
        backend=b,
        project_id=project_id,
        actor_id=aid,
        spec=spec,
        plan=plan,
        dest_lang=dest_lang,
        repo_root=repo_root,
        force=force,
    )
    if result.kind == "manifest":
        assert result.manifest is not None
        return result.manifest.model_dump()
    assert result.refusal is not None
    return dict(result.refusal)


@mcp.tool()
async def luplo_import_finalize(
    bundle_id: str,
    items: list[dict[str, Any]],
    project_id: str,
    close_work_unit: bool = False,
    actor_id: str = "claude",
) -> dict[str, Any]:
    """Commit agent-extracted items into the staged import bundle.

    *items* must be a list of objects matching the ``ResultItem`` shape:
    ``{item_type, title, body, status, evidence_paths, [rationale],
    [tags], [system_ids], [source_url]}``.

    Validation aborts the entire commit on protocol violations
    (no fenced code blocks; ``status=done|partial`` requires
    ``evidence_paths``; ``item_type`` ∈ {``decision``, ``knowledge``,
    ``document``}). Defense-in-depth strips fenced code blocks even when
    the agent followed the rule and surfaces them as warnings.

    Args:
        bundle_id: Work-unit id returned by ``luplo_import_begin``.
        items: List of result-item dicts to persist as luplo items.
        project_id: Project owning the bundle. A cross-project guard
            rejects mismatches.
        close_work_unit: When True, transition the bundle's work unit
            to ``done`` after items are written.
        actor_id: UUID of the actor finalising. The literal ``"claude"``
            resolves to the configured ``.luplo`` actor.

    Returns:
        Summary dict with ``status``, ``bundle_id``, ``items_created``,
        and a (possibly empty) list of ``warnings``.
    """
    from luplo.core.import_pipeline.finalize import finalize_import
    from luplo.core.import_pipeline.results import ImportResults

    aid = _resolve_actor(actor_id)
    parsed = ImportResults.model_validate(
        {
            "bundle_id": bundle_id,
            "items": items,
            "close_work_unit": close_work_unit,
        }
    )

    b = await _get_backend()
    return await finalize_import(
        backend=b,
        project_id=project_id,
        actor_id=aid,
        results=parsed,
    )


# ── Entrypoint ───────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
