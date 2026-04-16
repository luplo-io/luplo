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

**Secrets are env-only.** These fields refuse to load from TOML or
`.env` if you prefer to keep `.env` out of the picture:

- `LUPLO_JWT_SECRET`
- `LUPLO_ADMIN_PASSWORD_INITIAL`
- `LUPLO_GITHUB_CLIENT_SECRET`
- `LUPLO_GOOGLE_CLIENT_SECRET`

### All server settings

| Setting | Env variable | TOML key | Default |
|---|---|---|---|
| PostgreSQL URL | `LUPLO_DB_URL` | `db_url` | `postgresql://localhost/luplo` |
| JWT secret (HS256) | **`LUPLO_JWT_SECRET`** | — | (required) |
| JWT algorithm | `LUPLO_JWT_ALG` | `jwt_alg` | `HS256` |
| JWT TTL (minutes) | `LUPLO_JWT_TTL_MINUTES` | `jwt_ttl_minutes` | `60` |
| Seed admin email | `LUPLO_ADMIN_EMAIL` | `admin_email` | `""` |
| Seed admin password | **`LUPLO_ADMIN_PASSWORD_INITIAL`** | — | `""` |
| GitHub OAuth client id | `LUPLO_GITHUB_CLIENT_ID` | `github_client_id` / `[github] client_id` | `""` |
| GitHub OAuth secret | **`LUPLO_GITHUB_CLIENT_SECRET`** | — | `""` |
| Google OAuth client id | `LUPLO_GOOGLE_CLIENT_ID` | `google_client_id` / `[google] client_id` | `""` |
| Google OAuth secret | **`LUPLO_GOOGLE_CLIENT_SECRET`** | — | `""` |
| Allowed email domains | `LUPLO_ALLOWED_EMAIL_DOMAINS` | `allowed_email_domains` | `[]` (all) |
| Auto-create users | `LUPLO_AUTO_CREATE_USERS` | `auto_create_users` | `true` |
| Start worker in lifespan | `LUPLO_WORKER_ENABLED` | `worker_enabled` | `false` |
| Public base URL | `LUPLO_BASE_URL` | `base_url` | `http://localhost:8000` |
| OAuth session secret | **`LUPLO_SESSION_SECRET`** | — | `""` |

Bolded env variables are secrets.

### TOML grouping

Both flat and grouped forms are accepted:

```toml
# Flat
github_client_id = "Iv23li..."

# Grouped
[github]
client_id = "Iv23li..."
```

The loader flattens `[github] client_id` into `github_client_id` before
handing the dict to pydantic-settings.

### Fail-fast check

```bash
uv run lp server config-check
```

Validates that `LUPLO_JWT_SECRET` is set, `jwt_ttl_minutes > 0`, and
the admin seed fields are consistent. Exits non-zero with a readable
error list on misconfiguration.

## Keyring

`lp login` stores the JWT in the OS keyring via the
[keyring](https://pypi.org/project/keyring/) library — Keychain on
macOS, Credential Manager on Windows, Secret Service on Linux. There is
no luplo-specific file on disk holding tokens; revoke access by
logging out or removing the entry from the OS keyring.

## Related

- {doc}`../guides/remote-server` — a walkthrough that uses these
  settings end-to-end.
- {doc}`../concepts/architecture` — how client and server configs end
  up pointing at the same PostgreSQL.
