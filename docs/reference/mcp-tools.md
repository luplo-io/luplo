# MCP tool reference

The luplo MCP server exposes a **small, deliberate** tool surface — an
LLM gets confused with dozens of similar tools, so rarely-used
operations stay CLI-only. Everything listed here is callable from any
MCP-compatible client (see {doc}`../guides/mcp-client`).

## Conventions

- **`project_id`** is required almost everywhere. luplo is per-project;
  there is no implicit current project.
- **`actor_id`** is derived from the server's auth context — clients do
  not pass it.
- All write tools fire only when the caller explicitly invokes them
  (no auto-extraction — see {doc}`../concepts/philosophy`).

## Context

### `luplo_brief`

Active work units + recent items. Useful at the start of a session when
the human asks for context.

```json
{
  "project_id": "myapp",
  "system_id": "",
  "keyword": ""
}
```

Returns a markdown blob grouped under `## Active Work Units` and
`## Recent Items`.

## Items

### `luplo_item_search`

Glossary-expanded tsquery search.

```json
{
  "query": "auth rate limit",
  "project_id": "myapp",
  "item_types": ["decision"],
  "system_ids": ["<uuid>"],
  "limit": 10
}
```

`item_types` and `system_ids` are optional filters.

### `luplo_item_upsert`

Create or supersede an item. The decision-memory entry point for
explicit writes.

### `luplo_save_decisions`

Batch write of decisions extracted from a conversation **only when the
user explicitly asks**. Idiomatic phrasings: "save these decisions",
"기록해줘". The tool validates shape before writing and echoes back
the created ids.

### `luplo_page_sync`

Materialise a structured page (decisions + glossary review queue) for a
single top-of-mind view. Not a replacement for `luplo_brief` — this is
heavier and targeted.

### `luplo_history_query`

Query the `items_history` table for semantic changes.

```json
{
  "project_id": "myapp",
  "item_id": "<uuid>",
  "since": "2026-04-10T00:00:00Z",
  "semantic_impacts": ["numeric_change", "rule_addition"],
  "limit": 20
}
```

See {doc}`semantic-impact` for the seven categories.

## Captures

Captures are a raw text intake surface outside the curated `items`
graph. Capture tools are deterministic and BYOLLM: caller LLMs may
reason before calling them, but luplo core only stores the supplied
text, annotations, state changes, redactions, and explicit promotions.
It does not transcribe, summarize, classify, infer sensitivity, or
choose what becomes an item.

Capture search/list results are separate from item search. A capture
appears in `luplo_item_search` only after an explicit
`luplo_capture_promote` call creates a normal item.

### `luplo_capture_add`

Save raw text into the capture backlog.

```json
{
  "text": "raw thought from today",
  "actor_id": "claude"
}
```

Returns a short acknowledgement with the capture id prefix and state.

### `luplo_capture_list`

List recent captures, newest first.

```json
{
  "review_state": "",
  "limit": 100,
  "include_discarded": false,
  "include_redacted": false
}
```

Discarded and redacted captures are hidden unless requested. Redacted
captures stay masked.

### `luplo_capture_search`

Search capture text and optional summary.

```json
{
  "query": "people issue",
  "review_state": "",
  "limit": 50,
  "include_discarded": false,
  "include_redacted": false
}
```

Pass an empty query for filter-only review flows.

### `luplo_capture_annotate`

Store caller-supplied annotation hints.

```json
{
  "capture_id": "<capture-id>",
  "summary": "caller supplied summary",
  "sensitivity_hint": "possible",
  "signals": {"tags": ["people_issue"], "confidence": 0.64}
}
```

`signals` must be a JSON object. Core stores it as a hint, not truth.

### `luplo_capture_set_state`

Move a capture between review states.

```json
{
  "capture_id": "<capture-id>",
  "review_state": "review",
  "actor_id": "claude"
}
```

Use `luplo_capture_redact` for the `redacted` state.

### `luplo_capture_discard`

Mark a capture `discarded` so default list/search hides it.

### `luplo_capture_redact`

Replace capture text/summary with `[redacted]`, clear signals, stamp
redaction metadata, and remove original content from capture search.

### `luplo_capture_promote`

Explicitly promote a capture into a curated item.

```json
{
  "capture_id": "<capture-id>",
  "project_id": "myapp",
  "item_type": "knowledge",
  "title": "Useful pattern",
  "body": "",
  "actor_id": "claude"
}
```

