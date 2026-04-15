# Work units

A **work unit** is a user-facing grouping of related items that belongs
to a single intent — "Vendor system redesign", "Auth rewrite", "v0.5.1
handoff" — and may span many sessions. Work units replaced an earlier
`sessions` concept: sessions conflated a client process lifetime with a
human intent lifetime, and that was the wrong frame for decision memory.

This guide walks through the three states (`open`, `in_progress`,
`closed`) and the A→B handoff pattern.

## Life cycle

```
          lp work open
                │
                ▼
         in_progress ────────── items, tasks, qa attach here ──────┐
                │                                                   │
   lp work close                                                    │
   (or --force if tasks remain)                                     │
                │                                                   │
                ▼                                                   │
           done / abandoned                                         │
                                                                    │
   lp work resume "vendor"  ◄──────────────────────────────────────┘
```

## Open a work unit

```bash
uv run lp work open "Vendor system redesign" \
    --desc "Scope: NPC merchants, static inventories, no player economy."
```

Output:

```text
work_unit_id: a85a4555-3046-4689-b90e-176ba7c1e981
status:       in_progress
created_by:   you@example.com
```

Attach items to the work unit by including `--wu <id-or-prefix>` when
creating them:

```bash
uv run lp items add "Use NPC merchants over player shops" \
    --type decision --wu a85a4555 \
    --rationale "Solo-dev scope; player economy is out of scope for v1."

uv run lp task add "Wire vendor dialogue to inventory" --wu a85a4555
```

The `--wu` argument accepts an ID prefix, so you rarely need the full
UUID.

## Find in-progress work

```bash
uv run lp work resume "vendor"
```

Output (example):

```text
Active work units matching 'vendor':
- Vendor system redesign  (id: a85a4555..., opened 2d ago)
- Vendor dialogue rewrite (id: 73f0..., opened 5h ago)
```

Pick the one you meant, and keep working. Nothing is reopened — the
work unit was already `in_progress`.

## Close it

```bash
uv run lp work close a85a4555
```

By default `close` refuses if any attached task is still in
`in_progress` — the work unit would be misleading as "done" with an open
task. Either finish the task first, or use `--force`:

```bash
uv run lp work close a85a4555 --force
# or, if the work was dropped:
uv run lp work close a85a4555 --status abandoned
```

## A → B developer handoff

The canonical team pattern: developer A starts something, hits a
context limit or end-of-day, hands off to developer B.

**A** — leaves the work unit in `in_progress` and captures the current
state as a `knowledge` item so B can rebuild the picture quickly:

```bash
uv run lp items add "Vendor work state on 2026-04-14" \
    --type knowledge --wu a85a4555 \
    --body "Dialogue wired, inventory seeded, pricing still TODO. \
            Blocked on: currency formatting lib decision."
```

**B** — opens the repo, asks their MCP client (or runs CLI):

```bash
uv run lp brief --project hearthward
uv run lp work resume "vendor"
uv run lp items list --type knowledge --system vendor
```

…and picks up. `created_by` on the work unit stays as A; whoever runs
`lp work close` becomes `closed_by`. The mismatch is a feature — it
preserves the handoff record.

:::{admonition} Why work units, not sessions
:class: note

A Claude session may last 40 minutes. A decision about vendors may take
two weeks. Tying memory to the shorter unit forces users into arbitrary
re-framings of what they were working on. Work units let a human say
"this chunk of intent" once, and let clients come and go underneath.
:::

## Brief it

`lp brief` (or `luplo_brief` from an MCP client) returns the project's
active work units alongside recent items, giving a new session a
compact picture of what the human is in the middle of:

```text
## Active Work Units
- Vendor system redesign (id: a85a4555-...)
- Auth rewrite (id: 73f0-...)

## Recent Items
- [decision] Use NPC merchants over player shops
- [policy] Framework化 거부 운영 원칙 — 거부 목록 + 진입 트리거
- [knowledge] Vendor work state on 2026-04-14
```

## Related

- {doc}`tasks-and-qa` — tasks attach to a work unit; QA checks can too.
- {doc}`../concepts/data-model` — the `work_units` row shape.
- {doc}`../reference/cli` — every `lp work *` flag.
