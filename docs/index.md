# luplo

**Long-term memory for engineering decisions.**

luplo is a CLI + MCP server + HTTP server for tracking decisions,
knowledge, policies, documents, tasks, and QA checks across coding
sessions. It is backed by PostgreSQL with full-text search
(`tsquery` + glossary expansion) and optional pgvector reranking.

Three interfaces share one core:

- `lp` — the human-facing CLI (typer).
- An **MCP server** on stdio, usable from any
  [MCP-compatible client](https://modelcontextprotocol.io/clients)
  (Claude Code, Claude Desktop, Cursor, Zed, custom).
- An optional **FastAPI HTTP server** for multi-user deployments.

## Where to start

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} Quickstart
:link: quickstart
:link-type: doc

Install uv + Postgres, initialise a project, record and recall a
decision, wire up an MCP client — in about five minutes.
:::

:::{grid-item-card} Concepts
:link: concepts/index
:link-type: doc

Why luplo refuses to be a framework, what honesty-over-coverage means
for search, how the twelve-table schema fits together.
:::

:::{grid-item-card} Guides
:link: guides/index
:link-type: doc

How-tos for work units, tasks & QA, connecting MCP clients, running
the Remote server, operating the worker.
:::

:::{grid-item-card} Reference
:link: reference/index
:link-type: doc

CLI flags, MCP tool surface, every configuration variable, and the
auto-generated API reference.
:::

::::

## Project

- Source — <https://github.com/luplo-io/luplo>
- License — {doc}`AGPL-3.0-or-later <project/license>` (CLA coming)
- Changelog — {doc}`project/changelog`
- Contributing — {doc}`project/contributing`

```{toctree}
:hidden:
:maxdepth: 1

quickstart
concepts/index
guides/index
reference/index
project/index
API reference <api/index>
```
