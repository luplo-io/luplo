# Changelog

All notable changes to luplo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While luplo is in `0.x`, minor-version bumps (`0.x` → `0.(x+1)`) may contain
breaking changes; patch bumps are bug fixes only. Once `1.0.0` is tagged the
public CLI / MCP tool / HTTP surface becomes a stability commitment.

## [Unreleased]

### Added

- **Audit (impact analysis)** — `lp impact <id> [--depth N<=5] [--format tree|flat|json]`,
  MCP tool `luplo_impact`, and `GET /items/{id}/impact`. Recursive CTE
  over typed edges (`depends` / `blocks` / `supersedes` / `conflicts`)
  with cycle prevention, project scope, and a five-hop ceiling enforced
  server-side.
- **`lp task edit` + `luplo_task_edit`** — dedicated surface for editing
  a task's title / body / sort_order via supersede (status machine
  preserved).
- **On `task done`, propose a decision draft** — CLI flag
  `--propose-decision` and MCP kwarg `propose_decision` return a
  never-inserted `ItemCreate` draft derived from the completed task.
- **Web-search-style search** — `"exact phrase"`, `word OR word`,
  `-negation`. Glossary expansion applies only to required and OR-group
  terms; phrases and negations are literal.
- **Password reset (magic link)** — `POST /auth/reset-request`
  (no-enumeration), `POST /auth/reset-confirm` (atomic token use +
  password rotation). Argon2id token hashes, 15-minute TTL. New
  `EmailSender` abstraction with logging and SMTP backends.
- **`docs/concepts/positioning.md`** — 8-axis comparison against a
  generic AI-memory tool, plus "when luplo is the wrong tool".
- **`docs/project/roadmap.md`** — public roadmap (Audit →
  Slack `/archive` → Notion webhook → rule pack).
- **`demos/`** — reproducible VHS pipeline with fixed-ID seed data for
  the README's recall and impact gifs.

### Changed

- **Philosophy** restructured around **five refusals**
  (vectors-don't-lead, five-hop, decisions-immutable,
  typed-and-bounded-edges, not-a-general-memory). The three existing
  operational commitments (tool-not-framework, augment-not-replace,
  honesty-over-coverage) moved below as the enforcement layer.
- **Hero tagline** is now "AI memory that survives across sessions,
  teammates, and vendors." — applied to README, docs, `pyproject.toml`
  description, `src/luplo/__init__.py`, and the FastAPI app.
- **Mutator project scope** — `start_task`, `complete_task`, `block_task`,
  `skip_task`, `reorder_tasks`, `start_qa`, `pass_qa`, `fail_qa`,
  `block_qa`, `skip_qa`, `assign_qa` all accept `project_id` kwarg
  threaded into prefix resolution. CLI and MCP surfaces pass the
  current project automatically.
- **CLI error handling** — `_run` now catches `NotFoundError` subclasses
  and prints a clean message instead of a traceback (exposed by the
  scope work above).

### Fixed

- Cross-project prefix collisions could silently mutate a task / QA
  check in the wrong project. Closed by the scope propagation above.

### Migrations

- `0005_auth_reset_tokens` — new table for magic-link reset tokens.

## [0.1.0] - 2026-04-16

Initial public release. luplo is usable end-to-end in Local mode and is
documented at <https://luplo.readthedocs.io>.

### Added

- **PostgreSQL schema** — 12 tables covering projects, actors, work_units,
  systems, items, links, the item_types registry, items_history, audit_log,
  sync_jobs, and the three glossary tables (migrations 0001–0004).
- **CLI (`lp`)** — `init`, `brief`, `worker`, and subcommand groups for
  `items`, `work`, `systems`, `glossary`, `task`, `qa`, plus
  `login`/`logout`/`whoami`/`token`/`admin`/`server` for the Remote backend.
- **MCP server** — stdio adapter for any MCP-compatible client (Claude
  Code / Claude Desktop / Cursor / Zed / custom). Exposes `luplo_brief`,
  `luplo_item_search`, `luplo_item_upsert`, `luplo_work_*`, `luplo_task_*`,
  `luplo_qa_*`, `luplo_page_sync`, `luplo_history_query`, and
  `luplo_save_decisions`.
- **HTTP server** — optional FastAPI + OAuth app under the `server`
  extra, with routes for items, work units, projects, search, and auth.
- **`research` item_type** — cached external references with a required
  `source_url` (enforced by DB `CHECK` and an early app-level guard) and
  a configurable TTL via `expires_at`. Default TTL is 90 days; override
  with `[research] ttl_days = N` in `.luplo`.
- **Documentation** — Sphinx + Read the Docs at
  <https://luplo.readthedocs.io>, including quickstart, concepts,
  guides, reference, and an autoapi-generated API reference.

[Unreleased]: https://github.com/luplo-io/luplo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/luplo-io/luplo/releases/tag/v0.1.0
