# Data model

luplo's schema was frozen on 2026-04-13 as **twelve tables** split across
three concerns: core domain (6), sync and history (3), and glossary (3).
A post-freeze refactor promoted `items` into a general-purpose substrate;
tasks and QA checks stopped being new tables and became **item types**
with typed `context` JSONB. A small `item_types` registry gives the
database a language-agnostic contract for extension.

## The twelve tables

### Core (6)

| Table | Purpose |
|---|---|
| `projects` | Top-level scope. Most queries are `WHERE project_id = ?`. |
| `actors` | Users. Email-first primary identity (v0.5.1+), UUID id, argon2 password hash nullable (OAuth-only users leave it NULL). |
| `systems` | Named components inside a project with optional dependency edges. "Auth", "Payments", "Notifications". Items and work units tag into these. |
| `items` | The substrate. One row per decision / knowledge / policy / document / task / qa_check / research (and any user-registered type). See below for columns. |
| `links` | Typed edges — item↔item, item↔system, item↔work_unit. |
| `work_units` | User-facing intent grouping. Spans multiple sessions. Replaces the earlier `sessions` concept. |

### Sync & history (3)

| Table | Purpose |
|---|---|
| `items_history` | Immutable row per semantic edit of an item. Carries `semantic_impact` (see {doc}`../reference/semantic-impact`). |
| `audit_log` | Every write through the core, with `actor_id`, `action`, payload. The authoritative "who did what". |
| `sync_jobs` | Debounced outbound-sync queue drained by the worker. |

### Glossary (3)

| Table | Purpose |
|---|---|
| `glossary_groups` | A normalized term plus its approved aliases. Expands queries at search time. |
| `glossary_terms` | Pending candidates awaiting curation (plus rejected history for auditability). |
| `glossary_rejections` | Permanent "do not suggest this again" list, scoped per group. |

## Items as substrate

The big shift after 2026-04-13 was giving up the three-tier split (items /
tasks / qa_checks as separate tables) and promoting `items` into a
general-purpose row. The reasons:

- `items` already had `item_type`, `system_ids`, `tags`, `supersedes_id`,
  `deleted_at`, actor, project — every cross-cutting field a domain
  object needs.
- An OSS user wanting a custom type (sprints, retros, stand-ups) can now
  `INSERT` into `item_types` and start using it. Forking luplo is no
  longer the entry fee.
- The DB, not Python, is the contract. Raw SQL and non-Python clients
  can add a type without importing anything.

### The `item_types` registry

```sql
CREATE TABLE item_types (
  key          TEXT PRIMARY KEY,   -- 'task', 'qa_check', 'decision', ...
  display_name TEXT NOT NULL,
  schema       JSONB NOT NULL,     -- JSON Schema, validates context
  owner        TEXT NOT NULL,      -- 'system' or 'user'
  created_at   TIMESTAMPTZ DEFAULT now()
);
```

`items.item_type` carries a foreign key into this table. Seven system
types ship in the migrations:

| key | Schema policy | Notes |
|---|---|---|
| `decision` | loose (`additionalProperties` permitted) | free-form rationale + alternatives |
| `knowledge` | loose | "how X works", gotchas |
| `policy` | loose | organisational must-do / must-not |
| `document` | loose | specs, RFCs |
| `research` | loose + `source_url NOT NULL` CHECK | cached external references with TTL |
| `task` | strict (`additionalProperties=false`) | status machine, sort_order, block reason |
| `qa_check` | strict | coverage, area, severity, target arrays |

**Strict vs loose is by intent, not by owner.** Types that gate behavior
(task, qa_check) enforce their context shape so the state machines stay
honest. Types that exist for human prose (decision, policy) stay permissive
so new fields don't require a migration. See P6 in the project decision log.

## The `items` row

Key columns shared across every item type:

| Column | Type | Role |
|---|---|---|
| `id` | UUID | primary key |
| `project_id` | UUID | scope |
| `item_type` | TEXT FK → `item_types.key` | domain discriminator |
| `title` | TEXT | human label (indexed for tsquery) |
| `body` | TEXT | main content (indexed) |
| `rationale` | TEXT | why this decision (indexed) |
| `alternatives` | TEXT | what was considered and rejected |
| `system_ids` | UUID[] | systems touched (GIN indexed) |
| `tags` | TEXT[] | free tags (GIN indexed) |
| `context` | JSONB | type-specific fields, validated against `item_types.schema` |
| `source_url` | TEXT | external reference (research type requires it) |
| `actor_id` | UUID | who wrote this row |
| `work_unit_id` | UUID NULL | optional grouping |
| `supersedes_id` | UUID NULL | previous chain head when edited |
| `deleted_at` | TIMESTAMPTZ NULL | soft delete |
| `ts` | `tsvector` | generated — full-text search vector |
| `embedding` | `vector(1024)` | only when `pgvector` is installed |

### Supersede chain

> **Decisions are immutable. They get superseded, never edited. Your
> mistakes are your most valuable data.**

Edits **never mutate** an existing row. `update_item` writes a new row
with `supersedes_id` pointing at the previous head. Readers follow the
chain to the current head; auditors walk it backwards. The principle:
a wrong decision teaches more than a right one — overwriting it destroys
the lesson.

Two deliberate exceptions where luplo **updates in place with an audit
entry** instead of creating a new row:

- Task `sort_order` — a presentation concern; N=100 reorders would
  otherwise create 3N writes and bloat the chain (P10).
- QA-check revalidation trigger — a system-initiated "please re-look"
  flag, not a human-decided change (P9).

These exceptions are recorded as explicit policy decisions in the project
log. Everything else obeys the rule "human decision → new row".

### Soft delete

`deleted_at` marks rows as gone without physically removing them.
`get_item` and default listings hide deleted rows; history and audit
readers still see them. This is the compliance floor: no write is ever
lost, and any past state can be reconstructed.

## Relationships

- **`links`** carries typed edges. Common kinds: `supersedes`, `implements`,
  `conflicts_with`, `belongs_to` (item→work_unit), `touches` (item→system).
- **`systems`** can declare dependencies on other systems — a small graph
  captured per project so briefs and search can include neighbours.
- **`work_units`** attach to items via `items.work_unit_id` and to the
  creator/closer via two `actor_id` columns — see
  {doc}`../guides/work-units` for the A→B handoff pattern.

## Where the design is written down

Migrations are the executable spec:

```
db/migrations/
├── 0001_init_schema.py               # 12 tables, frozen 2026-04-13
├── 0002_auth_redesign.py             # actors TEXT → UUID, email-first
├── 0003_item_types_and_context.py    # substrate refactor + registry
└── 0004_add_research_item_type.py    # research type + URL CHECK
```

See {doc}`../project/changelog` for the narrative version.
