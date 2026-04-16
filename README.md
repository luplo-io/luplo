# luplo

[![Documentation Status](https://readthedocs.org/projects/luplo/badge/?version=latest)](https://luplo.readthedocs.io/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> Long-term memory for engineering decisions.

luplo tracks decisions, knowledge, policies, documents, tasks, QA checks,
and research across coding sessions — searchable forever, handed off in one
command.

## Why luplo

- **Session handoff in one command.** Developer A spent two hours building
  context. `lp brief` gives developer B all of it — active work units,
  recent decisions, open tasks — instantly.
- **Glossary-expanded search.** `"auth"` finds items indexed under
  `"authentication"` or `"sign-in"` via a strict-first glossary pipeline.
  PostgreSQL tsquery retrieves; optional pgvector reranks.
- **Tasks and QA as first-class items.** Tasks carry a state machine
  (proposed → in_progress → done / blocked / skipped). QA checks target
  tasks or items with coverage and area tags. Blocking a task
  auto-creates a decision item so the reason surfaces in search.
- **MCP-native, vendor-neutral.** Ships an MCP server on stdio — works
  with Claude Code, Claude Desktop, Cursor, Zed, or any
  [MCP-compatible client](https://modelcontextprotocol.io/clients).
  Also usable as a plain CLI with no AI at all.
- **Your data, your database.** PostgreSQL. Local mode for solo use,
  Remote mode (FastAPI + JWT) for teams. AGPL-3.0.

## Quick start

```bash
# Install
git clone https://github.com/luplo-io/luplo.git
cd luplo
uv sync

# Database
createdb luplo
uv run lp init --project myapp --email you@example.com

# Work
uv run lp work open "Auth rework"
uv run lp items add "Use JWT over session cookies" \
    --type decision \
    --rationale "Stateless auth scales; session store is an extra dep."
uv run lp task add "Add JWT validation middleware" --wu <work-id>
uv run lp task start <task-id>
# (work)
uv run lp task done <task-id>

# Recall
uv run lp brief
uv run lp items search "auth"
```

See the [Quickstart](https://luplo.readthedocs.io/en/latest/quickstart.html)
for the full walkthrough including uv install, Postgres setup, and MCP
wiring.

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

## Documentation

Full docs at **[luplo.readthedocs.io](https://luplo.readthedocs.io/)**:

- [Concepts](https://luplo.readthedocs.io/en/latest/concepts/) —
  philosophy, architecture, data model, search pipeline.
- [Guides](https://luplo.readthedocs.io/en/latest/guides/) —
  work units, tasks & QA, MCP clients, Remote server, worker.
- [Reference](https://luplo.readthedocs.io/en/latest/reference/) —
  CLI, MCP tools, configuration, semantic impact categories.
- [API reference](https://luplo.readthedocs.io/en/latest/api/) —
  auto-generated from source.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: English
everywhere, Google-style docstrings, `ruff` + `pyright strict` +
`pytest`, Conventional Commits.

## License

[AGPL-3.0-or-later](LICENSE). A CLA will be required for external
contributions (not yet set up).
