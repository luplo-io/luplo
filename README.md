# luplo

[![Documentation Status](https://readthedocs.org/projects/luplo/badge/?version=latest)](https://luplo.readthedocs.io/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> **AI memory that survives across sessions, teammates, and vendors.**

> Last month I explained a decision to Claude Code.
> Today, back from vacation, a teammate's Codex already knew.

![lp items search recall demo](demos/output/recall.gif)

## What luplo does

Your engineering decisions — structured, searchable, and cited by
typed edges — so three weeks later you (or your teammate, or their AI)
can answer **"why is X like that?"** and **"what else depends on it?"**
without reading the codebase cold.

- **Git for decisions.** Append-only, typed edges, contradiction-aware.
- **`lp impact` tells you what breaks** when you change something.
  Traverses `depends` / `blocks` / `supersedes` / `conflicts` edges up
  to five hops.
- **MCP-native, vendor-neutral.** Ships an MCP server on stdio — works
  with Claude Code, Claude Desktop, Cursor, Zed, or any
  [MCP-compatible client](https://modelcontextprotocol.io/clients).
  Also usable as a plain CLI with no AI at all.
- **Full-text first. Vectors only rerank.** PostgreSQL `tsquery` with
  glossary expansion does retrieval; optional pgvector reorders
  candidates. If it's not there, we say so.

![lp impact blast radius demo](demos/output/impact.gif)

## Quickstart

```bash
# Install
git clone https://github.com/luplo-io/luplo.git
cd luplo
uv sync

# Database
createdb luplo
uv run lp init --project myapp --email you@example.com

# Record a decision
uv run lp work open "Auth rework"
uv run lp items add "Use JWT over session cookies" \
    --type decision \
    --rationale "Stateless auth scales; session store is an extra dep."

# Recall
uv run lp brief
uv run lp items search "auth"
uv run lp impact <decision-id>     # blast radius
```

See the [Quickstart](https://luplo.readthedocs.io/en/latest/quickstart.html)
for the full five-minute walkthrough including uv install, Postgres
setup, and MCP wiring.

## What luplo doesn't do

luplo is opinionated about what it will not become. The
[Philosophy](https://luplo.readthedocs.io/en/latest/concepts/philosophy.html)
page has the long version; the short one:

- **Not a vector database.** Vectors rerank `tsquery` candidates. They
  never lead retrieval and never invent candidates of their own.
- **Not a general-purpose AI memory.** Engineering decisions only — not
  chatbot user profiles, conversation history, or arbitrary facts.
- **Not an editable store.** Decisions are immutable. They get
  superseded, never edited. Your mistakes are your most valuable
  data.
- **Not a graph database.** Edges are typed; traversal stops at five
  hops. If your project needs more, you're modeling it wrong.
- **Not a plugin platform.** luplo is a tool, not a framework. Integrate
  via webhook, sync worker, or MCP — not in-process Python.

If any of these make luplo a worse fit than a chatbot memory, a wiki,
or a ticket queue, use that tool instead.
[Positioning](https://luplo.readthedocs.io/en/latest/concepts/positioning.html)
explains where luplo does and doesn't fit.

## Connect an MCP client

```json
{
  "mcpServers": {
    "luplo": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/luplo",
        "python", "-m", "luplo.mcp"
      ],
      "env": {
        "LUPLO_DB_URL": "postgresql://localhost/luplo"
      }
    }
  }
}
```

Drop this into `.mcp.json` (Claude Code), `claude_desktop_config.json`
(Claude Desktop), `.cursor/mcp.json` (Cursor), or your client's
equivalent. See the
[MCP client guide](https://luplo.readthedocs.io/en/latest/guides/mcp-client.html)
for details.

## Architecture

PostgreSQL (tsquery + glossary expansion + pgvector reranking), typed
edges (`depends` / `blocks` / `supersedes` / `conflicts`), and three
interfaces sharing one core: `lp` CLI, MCP server on stdio, and a
FastAPI HTTP server.

## Documentation

Full docs at **[luplo.readthedocs.io](https://luplo.readthedocs.io/)**:

- [Concepts](https://luplo.readthedocs.io/en/latest/concepts/) —
  philosophy, positioning, architecture, data model, search pipeline.
- [Guides](https://luplo.readthedocs.io/en/latest/guides/) —
  work units, tasks & QA, MCP clients, Remote server, worker.
- [Reference](https://luplo.readthedocs.io/en/latest/reference/) —
  CLI, MCP tools, configuration, semantic impact categories.
- [Roadmap](https://luplo.readthedocs.io/en/latest/project/roadmap.html) —
  what we're building next.
- [API reference](https://luplo.readthedocs.io/en/latest/api/) —
  auto-generated from source.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: English
everywhere, Google-style docstrings, `ruff` + `pyright strict` +
`pytest`, Conventional Commits. Large architectural PRs should open an
issue first — the shape of luplo is a curated decision.

## License

[AGPL-3.0-or-later](LICENSE). A CLA will be required for external
contributions (not yet set up).
