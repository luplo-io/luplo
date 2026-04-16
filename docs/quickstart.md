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

The Docker path is the fastest way to a working database because it comes
pre-configured with passwordless local auth (`POSTGRES_HOST_AUTH_METHOD=trust`).
Pick whichever fits your setup — but if `lp init` later fails with
`fe_sendauth: no password supplied`, jump to {ref}`quickstart-troubleshooting`.

::::{tab-set}

:::{tab-item} Docker (recommended)
```bash
docker run -d --name luplo-pg \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 5432:5432 \
  postgres:16
```

Connection string for step 2: `postgresql://postgres@localhost:5432/luplo`.
:::

:::{tab-item} Homebrew (macOS)
```bash
brew install postgresql@16
brew services start postgresql@16
createuser -s "$USER"    # role for your shell user, if it doesn't exist
```

Connection string for step 2: `postgresql://$USER@localhost/luplo`.
:::

:::{tab-item} apt (Debian/Ubuntu)
```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo -u postgres createuser -s "$USER"
```

Connection string for step 2: `postgresql://$USER@localhost/luplo`.
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

First export the connection string that matches your Postgres setup —
luplo's default is `postgresql://localhost/luplo`, which works **only** if
your shell user has a passwordless role on the local server. Set
`LUPLO_DB_URL` explicitly to avoid surprises:

::::{tab-set}

:::{tab-item} Docker
```bash
export LUPLO_DB_URL="postgresql://postgres@localhost:5432/luplo"
createdb -h localhost -U postgres luplo
```
:::

:::{tab-item} Homebrew / apt
```bash
export LUPLO_DB_URL="postgresql://$USER@localhost/luplo"
createdb luplo
```

If your role needs a password:
```bash
export LUPLO_DB_URL="postgresql://$USER:PASSWORD@localhost/luplo"
```
:::

::::

## 3. Initialise the project

`lp init` writes a `.luplo` config file in the current directory, runs
Alembic migrations, and seeds the project and actor rows:

```bash
uv run lp init --project myapp --email you@example.com
```

Expected output:

```text
Created .luplo
Running migrations...
Migrations complete.
Seeded project 'myapp'.
Seeded actor you@example.com.
```

After this, every `lp` command reads the project and actor from `.luplo`
automatically — no need to pass `--project` each time. `lp init` is
idempotent; re-running it on the same directory is safe.

:::{warning}
If migrations fail, a `.luplo` file is still written but the schema is
empty. Delete `.luplo` and retry after fixing the DB connection — do
not leave the half-initialised state. See
{ref}`quickstart-troubleshooting`.
:::

## 4. Record your first decision

Open a **work unit** (user-facing grouping of related items that may span
multiple MCP sessions), then attach a decision to it:

```bash
uv run lp work open "Auth rework"

uv run lp items add "Use JWT over session cookies" \
    --type decision \
    --rationale "Stateless auth scales; the session store is an extra dep."
```

Each command prints the created row's ID. The CLI accepts the **first
8 hex characters** as shorthand on later commands, so you don't have to
copy the entire UUID. Ambiguous prefixes are rejected — see
{doc}`reference/cli` for the rules.

## 5. Recall it

Get a project-level brief (active work units + recent items):

```bash
uv run lp brief
```

Example output:

```text
## Active Work Units
- Auth rework (id: a85a4555-...)

## Recent Items
- [decision] Use JWT over session cookies
  Rationale: Stateless auth scales; the session store is an extra dep.
```

Search items with glossary-expanded full-text search:

```bash
uv run lp items search "auth"
```

The query is expanded through your project's glossary — so `"auth"` can
also surface items indexed under `"authentication"` or `"sign-in"` once
those aliases exist. See {doc}`concepts/search-pipeline` for the
four-stage pipeline.

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

Smoke test: ask the client "what did we decide about auth?" — it
should call `luplo_item_search` and cite the decision you just saved.

(quickstart-troubleshooting)=

## Troubleshooting

**`fe_sendauth: no password supplied` / `connection to server … failed: no password supplied`**

: `lp init` tried the default `postgresql://localhost/luplo` but your
  Postgres role requires a password or a different username. Fix it by
  exporting `LUPLO_DB_URL` with the full URL **before** rerunning `lp init`:
  ```bash
  export LUPLO_DB_URL="postgresql://USER:PASSWORD@localhost/luplo"
  rm .luplo                           # clear the half-initialised state
  uv run lp init --project myapp --email you@example.com
  ```
  The Docker path (`POSTGRES_HOST_AUTH_METHOD=trust`) avoids this entirely.

**`createdb: error: ... FATAL: role "<you>" does not exist`**

: Your shell user has no Postgres role. Create one or use a superuser:
  ```bash
  createuser -s "$USER"              # option A: create role for your user
  createdb -U postgres luplo         # option B: use the postgres role
  ```

**`uv: command not found`**

: The installer script adds uv to `~/.local/bin` (or `~/.cargo/bin`) but
  does not touch your shell rc. Add it to `PATH`, or restart the shell
  after installing.

**`lp init` already created `.luplo` — can I re-run it?**

: Yes if the migrations succeeded. If the first run failed partway, delete
  `.luplo` first — otherwise `lp init` will skip the seed step thinking
  the directory is already initialised.

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
