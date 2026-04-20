# Configuration reference

luplo has **two** configuration surfaces: a client-side one used by the
CLI and MCP server, and a server-side one used only by the Remote-mode
FastAPI app. They are deliberately separated — the server never imports
the client module, so adding a field to one does not touch the other.

## Client: `.luplo` file + env vars

### Resolution order

Highest priority wins:

1. CLI flag (`--project`, `--actor`, `--db-url`, …)
2. Environment variable (`LUPLO_*`)
3. `.luplo` file (walked up from the current working directory)
4. Built-in defaults

### `.luplo` file

TOML. Created by `lp init`, editable by hand:

```toml
[backend]
type      = "local"                            # or "remote"
db_url    = "postgresql://localhost/luplo"
server_url = "https://luplo.example.com"       # only for remote

[project]
id   = "myapp"
name = "MyApp"

[actor]
id    = "<uuid4>"
name  = "Ryan"
email = "ehanyul99@gmail.com"

[research]
ttl_days = 90                                   # expiry for research items
```

`find_config_file()` walks up from CWD, so any subdirectory of the
project inherits the root `.luplo`.

### Environment variables (client)

| Variable | Replaces | Notes |
|---|---|---|
| `LUPLO_DB_URL` | `.luplo/backend.db_url` | Used in Local mode. |
| `LUPLO_SERVER_URL` | `.luplo/backend.server_url` | Used in Remote mode. |
| `LUPLO_PROJECT` | `.luplo/project.id` | Override the active project. |
| `LUPLO_ACTOR_ID` | `.luplo/actor.id` | Override the active actor. |

### Defaults

- `db_url`: `postgresql://localhost/luplo`
- `backend_type`: `local`
- `research_ttl_days`: `90`

## Server: env + `luplo-server.toml`

The Remote server (FastAPI, started via `uvicorn luplo.server.app:app`)
reads configuration via [pydantic-settings]. Priority:

1. Environment variables (`LUPLO_*`)
2. `.env` file in the working directory (auto-loaded by pydantic-settings)
3. `luplo-server.toml` in the working directory
4. Defaults

The server does not authenticate callers — it trusts the network layer
in front of it. See {doc}`../guides/remote-server` for the shape.

### All server settings

| Setting | Env variable | TOML key | Default |
|---|---|---|---|
| PostgreSQL URL | `LUPLO_DB_URL` | `db_url` | `postgresql://localhost/luplo` |
| Default attribution actor | `LUPLO_DEFAULT_ACTOR_ID` | `default_actor_id` | `""` (no fallback — every write must carry `X-Actor`) |
| Start worker in lifespan | `LUPLO_WORKER_ENABLED` | `worker_enabled` | `false` |
| Public base URL | `LUPLO_BASE_URL` | `base_url` | `http://127.0.0.1:8000` |

### Attribution (`X-Actor` header)

Every write handler resolves the actor id in this order:

1. `X-Actor: <uuid>` on the request.
2. `LUPLO_DEFAULT_ACTOR_ID` if set.
3. HTTP 400 otherwise.

Reads do not require it. The actor referenced by `X-Actor` must exist
in the `actors` table; provision it with `lp init` or directly in SQL.

## Related

- {doc}`../guides/remote-server` — a walkthrough that uses these
  settings end-to-end.
- {doc}`../concepts/architecture` — how client and server configs end
  up pointing at the same PostgreSQL.