`project_id` is required because the target item is project-scoped. If
`body` is empty, the tool uses the capture text. Promotion creates a
normal item through the existing item creation path and records a
`capture_promotions` bridge row.

## Audit (blast radius)

### `luplo_impact`

Traverse outgoing typed edges from *item_id* and return the list of
items reachable within *depth* hops (1–5, capped server-side). Every
hop carries the edge type that first reached the item at its
shortest-path depth; cycles are broken automatically; each item
appears once. Scope is always project-local.

```json
{
  "item_id": "<uuid-or-prefix>",
  "project_id": "myapp",
  "depth": 5
}
```

Returns markdown a model can cite. The same payload (structured JSON)
is available via `GET /items/{item_id}/impact`. See
{doc}`../concepts/philosophy` for why depth stops at five.

## Work units

### `luplo_work_open`

Opens a new work unit and returns its id.

### `luplo_work_resume`

Find in-progress work units by title keyword. The response has a
stable top-level shape so LLM callers can parse it reliably
(see decision `58f5a473`):

```text
{
  "work_units": [ ... ],
  "tasks":      [ ... ],
  "qa_checks":  [ ... ]
}
```

Field shapes inside each array are implementation detail; top-level
keys are the contract.

### `luplo_work_close`

Closes a work unit. Refuses if an `in_progress` task remains unless
`force=true`.

## Tasks

### `luplo_task_add`

Create a task in `proposed`. Requires `work_unit_id`.

### `luplo_task_list`

```json
{ "work_unit_id": "<uuid-or-prefix>", "status": "" }
```

Returns the chain-head tasks ordered by `sort_order`. Only chain heads
— earlier supersede rows are not surfaced.

### `luplo_task_start`

Transitions `proposed` → `in_progress`. Enforces one per work unit via
`SELECT ... FOR UPDATE`.

### `luplo_task_done`

Transitions `in_progress` → `done`. Optional `summary` attaches an
outcome string. When `propose_decision=true`, the response appends a
draft `decision` item derived from the task (never inserted — the
human decides whether to save it via `luplo_item_upsert`). Returns
`None` for the draft when the task has neither body nor summary.

### `luplo_task_block`

`in_progress` → `blocked`. Automatically creates a `decision` item
documenting the block reason (see `block_task` semantics in
{doc}`../guides/tasks-and-qa`).

### `luplo_task_edit`

Edit a task's `title` / `body` / `sort_order` by creating a supersede
row. Status is preserved — a `done` task can still get a typo fixed.
Passing no editable fields is a no-op that returns the current head.

## QA checks

### `luplo_qa_add`

Create a pending QA check. `coverage` defaults to `human_only`.
Multi-target via `target_task_ids` / `target_item_ids` arrays.

### `luplo_qa_list_pending`

```json
{
  "project_id": "myapp",
  "task_id":    "",
  "item_id":    "",
  "work_unit_id": ""
}
```

Pass one of the filters (task / item / work unit) to scope the list.

### `luplo_qa_pass` / `luplo_qa_fail`

Drive a QA check to `passed` / `failed` terminal states.

## Rule pack

### `luplo_check`

Run the deterministic rule pack over *project_id* and return findings
as markdown. Rules are SQL + Python only; no LLM, no external calls.
The set is fixed per release — see {doc}`checks` for each rule and
the `.luplo [checks] disabled_rules` override.

```json
{
  "project_id": "myapp",
  "rule": "",
  "severity": "warn"
}
```

- Empty `rule` runs every enabled rule; setting it restricts to one.
- `severity` is the display threshold (`error` / `warn` / `info`).
  It does not change the set of findings collected, only which ones
  appear in the response.
- The HTTP equivalent is `GET /checks?project_id=&rule=`.

## Philosophy-aligned behaviours

- **No auto-brief.** MCP clients do not call `luplo_brief` unless the
  human asks for context.
- **No auto-extract.** `luplo_save_decisions` fires only on explicit
  request.
- **Honest empty results.** Tools return empty lists when retrieval
  finds nothing — they do not synthesize.

See {doc}`../concepts/philosophy` for the full reasoning.

## Related

- {doc}`../guides/mcp-client` — how to wire this server to a client.
- {doc}`cli` — the human-facing counterpart of every tool here.
