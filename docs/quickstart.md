# Quickstart

A five-minute tour: install luplo, open a work unit, save a decision,
search it back, and wire it up to Claude via MCP.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for package management
- **PostgreSQL 15+** running locally (or Docker)

## 1. Install

```bash
git clone https://github.com/luplo-io/luplo.git
cd luplo
uv sync
```

To include the HTTP server (Remote backend) install the extra:

```bash
uv sync --extra server
```

## 2. Create the database

```bash
createdb luplo
```

If your PostgreSQL user/password is non-default, export `LUPLO_DB_URL`
before the next step:

```bash
export LUPLO_DB_URL="postgresql://USER:PASSWORD@localhost/luplo"
```

## 3. Initialise the project

`lp init` writes a `.luplo` config file, runs migrations, and seeds
your project and actor rows:

```bash
uv run lp init --project hearthward --email you@example.com
```

After this, every other `lp` command reads the project/actor from
`.luplo` automatically — you do not need to pass `--project` each time.

## 4. Record something

Open a work unit (a user-facing grouping of related decisions) and
attach a decision to it:

```bash
# Open a work unit
uv run lp work open "Vendor system design"

# Add a decision
uv run lp items add "Use NPC merchants over player shops" \
    --type decision \
    --rationale "Solo-dev scope; player economy is out of scope for v1."
```

## 5. Recall it

Get a project-level brief (active work + recent items):

```bash
uv run lp brief
```

Search items with glossary-expanded full-text search:

```bash
uv run lp items search "vendor"
```

## 6. Connect Claude (MCP)

luplo ships an MCP server so Claude Code / Claude Desktop can read and
write items during a coding session.

Copy the example config and edit paths/credentials:

```bash
cp .mcp.json.example .mcp.json
# Edit .mcp.json: set the absolute path and LUPLO_DB_URL
```

Claude Code auto-detects `.mcp.json` in the project root on the next
session start. In Claude Desktop, merge the `mcpServers` block into
`claude_desktop_config.json` and restart Desktop.

Once connected, ask Claude things like "what did we decide about
vendors?" — it will call `luplo_item_search` through MCP and cite the
items it finds.

## Next steps

- Run `uv run lp --help` to see every CLI command.
- Browse the {doc}`API reference <api/luplo/index>` for the full module
  layout and every public function/class.
- Read
  [CONTRIBUTING.md](https://github.com/luplo-io/luplo/blob/main/CONTRIBUTING.md)
  for the development workflow.
