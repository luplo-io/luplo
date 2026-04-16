# Changelog

luplo is pre-1.0 and tracks its changes via Alembic migration ids that
align with sprint versions. This page is the narrative layer on top of
the migrations in `db/migrations/`.

For the schema delta of any version, read the matching `0NNN_*.py` file
in that directory.

## v0.5.3 — `research` item type

**Migration:** `0004_add_research_item_type`

- New system item type `research` seeded into `item_types`. Represents a
  cached external reference — typically a web page — that expires after
  a project-configurable TTL (`.luplo/research.ttl_days`, default 90).
- Partial CHECK constraint: `source_url IS NOT NULL` for rows with
  `item_type='research'`, so a research item cannot slip in without a
  URL.
- Added post-freeze (the v0.5 design on 2026-04-13 didn't include it).
  Parity review against the dogfooding workflow showed research items
  were load-bearing and did not fit cleanly into `knowledge`.

## v0.5.2 — items as substrate

**Migration:** `0003_item_types_and_context`

This is the substrate refactor. Earlier sprints had pencilled in
separate `tasks` and `qa_checks` tables. The v0.5.2 decision was to
**promote `items` into a general-purpose row** and represent tasks /
QA checks as item types with strictly-validated `context` JSONB.

Specifically:

- New `item_types` registry table — `(key, display_name, schema, owner)`
  with JSON-schema-per-type validation.
- `items.item_type` becomes an FK into `item_types`.
- `items.context JSONB` added — free-form per-type, validated against
  `item_types.schema`.
- Seven system types seeded: `decision`, `knowledge`, `policy`,
  `document`, `task`, `qa_check`, plus the earlier-added `research`
  (slotted in by v0.5.3).
- GIN indexes on `context->'target_task_ids'` and
  `context->'target_item_ids'` so QA checks can be looked up by target
  in either direction.
- B-tree index on `(work_unit_id, (context->>'sort_order')::int)` for
  task ordering.
- `task` and `qa_check` schemas are **strict** (`additionalProperties=false`);
  `decision`, `knowledge`, `policy`, `document`, `research` stay permissive
  (see P6 for the "strict by intent, not by owner" rule).

Decisions tied to this change: D1 (items as substrate), D2 (DB as
source of truth for types), P6 (schema strictness policy), P7 (no
partial UNIQUE for in-progress task), P9 (in-place QA revalidation),
P10 (in-place task reorder).

## v0.5.1 — auth redesign

**Migration:** `0002_auth_redesign`

- `actors.id` changed from `TEXT` to `UUID`. All ten FK columns
  referencing actors were migrated in the same transaction so the DB
  never sees a mixed state.
- `actors.email` promoted to the primary human identifier.
- `actors.password_hash TEXT NULL` added. OAuth-only users leave it
  NULL.
- `lp login` lands the JWT in the OS keyring.
- Minimal password flow (argon2id, no reset). Reset is deferred —
  adding it without compromising the "no web UI" stance is v0.6
  material.

Reordering note: this sprint deliberately preceded tasks/qa because
every domain table FKs into `actors` — doing auth after would have
meant re-migrating them all.

## v0.5 — initial 12-table schema

**Migration:** `0001_init_schema`

Schema frozen on 2026-04-13 after a full-day design session. Twelve
tables across three concerns:

- **Core (6):** `projects`, `actors`, `systems`, `items`, `links`,
  `work_units`.
- **Sync (3):** `items_history`, `audit_log`, `sync_jobs`.
- **Glossary (3):** `glossary_groups`, `glossary_terms`,
  `glossary_rejections`.

Design goals covered:

- Items carry supersede chains + soft delete + semantic-impact history.
- Work units replace sessions; they span multiple client sessions and
  record A→B handoffs.
- Glossary is strict-first with a curation queue.
- Vector search (pgvector) is optional and only reranks tsquery
  candidates.
- Worker uses PG LISTEN/NOTIFY — no external broker.

## Versioning note

Pre-1.0, luplo's "versions" are the migration numbers. The PyPI
`0.0.1` tag is a placeholder — real releases will track v0.5 / v0.6
milestones with a proper semantic version once the core is
dog-food-stable end-to-end.

## Related

- {doc}`../concepts/data-model` — the schema in its current form.
- {doc}`../concepts/philosophy` — the commitments behind the design
  choices.
