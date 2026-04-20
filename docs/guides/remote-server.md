# Running the Remote server

**Remote mode** is luplo's shared setup. A FastAPI server sits in front
of PostgreSQL so CLIs and MCP clients on other machines can talk to
luplo over HTTP instead of opening a database connection directly.

luplo's server **does not authenticate callers.** It is a library with
an HTTP adapter, not a hosted product. Deploy it on a trusted network
(localhost, a VPN, or behind a reverse proxy / auth-proxy that does
its own authentication) and use the ``X-Actor`` header to tell luplo
whose UUID to stamp on write operations. If you need real user auth,
OAuth, or multi-tenancy, wrap luplo — do not extend it.

## When to choose Remote

- You want the DB to sit behind a bastion and only the luplo server to
  reach it.
- You are building a SaaS or team product that needs its own identity
  layer, and you want luplo to be the storage/logic piece.
- Multiple dev machines should share the same luplo store without each
  one owning database credentials.

Solo users with a local Postgres should stick with {doc}`local-worker`.

## Prerequisites

- Everything in the {doc}`../quickstart` prereqs.
- `uv sync --extra server` — adds FastAPI, Uvicorn, and pydantic-settings.
- A Postgres instance the server can reach.

## 1. Configure

Server configuration loads from environment variables (highest priority)
and an optional `luplo-server.toml` in the working directory.

| Field | Source | Notes |
|---|---|---|
| `LUPLO_DB_URL` | env / TOML | PostgreSQL connection string. |
| `LUPLO_DEFAULT_ACTOR_ID` | env / TOML | Fallback attribution UUID when a request has no `X-Actor` header. Optional; leave empty to force every write to carry an explicit header. |
| `LUPLO_WORKER_ENABLED` | env / TOML | Start the worker in the lifespan hook. Default `false`. |
| `LUPLO_BASE_URL` | env / TOML | Documentation/presentation URL; not used for auth callbacks (there are none). |

Example `luplo-server.toml`:

```toml
db_url = "postgresql://luplo@db/luplo"
base_url = "https://luplo.example.com"
worker_enabled = true
default_actor_id = "00000000-0000-0000-0000-000000000000"
```

## 2. Run migrations

```bash
export LUPLO_DB_URL="postgresql://luplo@db/luplo"
uv run alembic upgrade head
```

## 3. Start the server

```bash
uv run uvicorn luplo.server.app:app --host 127.0.0.1 --port 8000
```

Binding to `127.0.0.1` is the intended default — the server has no
authentication, so it must not be reachable directly from the public
internet. Put your own auth layer in front of it (see below).

With `LUPLO_WORKER_ENABLED=true`, the lifespan hook also boots the
background worker — you do **not** run `lp worker` separately in Remote
mode.

## 4. Probes

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness. Reports only that the process is up. |
| `GET /ready` | Readiness. Round-trips `SELECT 1` through the pool. Use this as the Kubernetes readiness probe. |

## 5. Attribution (the `X-Actor` header)

Every write handler requires an attribution actor UUID. Reads do not.

```
POST /items
X-Actor: 71785d65-57a8-4951-8bc7-97888b5755f6
Content-Type: application/json
{ ... }
```

Resolution order:

1. `X-Actor: <uuid>` request header.
2. `settings.default_actor_id` (`LUPLO_DEFAULT_ACTOR_ID`).
3. HTTP 400 if neither is present.

The actor referenced by `X-Actor` must exist in `actors`. Provision it
once with the CLI (`lp init`) or via SQL before its first use.

## 6. Putting your own auth in front

Since luplo trusts the request caller, the network layer has to make
that trust meaningful. Two common shapes:

### Shape A — reverse proxy auth

An auth-proxy (oauth2-proxy, Caddy with `forward_auth`, nginx
`auth_request`, Pomerium, Tailscale Funnel, etc.) authenticates the
human in front of luplo. The proxy maps the authenticated user to a
luplo actor UUID and injects it:

```nginx
location / {
    auth_request /_auth;
    proxy_set_header X-Actor $authenticated_actor_uuid;
    proxy_pass http://127.0.0.1:8000;
}
```

### Shape B — import luplo as a library

For SaaS or team products, skip luplo's HTTP layer entirely. Use it as
a Python library inside your own FastAPI (or any) app:

```python
from fastapi import FastAPI, Depends
from luplo.core.backend.local import LocalBackend
from luplo.core.db import create_pool

app = FastAPI()  # your app, your auth

async def my_backend() -> LocalBackend:
    return LocalBackend(pool)  # pool scoped per-tenant as you prefer

@app.post("/memories")
async def create(body, user = Depends(my_auth), b = Depends(my_backend)):
    return await b.create_item(..., actor_id=user.id)
```

This is the intended path for multi-tenant deployments. luplo has no
opinion about organisations, users, or sessions — all of that belongs
in your wrapper.

## 7. Wire MCP clients to the Remote server

An MCP client in Remote mode spawns the same luplo MCP process but
with `LUPLO_SERVER_URL` set and **no** `LUPLO_DB_URL`.

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

If your reverse-proxy requires a token for service-to-service calls,
wire that into the MCP client's environment alongside
`LUPLO_SERVER_URL` — luplo's HTTP client forwards whatever Authorization
header your wrapper expects.

## Operational notes

- **Backups.** Everything is in Postgres — point-in-time recovery on
  the DB is the backup story. There is no state outside it.
- **Observability.** FastAPI serves its usual access log on stdout;
  the worker logs when it drains jobs. Both are quiet by design.

## Related

- {doc}`local-worker` — Local-mode alternative for solo use.
- {doc}`mcp-client` — client-side config for MCP hosts.
- {doc}`../reference/config` — every config field and env var.
