# Connecting an MCP client

luplo ships a [Model Context Protocol](https://modelcontextprotocol.io)
server on stdio. Any MCP-compatible client — Claude Code, Claude
Desktop, Cursor, Zed, or something built on the MCP SDKs — can call
luplo's tools during a coding session.

This guide shows how to wire up the most common clients and how to
sanity-check the connection. For the full tool surface see
{doc}`../reference/mcp-tools`.

## The launch command

Every client spawns the luplo MCP server the same way:

```bash
uv run --directory /absolute/path/to/luplo python -m luplo.mcp
```

…with `LUPLO_DB_URL` in the environment so the server can reach
Postgres. What varies between clients is only the **config file shape**
that describes this command.

:::{tip}
Use an absolute path for `--directory`. MCP hosts don't execute from
your shell's working directory.
:::

## Claude Code

Claude Code auto-detects `.mcp.json` in the workspace root.

```bash
cp .mcp.json.example .mcp.json
# edit the path and DB URL
```

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
        "LUPLO_DB_URL": "postgresql://USER:PASSWORD@localhost/luplo"
      }
    }
  }
}
```

Reopen the workspace. Claude Code will show `luplo` under MCP servers
and the tools become callable.

## Claude Desktop

Merge the same `mcpServers` block into:

- **macOS** — `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows** — `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux** — `~/.config/Claude/claude_desktop_config.json`

Restart Claude Desktop after editing.

## Cursor

Cursor reads `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per
project). The schema is identical to Claude Code's:

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
        "LUPLO_DB_URL": "postgresql://USER:PASSWORD@localhost/luplo"
      }
    }
  }
}
```

Restart Cursor (or open the project fresh).

## Zed

Zed's MCP support is evolving; consult the
[Zed docs](https://zed.dev) for the current config path. The command
shape is the same `uv run --directory … python -m luplo.mcp`.

## Other clients

Any MCP client that speaks the stdio transport can host luplo. If you
are building a custom client, see the
[MCP client SDKs](https://modelcontextprotocol.io/clients). Pass the
same `command`, `args`, and `env` through the client's server-config
shape.

## Smoke test

Once connected, ask the client:

> "What did we decide about auth in this project?"

A correctly wired client will call `luplo_item_search` with a query
derived from your question, return the matching decisions, and cite
the ids. If you get no results, either no decisions are saved yet or
the project id is wrong.

You can also verify manually from the CLI:

```bash
uv run lp items search "auth" --project myapp
```

If the CLI sees items and the MCP client doesn't, the client is
pointing at a different DB (check `LUPLO_DB_URL`) or a different
project (check the `project_id` argument in the tool calls).

## How clients *should* use luplo

From luplo's perspective, a well-behaved MCP client:

1. Calls `luplo_brief` at most once per session, **only when the human
   asks for context** — not on every prompt. See {doc}`../concepts/philosophy`
   on why there is no auto-injection.
2. Calls `luplo_item_search` liberally — it is cheap, glossary-expanded,
   and returns match reasons.
3. Calls `luplo_save_decisions` and `luplo_item_upsert` **only when the
   human explicitly says so** ("save this decision", "log that we
   decided…"). Never auto-extracts.

These are conventions, not enforcement. luplo has no way to stop a
client from spamming `luplo_brief` on every tool call — that's a client
bug to fix there, not a feature to code around here.

## Trouble

**Client can't find the server.**
: Run the launch command by hand from your shell. If `uv run` works
  there, the host is either using a non-login shell (no `PATH`) or
  `--directory` points at the wrong place. Use absolute paths.

**Tool call succeeds but returns empty.**
: Check the `project_id`. luplo is per-project; an empty project
  responds with nothing. Seed via `lp init`.

**Server crashes on start.**
: Inspect stderr via the client's MCP logs. The most common cause is
  `LUPLO_DB_URL` pointing at a DB that isn't up or doesn't have
  migrations applied — run `alembic upgrade head`.

## Related

- {doc}`../reference/mcp-tools` — every tool the server exposes.
- {doc}`../concepts/architecture` — how MCP fits alongside CLI and HTTP.
