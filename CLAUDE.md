# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

luplo is a CLI + MCP server for long-term memory of engineering decisions. Tracks items (decisions, knowledge, policies, documents), work units, system dependencies, and glossary terms. PostgreSQL with full-text search (tsquery + glossary expansion) and optional pgvector ranking. AGPL-3.0 + CLA.

Primary use case: Hearthward (solo MMORPG) development infrastructure. Secondary: enterprise Notion/Confluence semantic change layer. Tertiary: compliance audit (v1.0+).

## Architecture

Three interfaces, one core:
- **CLI** (`src/luplo/cli.py`) — typer, human-facing
- **MCP server** (`src/luplo/mcp.py`) — stdio, Claude Desktop/Code integration
- **HTTP server** (`src/luplo/server/`) — FastAPI, Remote mode only (`luplo[server]` extras)

All three call into `src/luplo/core/` which abstracts Local (direct PG) vs Remote (HTTP) via a Backend protocol.

```
src/luplo/
├── core/
│   ├── db.py            # connection, engine
│   ├── backend/         # Local / Remote protocol
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
├── mcp.py
└── server/
    ├── app.py
    ├── auth/
    └── routes/
```

## Build & development

```bash
uv sync                                     # install deps
uv sync --extra server                      # with FastAPI/auth
uv sync --extra vector-local                # with sentence-transformers

# Database
createdb luplo                              # or use --docker-pg
alembic upgrade head                        # run migrations
alembic downgrade -1                        # rollback last migration

# CLI (dev mode)
uv run lp --help
```

## Data model (12 tables)

Core 6: `projects`, `actors`, `systems`, `items`, `links`, `work_units`
Sync 3: `items_history`, `audit_log`, `sync_jobs`
Glossary 3: `glossary_groups`, `glossary_terms`, `glossary_rejections`

Migrations live in `db/migrations/`. Config in `alembic.ini`. Env override: `LUPLO_DB_URL`.

## Key design decisions

- **Two modes**: Local (direct PG, single-user) and Remote (FastAPI + OAuth, team). `.luplo` config file.
- **Embedding default is null backend** — no Python ML deps by default. `vector-local` extras for sentence-transformers.
- **Vector is ranking only, never primary search.** tsquery does retrieval, vector reranks. Honesty > coverage.
- **Glossary is strict-first** — deterministic normalization → strict LLM matching → human curation queue. No aggressive clustering.
- **Soft delete on items** — `deleted_at` field, rows never physically removed. Edits create new rows via `supersedes_id`.
- **work_units** replace sessions — user-facing intent grouping, spans multiple Claude sessions. A→B handoff via `status='in_progress'`.
- **Worker**: `lp worker start` (Local) or server lifespan (Remote). PG LISTEN/NOTIFY for sync_jobs + glossary term candidates.
- **systems** name kept (features considered and rejected — mental rewiring cost + cj data compat).

## Code standards (OSS grade)

- All code, comments, docstrings, and commit messages in **English**
- Public functions and classes must have **Google-style docstrings**
- **ruff** for linting and formatting — zero warnings
- **pyright strict** for type checking — no `# type: ignore`
- **pytest** for tests — core paths must have coverage
- Commit messages follow **Conventional Commits** (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- No inline `TODO` without a linked issue
- Imports sorted by ruff (isort-compatible)
- Max line length 99

## Source of truth

Design specs live in Notion (3 pages). Code follows them; if code and Notion diverge, ask before assuming code is wrong.

## Project setup

- **Python**: >=3.12 (dev on 3.14)
- **Build**: Hatchling (src layout)
- **Package**: `src/luplo/`
- **PyPI**: luplo 0.0.1
- **GitHub**: luplo-io/luplo
- **License**: AGPL-3.0-or-later + CLA
