# luplo

Long-term memory for engineering decisions.

luplo is a CLI + MCP server that tracks decisions, knowledge, policies,
documents, tasks, and QA checks across coding sessions. It is backed by
PostgreSQL with full-text search (tsquery + glossary expansion) and
optional pgvector ranking.

## Getting started

```bash
uv sync
createdb luplo
alembic upgrade head
uv run lp --help
```

See [CONTRIBUTING.md](https://github.com/luplo-io/luplo/blob/main/CONTRIBUTING.md)
for the full development guide.

## Interfaces

luplo exposes three interfaces on a shared core:

- **CLI** (`lp`) — human-facing commands via typer.
- **MCP server** — stdio adapter for Claude Desktop/Code.
- **HTTP server** — FastAPI + OAuth for the Remote backend (via the
  `server` extra).

## API reference

See the auto-generated [API reference](api/luplo/index) for the full
module layout and every public function/class.

## Source

- Repository: <https://github.com/luplo-io/luplo>
- License: AGPL-3.0-or-later + CLA

```{toctree}
:maxdepth: 2
:hidden:

api/index
```
