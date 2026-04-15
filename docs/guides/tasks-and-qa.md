# Tasks and QA checks

luplo models **tasks** and **QA checks** as item types on top of the
substrate (see {doc}`../concepts/data-model`), not as dedicated tables.
The domain logic — status machines, block handling, coverage, target
arrays — lives in typed `context` JSONB fields that are strictly
validated via the `item_types.schema`.

This guide is the working pattern: create a task, progress it, block it,
attach QA to it, and close the loop.

## Task state machine

```
proposed ──► in_progress ──► done
    │             │
    │             ├─► blocked  (writes a decision item explaining why)
    │             │
    └─────────────┴─► skipped  (terminal, human-declined)
```

**Invariant:** at most one task per work unit may be `in_progress` at
any time. The invariant is enforced as a domain check via
`SELECT ... FOR UPDATE`, not as a partial UNIQUE index — see P7 in the
decision log for why the obvious index doesn't compose with the
supersede pattern.

### Add a task

```bash
uv run lp task add "Wire vendor dialogue to inventory" \
    --wu a85a4555 \
    --system vendor \
    --body "Hook dialogue tree events into inventory.open()."
```

`--wu` is required: tasks always belong to a work unit.

### Advance it

```bash
uv run lp task start <task-id>      # proposed → in_progress
uv run lp task done  <task-id>      # in_progress → done
uv run lp task skip  <task-id>      # any → skipped
```

`start` refuses if another task in the same work unit is already
`in_progress`. Finish the first task or skip it before starting the
next.

### List and find

```bash
uv run lp task ls --wu a85a4555
uv run lp task ls --wu a85a4555 --status in_progress
uv run lp task in-progress --wu a85a4555    # the one, if any
```

Order is `sort_order` within the work unit. Reorder with:

```bash
uv run lp task reorder <task-id-1> <task-id-2> <task-id-3>
```

Reorder writes an **in-place** `sort_order` update plus one audit row,
not a supersede. See P10 in the decision log — sort_order is
presentation state and shouldn't bloat the chain.

### Block a task

```bash
uv run lp task blocked <task-id> \
    --reason "Waiting on currency formatting lib decision."
```

`blocked` does three things in one transaction:

1. Transitions the task to `blocked` status and stores `blocked_reason`.
2. **Automatically creates a `decision` item** with:
   - `title` — `Task blocked: <task title>`
   - `body` — the reason you passed
   - `work_unit_id` — inherited from the task
   - `system_ids` — inherited from the task
3. Writes an `audit_log` row (`task.blocked`).

The auto-generated decision is how a blocked task surfaces in search:
reasons stored only in task fields would not be found by
`lp items search`. Promoting to an item puts the block into the
decision memory.

## QA checks

A **QA check** (`item_type='qa_check'`) is a bounded verification task
— manual or automated — against a target task or item. Where tasks
are "do this", QA checks are "verify this was done right".

### Coverage and area

QA checks carry two classification fields in their context:

- **`coverage`** — how it can be verified.
  - `auto_partial` — at least one part is automated; a human must still
    verify edges.
  - `human_only` — cannot be automated meaningfully. This is the
    conservative default for unclassified checks.
- **`area`** — what aspect is being verified, any subset of:
  `vfx`, `sfx`, `ux`, `edge_case`, `perf`, `a11y`, `sec`.

### Add a QA check

```bash
uv run lp qa add "Vendor shop UI responsive at 480px" \
    --coverage human_only \
    --area ux,a11y \
    --task <task-id-1> --task <task-id-2> \
    --wu a85a4555 \
    --body "Open vendor → dialogue → sales tab. Verify layout, \
            focus order, and keyboard navigation."
```

Target many tasks or items via repeated `--task` / `--item` — the
arrays land in `context.target_task_ids` / `context.target_item_ids`
with GIN indexes on both so lookup in either direction is fast.

### Drive it to a terminal state

```bash
uv run lp qa start  <qa-id>    # pending → in_progress
uv run lp qa pass   <qa-id>    # in_progress → passed
uv run lp qa fail   <qa-id>    # in_progress → failed
uv run lp qa block  <qa-id>    # in_progress → blocked
uv run lp qa assign <qa-id> --to <actor-uuid>
```

### List QA by target

```bash
uv run lp qa ls --status pending
uv run lp qa ls --task <task-id>         # pending QA for a task
uv run lp qa ls --item <item-id>         # pending QA for an item
uv run lp qa ls --wu   <work-unit-id>
```

### Revalidation

When an item that a QA check targets is superseded by a new edit, the
QA check is flagged for re-verification. This is one of the two
documented **in-place updates that skip supersede** (the other is task
reorder): the re-verification trigger is a system-initiated "please
look again", not a human decision, and re-supersedeing every affected
check would create write amplification and chain bloat. See P9 for the
full reasoning.

## Closing a work unit with open tasks

```bash
uv run lp work close <work-id>
# error: 1 task still in_progress — use --force or finish the task.

uv run lp work close <work-id> --force    # closes anyway, audit records the override
```

## Deferred (not in v0.5.x)

- **Automatic task ↔ item linkage on `task done`.** Proposed as v0.6 —
  an LLM pass over the work-unit diff to suggest new decision items.
  Until then, add follow-up items manually.
- **Supersede of tasks via natural-language edit.** You can supersede a
  task with `lp items ... --supersedes`, but there is no dedicated
  `lp task edit` surface yet.

## Related

- {doc}`work-units` — the container tasks and QA check into.
- {doc}`../concepts/data-model` — why tasks and QA are item types.
- {doc}`../reference/cli` — full `lp task` / `lp qa` surface.
- {doc}`../reference/mcp-tools` — `luplo_task_*` and `luplo_qa_*` tools.
