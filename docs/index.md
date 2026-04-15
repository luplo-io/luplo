# luplo

Long-term memory for engineering decisions.

luplo is a CLI + MCP server that tracks decisions, knowledge, policies,
documents, tasks, and QA checks across coding sessions. It is backed by
PostgreSQL with full-text search (tsquery + glossary expansion) and
optional pgvector ranking.

## Getting started

See the {doc}`quickstart` for a five-minute tour — install, open a
work unit, save a decision, and connect Claude via MCP.

For the full development workflow, see
[CONTRIBUTING.md](https://github.com/luplo-io/luplo/blob/main/CONTRIBUTING.md).

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

quickstart
api/index
```
