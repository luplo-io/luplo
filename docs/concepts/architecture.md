# Architecture

luplo exposes three interfaces on top of one core. The interfaces stay
thin — they translate user input into calls on a backend — and the core
handles everything that matters: database access, search, glossary,
history, audit, worker dispatch.

```
      ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
      │     CLI     │   │     MCP     │   │    HTTP     │
      │   (typer)   │   │   (stdio)   │   │  (FastAPI)  │
      └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
             │                 │                 │
             └────────┬────────┴────────┬────────┘
                      │                 │
                      ▼                 ▼
                ┌────────────────────────────┐
                │   core.backend.Backend     │
                │  (Local | Remote protocol) │
                └──────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │   items · work_units ·   │
                  │   search · glossary ·    │
                  │   history · audit · ...  │
                  └──────────────┬───────────┘
                                 │
                                 ▼
                           PostgreSQL
                        (+ optional pgvector)
```

## The three interfaces

### CLI — `lp`

`src/luplo/cli.py` — a [typer](https://typer.tiangolo.com/) app that
exposes human-facing commands: `lp init`, `lp brief`, `lp items add`,
`lp work open`, `lp task start`, `lp qa pass`, `lp worker`, etc. It reads
`.luplo` (see {doc}`../reference/config`) to resolve the active project
and actor so most commands do not need flags.

### MCP — stdio server

`src/luplo/mcp.py` — speaks the [Model Context
Protocol](https://modelcontextprotocol.io) over stdio. Any MCP-compatible
client (Claude Code, Claude Desktop, Cursor, Zed, custom SDK) can call
tools like `luplo_brief`, `luplo_item_search`,
`luplo_save_decisions`, `luplo_work_open`, `luplo_task_start`.

The surface of tools exposed to clients is deliberately small (~20
tools) — LLMs get confused with large toolboxes. See
{doc}`../reference/mcp-tools` for the full list.

### HTTP — FastAPI

`src/luplo/server/` — the Remote-mode server. Installed via the `server`
extra (`uv sync --extra server`). Provides:

- Auth routes (`/auth/login`, `/auth/refresh`, OAuth start/callback,
  admin password set).
- Item / work-unit / search routes mirroring the core surface.
- A minimal login page (no SPA, no React).

The HTTP server is not required for Local-mode usage. A solo developer
can run CLI + MCP directly against Postgres without ever booting the
server.

## The core

Everything lives in `src/luplo/core/` and is organised by domain:

```
core/
├── db.py              connection pool, engine
├── backend/           Backend protocol (Local, Remote)
│   ├── protocol.py
│   ├── local.py
│   └── remote.py
├── items.py           CRUD + supersedes chain + soft delete
├── work_units.py      open / resume / close
├── tasks.py           item_type='task' wrapper
├── qa.py              item_type='qa_check' wrapper
├── links.py           typed edges between items / systems / work units
├── systems.py         system graph (dependencies)
├── projects.py        project row + seed
├── actors.py          users (email-first, argon2 passwords, OAuth)
├── glossary.py        strict-first glossary pipeline
├── search/            pipeline.py, tsquery.py
├── embedding/         protocol / null / local (sentence-transformers)
├── extract/           LLM-based item extraction (opt-in)
├── sync/              sync_jobs debounce queue
├── worker.py          PG LISTEN/NOTIFY worker loop
├── history.py         items_history writers/readers
├── audit.py           audit_log writer
├── item_types.py      DB-backed type registry + JSON-schema validators
├── schemas/           seed JSON schemas (decision, task, qa_check, …)
├── models.py          plain dataclasses returned by core calls
└── errors.py          domain exceptions
```

### Backend protocol

All three interfaces depend on `core.backend.Backend`:

- **`LocalBackend`** — direct `psycopg` pool against PostgreSQL.
  Used by Local-mode CLI, Local-mode MCP, and the HTTP server itself.
- **`RemoteBackend`** — HTTP client against a luplo server. Used by
  Remote-mode CLI and Remote-mode MCP so a team member can work against
  a shared server without DB credentials.

Switching modes is a `.luplo` change. No code in `cli.py`, `mcp.py`, or
the routes knows or cares which backend is in play.

## Writes and the audit trail

Every write path in the core funnels through:

1. Domain function (`items.create_item`, `tasks.transition_task`,
   `qa.assign_qa`, …) validated by JSON-schema when `item_type` is
   strict (`task`, `qa_check`).
2. A row in the target table (`items`, `work_units`, `links`, …).
3. An `audit_log` entry with `actor_id`, `action`, and a payload that
   describes what changed. Mutating functions always require an
   `actor_id` parameter — this is enforced in the function signatures.
4. Where applicable, an `items_history` row capturing the
   semantic_impact diff (see {doc}`../reference/semantic-impact`).
5. Optionally, a `sync_jobs` row that the worker drains asynchronously.

The one-way flow — **caller → core function → table + audit + history
+ queue** — means any record can be traced back to the command that
produced it. This is how luplo stays honest about who did what.

## The worker

`src/luplo/core/worker.py` — a single long-running loop that uses
`PG LISTEN/NOTIFY` to wake on two channels:

- `sync_jobs` — outbound sync work (debounced per-item so a rapid edit
  burst collapses into one external write).
- Glossary term candidates — terms the LLM pipeline flagged for human
  review.

The worker is deliberately single-process and dependency-free (no Redis,
no Celery). In Local mode you start it with `lp worker`. In Remote mode
the FastAPI lifespan hook starts and stops it alongside the server.

See {doc}`../guides/local-worker` for details.

## Data plane

PostgreSQL is the single source of truth — schema, history, audit, sync
queue, worker triggers, and the glossary all live in one database. See
{doc}`data-model` for the twelve tables.

## Next

- {doc}`data-model` — the twelve tables and how items became a substrate.
- {doc}`search-pipeline` — how retrieval really works.
- {doc}`../guides/remote-server` — running the HTTP server for a team.
