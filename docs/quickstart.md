# Quickstart

A five-minute tour: install the toolchain, bring up Postgres, initialise a
project, record and recall a decision, and wire luplo into any MCP client.

:::{note}
This is the **Local** mode path — direct PostgreSQL, single user. For the
multi-user **Remote** mode (FastAPI + JWT), see
{doc}`guides/remote-server`.
:::

## Prerequisites

luplo needs three things on your machine: **uv**, **Python 3.12+**, and
**PostgreSQL 15+**. `uv` will fetch Python for you, so only uv and Postgres
require real installation.

### uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Homebrew alternative
brew install uv
```

Verify: `uv --version`.

### PostgreSQL

Pick whichever is easier on your box.

::::{tab-set}

:::{tab-item} Homebrew (macOS)
```bash
brew install postgresql@16
brew services start postgresql@16
```
:::

:::{tab-item} Docker (any OS)
```bash
docker run -d --name luplo-pg \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 5432:5432 \
  postgres:16
```
Connection string for later: `postgresql://postgres@localhost/luplo`.
:::

:::{tab-item} apt (Debian/Ubuntu)
```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```
:::

::::

Verify: `psql --version`.

## 1. Clone and sync

```bash
git clone https://github.com/luplo-io/luplo.git
cd luplo
uv sync
```

`uv sync` reads `pyproject.toml` and `uv.lock`, provisions Python 3.12+ if
needed, creates `.venv/`, and installs every dependency. No manual
`python -m venv` step.

To include the HTTP server (Remote mode) or local vector reranking, add
extras:

```bash
uv sync --extra server          # FastAPI + auth
uv sync --extra vector-local    # sentence-transformers (adds ~500MB)
```

## 2. Create the database

```bash
createdb luplo
```

If your Postgres role is not the default (e.g. Docker's `postgres`), export
the full connection string before the next command:

```bash
export LUPLO_DB_URL="postgresql://postgres@localhost/luplo"
```

See {ref}`quickstart-troubleshooting` below if `createdb` fails.

## 3. Initialise the project

`lp init` writes a `.luplo` config file in the current directory, runs
Alembic migrations, and seeds the project and actor rows:

```bash
uv run lp init --project hearthward --email you@example.com
```

Expected output:

```text
Initialised project 'hearthward' at /path/to/repo/.luplo
Actor: you@example.com
Database: postgresql://localhost/luplo
Migrations: head
```

After this, every `lp` command reads the project and actor from `.luplo`
automatically — no need to pass `--project` each time. `lp init` is
idempotent; re-running it on the same directory is safe.

## 4. Record your first decision

Open a **work unit** (user-facing grouping of related items that may span
multiple MCP sessions), then attach a decision to it:

```bash
uv run lp work open "Vendor system design"

uv run lp items add "Use NPC merchants over player shops" \
    --type decision \
    --rationale "Solo-dev scope; player economy is out of scope for v1."
```

Each command prints the created row's ID — keep them handy for the next
step.

## 5. Recall it

Get a project-level brief (active work units + recent items):

```bash
uv run lp brief
```

Example output:

```text
## Active Work Units
- Vendor system design (id: a85a4555-...)

## Recent Items
- [decision] Use NPC merchants over player shops
  Rationale: Solo-dev scope; player economy is out of scope for v1.
```

Search items with glossary-expanded full-text search:

```bash
uv run lp items search "vendor"
```

The query is expanded through your project's glossary — so `"vendor"` can
also surface items indexed under `"shop"` or `"NPC merchant"` once those
aliases exist. See {doc}`concepts/search-pipeline` for the four-stage
pipeline.

## 6. Start the worker (optional but recommended)

luplo enqueues glossary candidates and sync jobs in the database and drains
them with a worker that listens on `PG LISTEN/NOTIFY`. Without it, queued
jobs still accumulate but will not process.

```bash
uv run lp worker &
```

In **Remote** mode the server's lifespan hook starts the worker for you —
this step is only for Local mode dogfooding.

## 7. Connect an MCP client

luplo ships an [MCP](https://modelcontextprotocol.io) server on stdio, so
**any MCP-compatible client** can call `luplo_brief`, `luplo_item_search`,
`luplo_save_decisions`, and the rest during a session. This includes
Claude Code, Claude Desktop, Cursor, Zed, and custom clients built on the
MCP SDKs.

The launch command is the same everywhere:

```bash
uv run --directory /absolute/path/to/luplo python -m luplo.mcp
```

…with `LUPLO_DB_URL` in the environment. What changes between clients is
only the config file format.

### Example: Claude Code / Claude Desktop

Copy the example config and fill in the absolute path plus your DB URL:

```bash
cp .mcp.json.example .mcp.json
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

- **Claude Code** auto-detects `.mcp.json` in the project root — reopen
  the workspace.
- **Claude Desktop** uses the same `mcpServers` block inside
  `~/Library/Application Support/Claude/claude_desktop_config.json`
  (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows);
  restart Desktop after editing.

### Other clients

Any client following the MCP stdio transport spec can host luplo — pass
the same `command` / `args` / `env` through the client's server-config
shape. See the [MCP clients directory](https://modelcontextprotocol.io/clients)
for the current list and their config formats.

Smoke test: ask the client "what did we decide about vendors?" — it
should call `luplo_item_search` and cite the decision you just saved.

(quickstart-troubleshooting)=

## Troubleshooting

**`createdb: error: connection to server on socket ... failed: FATAL: role "you" does not exist`**

: Your shell user doesn't have a Postgres role yet. Create one, or use
  the `postgres` superuser explicitly:
  ```bash
  createuser -s "$USER"          # option A: create role
  createdb -U postgres luplo     # option B: use postgres role
  ```

**`uv: command not found`**

: The installer script adds uv to `~/.local/bin` (or `~/.cargo/bin`) but
  does not touch your shell rc. Add it to `PATH`, or restart the shell
  after installing.

**`lp init` already created `.luplo` — can I re-run it?**

: Yes. `lp init` is idempotent: migrations are applied with
  `alembic upgrade head` (no-op if already at head), and the project /
  actor seed is upsert-style. Safe to re-run after editing the DB URL.

**I ran `lp worker` but nothing happened.**

: The worker is quiet by default — it only logs when it picks up a job.
  Enqueue something (e.g. add an item) and you should see activity.
  `kill %1` to stop the backgrounded worker.

## Next steps

- {doc}`concepts/philosophy` — why luplo refuses to auto-extract decisions
  and why that is a feature, not a gap.
- {doc}`concepts/architecture` — the three interfaces (CLI / MCP / HTTP)
  and how they share one core.
- {doc}`guides/work-units` — using work units for A→B developer handoff.
- {doc}`reference/cli` — full CLI reference.
- [CONTRIBUTING.md](https://github.com/luplo-io/luplo/blob/main/CONTRIBUTING.md) —
  code standards, test expectations, and the CLA.
