# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

luplo is a CLI + MCP server for long-term memory of engineering decisions. It tracks items (decisions, knowledge, policies, documents), work units, system dependencies, and glossary terms in PostgreSQL, with full-text search (tsquery + glossary expansion) and optional pgvector ranking.

## Architecture

Two interfaces, one core:
- **CLI** (`src/luplo/cli.py`) — typer, human-facing
- **MCP server** (`src/luplo/mcp.py`) — stdio, Claude Desktop/Code integration

Both call into `src/luplo/core/` which abstracts Local (direct PG) vs Remote (HTTP client) via a Backend protocol. The HTTP server that Remote mode talks to lives outside this repo (hosted at `api.luplo.io` or self-hosted); only the client adapter (`core/backend/remote.py`) ships here.

```
src/luplo/
├── core/
│   ├── db.py            # connection, engine
│   ├── backend/         # Local (direct PG) / Remote (HTTP client) protocol
│   ├── items.py         # CRUD + supersedes chain + soft delete
│   ├── work_units.py    # open/resume/close
│   ├── search/          # tsquery + glossary expansion + vector ranking
│   ├── extract/         # transcript → items (LLM)
│   ├── embedding/       # backend abstraction (null/sentence_transformers/remote)
│   ├── glossary.py      # strict-first pipeline
│   ├── sync/            # sync_jobs debounce queue
│   ├── worker.py        # PG LISTEN/NOTIFY unified worker
│   ├── history.py       # items_history
│   └── audit.py         # audit_log
├── cli.py
└── mcp.py
```

## Build, test & development

```bash
# Install
uv sync                                     # core deps
uv sync --extra vector-local                # with sentence-transformers

# Database
createdb luplo                              # or use --docker-pg
alembic upgrade head                        # run migrations
alembic downgrade -1                        # rollback last migration

# CLI (dev mode)
uv run lp --help

# Tests
uv run pytest
uv run pytest tests/path/to/test.py::test_name   # single test

# Lint, format, types
uv run ruff check .
uv run ruff format .
uv run pyright
```

## Data model (12 tables)

Core 6: `projects`, `actors`, `systems`, `items`, `links`, `work_units`
Sync 3: `items_history`, `audit_log`, `sync_jobs`
Glossary 3: `glossary_groups`, `glossary_terms`, `glossary_rejections`

Migrations live in `src/luplo/_db_assets/migrations/` (shipped inside the wheel — see `_migrate.py` for the runtime locator). Config in `alembic.ini` (repo root, dev convenience). Env override: `LUPLO_DB_URL`. Production deploys should run `lp migrate`, which reads only env / `--db-url` and never touches `.luplo`.

## Key design decisions

- **Two modes**: Local (direct PG, single-user) and Remote (HTTP client to an out-of-tree luplo server — `api.luplo.io` or self-hosted). Bearer auth via `LUPLO_CLOUD_API_KEY` or keyring. `.luplo` config file.
- **Embedding default is null backend** — no Python ML deps by default. `vector-local` extras for sentence-transformers.
- **Vector is ranking only, never primary search.** tsquery does retrieval, vector reranks. Honesty > coverage.
- **Glossary is strict-first** — deterministic normalization → strict LLM matching → human curation queue. No aggressive clustering.
- **Soft delete on items** — `deleted_at` field, rows never physically removed. Edits create new rows via `supersedes_id`.
- **work_units** replace sessions — user-facing intent grouping, spans multiple Claude sessions. A→B handoff via `status='in_progress'`.
- **Worker**: `lp worker start` runs the Local-mode background worker; PG LISTEN/NOTIFY for sync_jobs + glossary term candidates. Remote mode delegates this to the upstream server.

## Code standards

- All code, comments, docstrings, and commit messages in **English**
- Public functions and classes must have **Google-style docstrings**
- **ruff** for linting and formatting — zero warnings
- **pyright strict** for type checking — no `# type: ignore`
- **pytest** for tests — core paths must have coverage
- No inline `TODO` without a linked issue
- Imports sorted by ruff (isort-compatible)
- Max line length 99
- Python `>=3.12`

## Commit & PR conventions

- Follow **Conventional Commits** (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- **Do not add `Co-Authored-By: Claude` trailers** — commit as the developer's git identity only
- Do not mark PRs ready for review automatically; leave as draft unless the user asks otherwise
- Do not run destructive git operations (`push --force`, `reset --hard`, branch deletion) without explicit user instruction

## Design docs

Concept-level design lives in `docs/concepts/` and `docs/guides/`. If code and docs diverge, ask before assuming code is correct.
