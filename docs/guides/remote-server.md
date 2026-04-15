# Running the Remote server

**Remote mode** is luplo's team setup. A FastAPI server sits in front of
PostgreSQL, issues JWTs to authenticated users, and runs the background
worker alongside the HTTP surface. CLIs and MCP clients on team
members' laptops talk to the server over HTTP instead of hitting the
database directly.

This guide is the end-to-end bring-up.

## When to choose Remote

- Two or more developers share a decision log.
- Your Postgres should not be reachable from every contributor's
  laptop.
- You want password or OAuth auth, not per-user database credentials.

Solo users with a local Postgres should stick with {doc}`local-worker`.

## Prerequisites

- Everything in the {doc}`../quickstart` prereqs.
- `uv sync --extra server` — adds FastAPI, authlib, pyjwt, argon2, etc.
- A Postgres instance the server can reach (loopback in dev, managed
  service in prod).

## 1. Generate server secrets

```bash
uv run lp server init-secrets
```

Prints a `.env` snippet with a fresh `LUPLO_JWT_SECRET` (HS256 signing
key) and `LUPLO_SESSION_SECRET` (OAuth callback state). Save it
somewhere safe — secrets are env-only by design (see below).

## 2. Configure

Server configuration loads from **environment variables** (highest
priority) and an optional **`luplo-server.toml`** file in the working
directory. Sensitive fields are **env-only**:

| Field | Source | Notes |
|---|---|---|
| `LUPLO_DB_URL` | env / TOML | PostgreSQL connection string. |
| `LUPLO_JWT_SECRET` | **env only** | HS256 signing key. |
| `LUPLO_JWT_TTL_MINUTES` | env / TOML | Token lifetime, default 60. |
| `LUPLO_ADMIN_EMAIL` | env / TOML | Optional seed admin address. |
| `LUPLO_ADMIN_PASSWORD_INITIAL` | **env only** | Seed password for the admin. Skipped if omitted. |
| `LUPLO_GITHUB_CLIENT_ID` / `..._SECRET` | env for secret | OAuth auto-enables when both present. |
| `LUPLO_GOOGLE_CLIENT_ID` / `..._SECRET` | env for secret | OAuth auto-enables when both present. |
| `LUPLO_ALLOWED_EMAIL_DOMAINS` | env / TOML | Restrict auto-provision; empty = allow all. |
| `LUPLO_AUTO_CREATE_USERS` | env / TOML | Default `true`. |
| `LUPLO_WORKER_ENABLED` | env / TOML | Start the worker in the lifespan hook. Default `false`. |
| `LUPLO_BASE_URL` | env / TOML | Used for OAuth callback URLs. |
| `LUPLO_SESSION_SECRET` | **env only** | OAuth session signing. |

Example `luplo-server.toml`:

```toml
db_url = "postgresql://luplo@db/luplo"
jwt_ttl_minutes = 120
base_url = "https://luplo.example.com"

worker_enabled = true
auto_create_users = false
allowed_email_domains = ["example.com"]

admin_email = "admin@example.com"

[github]
client_id = "Iv23liXXXX"

[google]
client_id = "123-xyz.apps.googleusercontent.com"
```

And the `.env` (secrets only):

```bash
LUPLO_JWT_SECRET=<from init-secrets>
LUPLO_SESSION_SECRET=<from init-secrets>
LUPLO_ADMIN_PASSWORD_INITIAL=change-me-on-first-login
LUPLO_GITHUB_CLIENT_SECRET=...
LUPLO_GOOGLE_CLIENT_SECRET=...
```

Check configuration before starting the server:

```bash
uv run lp server config-check
```

This loads the merged env + TOML and prints any missing or
inconsistent values without booting FastAPI.

## 3. Run migrations

Point Alembic at the same DB the server will use:

```bash
export LUPLO_DB_URL="postgresql://luplo@db/luplo"
uv run alembic upgrade head
```

## 4. Start the server

```bash
uv run uvicorn luplo.server.app:app --host 0.0.0.0 --port 8000
```

With `LUPLO_WORKER_ENABLED=true` the server's lifespan hook also boots
the background worker — you do **not** run `lp worker` separately in
Remote mode.

## 5. First admin login

If you set `LUPLO_ADMIN_EMAIL` + `LUPLO_ADMIN_PASSWORD_INITIAL`, the
admin is seeded on first boot. Visit `https://<base-url>/auth/login`
and sign in; you'll be asked to change the password immediately.

To reset an actor's password from the box the server runs on:

```bash
uv run lp admin set-password --email user@example.com
```

## 6. Client-side: `lp login`

On a developer's machine, point `.luplo` at the server and log in:

```bash
uv run lp init \
    --project hearthward \
    --email me@example.com \
    --server-url https://luplo.example.com

uv run lp login --server https://luplo.example.com
# prompts for password; stores JWT in OS keyring
```

`lp whoami` verifies the stored token. `lp token refresh` rotates it
before expiry. `lp logout` removes it from the keyring.

After login, every `lp …` call transparently uses the Remote backend —
CLI output shape is unchanged, the backend under the hood is now HTTP.

## 7. Wire MCP clients to the Remote server

An MCP client in Remote mode spawns the same luplo MCP process, but
with `LUPLO_SERVER_URL` set and **no** `LUPLO_DB_URL`. The keyring JWT
from `lp login` is reused automatically.

```json
{
  "mcpServers": {
    "luplo": {
      "command": "uv",
      "args": [
        "run", "--directory", "/abs/path/to/luplo",
        "python", "-m", "luplo.mcp"
      ],
      "env": {
        "LUPLO_SERVER_URL": "https://luplo.example.com"
      }
    }
  }
}
```

## OAuth providers

OAuth auto-enables when both `client_id` and `client_secret` are set
for a provider. Supported: **GitHub**, **Google**. Users authenticated
via OAuth have `password_hash=NULL` in `actors` and can only log in via
their provider.

- `auto_create_users=true` (default) — first OAuth login provisions a
  new `actors` row.
- `auto_create_users=false` — the actor row must already exist
  (admin-provisioned) or the login is rejected.
- `allowed_email_domains` — additional domain allowlist.

## Operational notes

- **Rotation.** To rotate `LUPLO_JWT_SECRET`, restart the server with
  the new value. Existing JWTs become invalid; users re-login.
- **Backups.** Everything is in Postgres — point-in-time-recovery on
  the DB is the backup story. There is no state outside it.
- **Observability.** FastAPI serves its usual access log on stdout;
  the worker logs when it drains jobs. Both are quiet by design.

## Related

- {doc}`local-worker` — Local-mode alternative for solo use.
- {doc}`mcp-client` — client-side config for MCP hosts.
- {doc}`../reference/config` — every config field and env var.
