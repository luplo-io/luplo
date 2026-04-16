# Work units

A **work unit** is a user-facing grouping of related items that belongs
to a single intent — "Auth service rework", "Rate limiter redesign",
"v0.5.1 handoff" — and may span many sessions. Work units replaced an
earlier `sessions` concept: sessions conflated a client process lifetime
with a human intent lifetime, and that was the wrong frame for decision
memory.

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
   lp work resume "auth"  ◄────────────────────────────────────────┘
```

## Open a work unit

```bash
uv run lp work open "Auth service rework" \
    --desc "Scope: JWT middleware, OAuth callback, refresh-token rotation."
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
uv run lp items add "Use JWT over session cookies" \
    --type decision --wu a85a4555 \
    --rationale "Stateless auth scales; the session store is an extra dep."

uv run lp task add "Add JWT validation middleware" --wu a85a4555
```

`--wu` (and every other id argument in the CLI) accepts a hex prefix of
**at least 8 characters** — `a85a4555` instead of the full UUID. If
that prefix matches more than one row the CLI prints the conflicting
ids and exits non-zero, so you never act on the wrong row by accident.
MCP and HTTP callers still require the full UUID — see
{doc}`../concepts/architecture` for why the asymmetry is deliberate.

## Find in-progress work

```bash
uv run lp work resume "auth"
```

Output (example):

```text
Active work units matching 'auth':
- Auth service rework      (id: a85a4555..., opened 2d ago)
- Auth cache invalidation  (id: 73f0...,     opened 5h ago)
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
uv run lp items add "Auth rework state on 2026-04-14" \
    --type knowledge --wu a85a4555 \
    --body "JWT middleware wired on incoming requests. Refresh-token \
            rotation still TODO. Blocked on: logging library decision \
            (stdlib vs structlog)."
```

**B** — opens the repo, asks their MCP client (or runs CLI):

```bash
uv run lp brief --project myapp
uv run lp work resume "auth"
uv run lp items list --type knowledge --system auth
```

…and picks up. `created_by` on the work unit stays as A; whoever runs
`lp work close` becomes `closed_by`. The mismatch is a feature — it
preserves the handoff record.

:::{admonition} Why work units, not sessions
:class: note

An MCP client session may last 40 minutes. A decision about auth may
take two weeks. Tying memory to the shorter unit forces users into
arbitrary re-framings of what they were working on. Work units let a
human say "this chunk of intent" once, and let clients come and go
underneath.
:::

## Brief it

`lp brief` (or `luplo_brief` from an MCP client) returns the project's
active work units alongside recent items, giving a new session a
compact picture of what the human is in the middle of:

```text
## Active Work Units
- Auth service rework (id: a85a4555-...)
- Rate limiter redesign (id: 73f0-...)

## Recent Items
- [decision] Use JWT over session cookies
- [policy]   All public endpoints require auth middleware
- [knowledge] Auth rework state on 2026-04-14
```

## Related

- {doc}`tasks-and-qa` — tasks attach to a work unit; QA checks can too.
- {doc}`../concepts/data-model` — the `work_units` row shape.
- {doc}`../reference/cli` — every `lp work *` flag.
