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
  "project_id": "hearthward",
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
  "query": "vendor budget",
  "project_id": "hearthward",
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
  "project_id": "hearthward",
  "item_id": "<uuid>",
  "since": "2026-04-10T00:00:00Z",
  "semantic_impacts": ["numeric_change", "rule_addition"],
  "limit": 20
}
```

See {doc}`semantic-impact` for the seven categories.

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

Transitions `in_progress` → `done`.

### `luplo_task_block`

`in_progress` → `blocked`. Automatically creates a `decision` item
documenting the block reason (see `block_task` semantics in
{doc}`../guides/tasks-and-qa`).

## QA checks

### `luplo_qa_add`

Create a pending QA check. `coverage` defaults to `human_only`.
Multi-target via `target_task_ids` / `target_item_ids` arrays.

### `luplo_qa_list_pending`

```json
{
  "project_id": "hearthward",
  "task_id":    "",
  "item_id":    "",
  "work_unit_id": ""
}
```

Pass one of the filters (task / item / work unit) to scope the list.

### `luplo_qa_pass` / `luplo_qa_fail`

Drive a QA check to `passed` / `failed` terminal states.

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
