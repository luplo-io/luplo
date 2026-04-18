# Changelog

All notable changes to luplo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While luplo is in `0.x`, minor-version bumps (`0.x` → `0.(x+1)`) may contain
breaking changes; patch bumps are bug fixes only. Once `1.0.0` is tagged the
public CLI / MCP tool / HTTP surface becomes a stability commitment.

## [Unreleased]

## [0.6.2] - 2026-04-18

Hotfix on top of 0.6.1 — `lp login` / `lp whoami` / `lp logout`
crashed on headless Linux (including CI runners) because the
`keyring` library raises `NoKeyringError` when no backend is
available and v0.6.1 did not guard the call sites.

### Fixed

- **`cli.py` keyring call sites** — `_store_token` now catches
  `KeyringError` and prints an actionable message pointing at
  `secret-tool` / desktop session before exiting 1. `_load_token`
  returns `None` when the backend is unavailable (indistinguishable
  from "not logged in" at the caller). `_delete_token` broadens
  `contextlib.suppress` from `PasswordDeleteError` to `KeyringError`.
- **`tests/test_cli.py`** — regression test asserting `lp whoami`
  prints "Not logged in" when the backend is unavailable. This is
  the exact failure that broke CI on the 0.6.1 release commit.

## [0.6.1] - 2026-04-18

A v0.6 follow-up focused on the deterministic rule pack, one residual
logging bug, a wide AI-smell cleanup, and a large test-coverage push.
No schema changes. No public API removals.

### Added

- **Rule pack (`lp check`)** — deterministic checks over the item
  graph with five starter rules: `missing_rationale` (error),
  `undated_retention` (warn), `dangling_edge` (warn),
  `unresolved_conflict` (warn), and `unlinked_policy` (info). Rules
  are SQL + Python only; no LLM, no plugin runtime. Surfaces on
  `lp check [--rule NAME]... [--severity LEVEL] [--list]`, MCP tool
  `luplo_check`, and `GET /checks?project_id=&rule=`. Non-zero CLI
  exit on any `error`-severity finding.
- **`.luplo [checks] disabled_rules`** — per-project rule disable.
  A disabled rule is skipped even when the caller asks for it
  explicitly via `--rule`; project-level disable is the stronger
  signal.
- **`docs/reference/checks.md`** — one section per rule plus
  "what the rule pack is not" (no compliance certification, no
  LLM auditor, no plugin runtime).

### Fixed

- **`core/worker.py:117`** — `fail_sync_job(..., error=str(Exception))`
  was logging the string `"<class 'Exception'>"` because the except
  clause had no binding. Fixed to `except Exception as exc: ...
  str(exc)` so real failure messages reach the sync-job record.

### Changed

- **AI-smell sweep across `src/luplo/`** — removed Step 1/2/3
  scaffolding comments from `cli.py init`, `core/search/pipeline.py
  search`, and `core/glossary.py expand_query`. Private-helper
  docstring compression on `_resolve_head` (tasks + qa),
  `row_to_item`, `_run`, `_revalidate_qa_for`. `_print_task` and
  `_print_qa` dropped their `item: object` + isinstance-assert
  defence in favour of a `item: Item` signature. `errors.py`
  module docstring de-romanised. `_render_impact_json`'s hand-rolled
  `_asdict` walk replaced with stdlib `dataclasses.asdict`.
  `item_types.__all__` no longer re-exports error classes (single
  source: `core.errors`). Misc: redundant inline imports, Korean
  example in a Protocol docstring.

### Tests + CI

- **+119 new tests** (300 → 419): `tests/test_auth_helpers.py` (unit
  coverage for password/jwt/pkce/domain_filter helpers),
  `tests/test_remote_backend.py` (HTTP round-trips through a stubbed
  transport), expanded `tests/test_cli.py` (top-level and subcommand
  groups end-to-end), expanded `tests/test_mcp.py` (smoke → real tool
  invocations with a module-scoped backend fixture), expanded
  `tests/test_auth_routes.py` (paths not covered by password-reset
  work).
- **`codecov.yml`** — project + patch coverage gate with a ratcheting
  threshold so merges that lower coverage fail CI.

## [0.6.0] - 2026-04-17

Narrative v0.6 ships. PyPI version jumps 0.1.0 → 0.6.0 to align the
SemVer axis with the migration-aligned narrative versions in
`docs/project/changelog.md` (v0.5, v0.5.1, v0.5.2, v0.5.3, v0.6). Pre-1.0
version numbers are not dense — skipping 0.2 through 0.5 is deliberate.

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

[Unreleased]: https://github.com/luplo-io/luplo/compare/v0.6.2...HEAD
[0.6.2]: https://github.com/luplo-io/luplo/releases/tag/v0.6.2
[0.6.1]: https://github.com/luplo-io/luplo/releases/tag/v0.6.1
[0.6.0]: https://github.com/luplo-io/luplo/releases/tag/v0.6.0
[0.1.0]: https://github.com/luplo-io/luplo/releases/tag/v0.1.0
