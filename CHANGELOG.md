# Changelog

All notable changes to luplo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While luplo is in `0.x`, minor-version bumps (`0.x` → `0.(x+1)`) may contain
breaking changes; patch bumps are bug fixes only. Once `1.0.0` is tagged the
public CLI / MCP tool / HTTP surface becomes a stability commitment.

## [Unreleased]

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
