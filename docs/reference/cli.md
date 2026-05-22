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

Glossary-expanded tsquery search. The query accepts a small
web-search-style dialect (full grammar in
{doc}`../concepts/search-pipeline`):

| Syntax | Meaning |
|---|---|
| `word` | required term (AND) |
| `"exact phrase"` | phrase match |
| `word OR word` | disjunction (literal uppercase `OR`) |
| `-word` | negation |
| `-"exact phrase"` | negated phrase |

Parentheses are not parsed; use De Morgan rewrites
(`(!A & B) & !C` → `B -A -C`). Supports `-n, --limit` (default 10).

### `lp items show <item-id>`

Resolves ID prefixes to the chain head.

## Captures

Captures are raw intake. They are separate from items and do not appear
in item search. Use `lp capture promote` to create a curated item.

Capture input is text-only and BYOLLM: luplo stores caller-provided text
and optional annotations, but it does not transcribe, summarize,
classify, infer sensitivity, or decide what should be promoted.

| Command | Effect |
|---|---|
| `lp capture add TEXT...` | Save raw text to the capture backlog. Requires an actor in local mode. |
| `lp capture ls` | List recent captures, newest first. Hidden by default: discarded and redacted rows. |
| `lp capture find [QUERY...]` | Full-text search over capture text and optional summary. Omit `QUERY` for filter-only search. |
| `lp capture annotate ID` | Store caller-supplied annotation hints. Options: `--summary`, `--sensitivity-hint`, `--signals` JSON object. |
| `lp capture state ID STATE` | Move a capture to `captured`, `backlog`, `review`, `promoted`, or `discarded`. Use `redact` for redaction. |
| `lp capture discard ID` | Mark a capture `discarded` so default list/search hides it. |
| `lp capture redact ID` | Replace text/summary with `[redacted]`, clear signals, and remove original content from capture search. |
| `lp capture promote ID --type TYPE --title TITLE` | Explicitly create a normal item through existing item validation and link it via `capture_promotions`. |

Common options:

| Flag | Description |
|---|---|
| `--state STATE` | Filter `ls` / `find` by capture state. |
| `--include-discarded` | Include discarded rows in `ls` / `find`. |
| `--include-redacted` | Include redacted rows in `ls` / `find`; content stays masked. |
| `--limit N` | Limit result count. |
| `--project`, `--actor` | Promotion uses project + actor to create the target item. |

Promotion is the only path from raw captures into curated memory:

```bash
uv run lp capture add "raw thought from today"
uv run lp capture find "raw thought"
uv run lp capture promote <capture-id> --type knowledge --title "Useful pattern"
uv run lp items search "Useful pattern"
```

## Ideas (legacy)

Deprecated for raw intake. Use capture for unstructured backlog entries.
Ideas remain for compatibility with work-unit-scoped ideation notes.

Existing `lp idea` commands are still available and keep their behavior:

| Command | Effect |
|---|---|
| `lp idea add TEXT... --wu <work-id>` | Append an ideation note to a work unit. If `--wu` is omitted, the active in-progress work unit is used. |
| `lp idea ls --wu <work-id>` | List ideas for a work unit, newest first. |
| `lp idea find [QUERY...]` | Search ideas within a project, optionally narrowed by work unit, author, or time. |
| `lp idea redact <idea-id>` | Mark an idea redacted while preserving the row for compatibility and audit. |

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

## Audit (blast radius)

### `lp impact <item-id>`

Traverse outgoing typed edges (`depends` / `blocks` / `supersedes` /
`conflicts`) from *item-id* and print every reachable item with the
edge type that first reached it. Cycles are broken automatically;
each item appears once, at its shortest-path depth. Traversal stops
at five hops server-side — this is a design principle, not a
performance limit (see {doc}`../concepts/philosophy`).

| Flag | Description |
|---|---|
| `-d`, `--depth` | Max depth, 1–5 (default 5). Values outside the range are rejected by the CLI. |
| `-f`, `--format` | `tree` (default), `flat`, or `json`. All three expose the same payload; JSON is what an LLM should cite. |

Exits 1 when the root item is not found, 2 when depth is out of
range.

## Rule pack

### `lp check`

Run the deterministic rule pack over the project graph. Exits
non-zero if any finding has severity `error`. See
{doc}`checks` for each rule and the `.luplo [checks] disabled_rules`
project-level override.

| Flag | Description |
|---|---|
| `-r`, `--rule` | Repeat to restrict to specific rules by name. Disabled rules are skipped even when named here. |
| `-s`, `--severity` | Display threshold: `error`, `warn` (default), `info`. Does not affect the exit code. |
| `--list` | Print every registered rule with its default severity and exit. |

## Tasks

Tasks live in `items` with `item_type='task'`.

| Command | Effect |
|---|---|
| `lp task add <title> --wu <work-id>` | Create in `proposed`. Optional `-b/--body`, `-s/--system`, `--sort`. |
| `lp task ls --wu <work-id>` | Chain heads ordered by `sort_order`. Optional `-s/--status`. |
| `lp task show <task-id>` | Single task, resolved to chain head. |
| `lp task start <task-id>` | `proposed` → `in_progress`. Enforces one per work unit. |
| `lp task done <task-id>` | `in_progress` → `done`. `--summary` attaches an outcome. `--propose-decision` prints a draft decision item derived from the task; the draft is NOT inserted. |
| `lp task blocked <task-id>` | `in_progress` → `blocked`. Auto-creates a decision item. |
| `lp task skip <task-id>` | Any → `skipped` (terminal). |
| `lp task edit <task-id>` | Edit title / body / `sort_order` via supersede. `--title`, `--body`, `--sort`. Status is preserved — a done task can still have a typo fixed. |
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

## Authentication

The CLI talks to a local PostgreSQL (`LocalBackend`) by default — no
authentication needed. The HTTP server has no built-in auth either;
see {doc}`../guides/remote-server` for how to put your own auth layer
in front.

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
