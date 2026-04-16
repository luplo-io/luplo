# CLI reference

`lp` is the human-facing CLI, implemented with
[typer](https://typer.tiangolo.com/). Every command honours `.luplo`
for default `--project` / `--actor`. Invoke any subcommand with
`--help` to see its exact flags.

```bash
uv run lp --help
uv run lp <command> --help
```

## Project bootstrap

### `lp init`

Initialise luplo in the current directory. Writes `.luplo`, runs
Alembic migrations, seeds the project and actor. Idempotent.

| Flag | Description |
|---|---|
| `-p`, `--project` *(required)* | Project ID (e.g. `myapp`). |
| `-e`, `--email` *(required)* | Your email — primary identifier since v0.5.1. |
| `--project-name` | Human-readable project name (defaults to project ID). |
| `--name` | Display name (defaults to email local-part). |
| `--actor-id` | Explicit actor UUID (generated if omitted). |
| `--db-url` | PostgreSQL URL. Env: `LUPLO_DB_URL`. |
| `--server-url` | Optional Remote server URL. Env: `LUPLO_SERVER_URL`. |

### `lp brief`

Active work units + recent decisions for the current project.

| Flag | Description |
|---|---|
| `-p`, `--project` | Override project. |
| `-s`, `--system` | Filter by system. |

## Identifying rows by prefix

Every CLI command that takes an id (`lp items show <item-id>`,
`lp task start <task-id>`, `lp work close <work-id>`, …) accepts either
a full canonical UUID **or** a hex prefix of **at least 8 characters**.
Dashes in the input are ignored, so you can paste `a85a4555` or
`a85a-4555` — both resolve the same way.

If a prefix matches more than one row, the CLI prints the conflicting
ids with a label and exits with status `2`. Type a longer prefix (or
the full UUID) to disambiguate. Prefix length below the 8-char minimum
is rejected up front to avoid accidental wide matches.

The MCP server and the HTTP API both require full UUIDs — prefix
resolution is a CLI-only convenience because LLM and machine callers
typically already have the full id from a previous list response.

## Items

### `lp items add <title>`

Add an item.

| Flag | Description |
|---|---|
| `-t`, `--type` | Item type (default `decision`). One of the seven seeded types or any registered in `item_types`. |
| `-b`, `--body` | Main content. |
| `-r`, `--rationale` | Why this decision. |
| `-s`, `--system` | System to tag. |
| `-p`, `--project` / `-a`, `--actor` | Overrides. |

### `lp items list`

| Flag | Description |
|---|---|
| `-t`, `--type` | Filter by item type. |
| `-s`, `--system` | Filter by system. |
| `-n`, `--limit` | Max rows (default 20). |

### `lp items search <query>`

Glossary-expanded tsquery search. Supports `-n, --limit` (default 10).

### `lp items show <item-id>`

Resolves ID prefixes to the chain head.

## Work units

### `lp work open <title>`

| Flag | Description |
|---|---|
| `-d`, `--desc` | Description. |
| `-s`, `--system` | System to attach. |

### `lp work resume <query>`

Find in-progress work units whose title matches the query.

### `lp work close <work-id>`

| Flag | Description |
|---|---|
| `--status` | `done` (default) or `abandoned`. |
| `-f`, `--force` | Close even if an `in_progress` task remains. |

## Tasks

Tasks live in `items` with `item_type='task'`.

| Command | Effect |
|---|---|
| `lp task add <title> --wu <work-id>` | Create in `proposed`. Optional `-b/--body`, `-s/--system`, `--sort`. |
| `lp task ls --wu <work-id>` | Chain heads ordered by `sort_order`. Optional `-s/--status`. |
| `lp task show <task-id>` | Single task, resolved to chain head. |
| `lp task start <task-id>` | `proposed` → `in_progress`. Enforces one per work unit. |
| `lp task done <task-id>` | `in_progress` → `done`. |
| `lp task blocked <task-id>` | `in_progress` → `blocked`. Auto-creates a decision item. |
| `lp task skip <task-id>` | Any → `skipped` (terminal). |
| `lp task reorder <task-id> [task-id ...]` | In-place `sort_order` update, single audit row. |
| `lp task in-progress --wu <work-id>` | Show the one `in_progress` task, if any. |

## QA checks

QA checks live in `items` with `item_type='qa_check'`.

| Command | Effect |
|---|---|
| `lp qa add <title> -c <coverage>` | Create in `pending`. `--coverage` is required (`auto_partial` / `human_only`). Multi-target via repeated `-t/--task` and `-i/--item`. `--area vfx,ux,...`. |
| `lp qa ls` | With `--task`/`--item` shows only pending QA for that target. Also `--wu`, `-s/--status`. |
| `lp qa show <qa-id>` | Chain-head view. |
| `lp qa start <qa-id>` | `pending` → `in_progress`. |
| `lp qa pass <qa-id>` | `in_progress` → `passed`. |
| `lp qa fail <qa-id>` | `in_progress` → `failed`. |
| `lp qa block <qa-id>` | `in_progress` → `blocked`. |
| `lp qa assign <qa-id> --to <actor-uuid>` | Assign an assignee. |

## Systems

| Command | Effect |
|---|---|
| `lp systems add <name>` | `-d/--desc`, `--depends <system-ids>`. |
| `lp systems list` | All systems for the current project. |

## Glossary

| Command | Effect |
|---|---|
| `lp glossary ls` | Approved groups. `-n, --limit` default 50. |
| `lp glossary pending` | Candidates awaiting curation. |
| `lp glossary approve <term-id> --group <group-id>` | Move a pending term into a group. |
| `lp glossary reject <term-id>` | Permanently reject (written to `glossary_rejections`). |

## Worker

| Command | Effect |
|---|---|
| `lp worker` | Start the foreground worker loop. Quiet until a job fires. |

Do not run this in Remote mode — the server handles it via its
lifespan hook when `LUPLO_WORKER_ENABLED=true`.

## Auth (Remote mode)

| Command | Effect |
|---|---|
| `lp login --server <url>` | Password login (or OAuth placeholder). Stores JWT in OS keyring. |
| `lp logout <server>` | Forget the JWT for that server. |
| `lp whoami <server>` | Show the authenticated actor. |
| `lp token refresh` | Rotate the current JWT. |
| `lp admin set-password --email <email>` | Server-side admin action (argon2id). |

## Server configuration helpers

| Command | Effect |
|---|---|
| `lp server init-secrets` | Print a `.env` snippet with fresh `LUPLO_JWT_SECRET` + `LUPLO_SESSION_SECRET`. |
| `lp server config-check` | Load env + `luplo-server.toml` and report problems. |

## Environment variables honoured

These override the `.luplo` file (which itself overrides defaults):

- `LUPLO_DB_URL`
- `LUPLO_PROJECT`
- `LUPLO_ACTOR_ID`
- `LUPLO_SERVER_URL`

See {doc}`config` for the full list (including server-only variables).

## Related

- {doc}`../guides/work-units`, {doc}`../guides/tasks-and-qa` — CLI
  walkthroughs.
- {doc}`mcp-tools` — the corresponding MCP tool surface.
