# Changelog

All notable changes to luplo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While luplo is in `0.x`, minor-version bumps (`0.x` → `0.(x+1)`) may contain
breaking changes; patch bumps are bug fixes only. Once `1.0.0` is tagged the
public CLI / MCP tool / HTTP surface becomes a stability commitment.

## [Unreleased]

## [0.11.0] - 2026-04-28

A search-and-discovery release. Adds a raw-`tsquery` escape hatch for
LLM-composed complex queries, makes every search result include the item
id (so `luplo_item_show` can actually be called on them), and adds a
`--version` flag.

### Added

- **`lp --version` / `lp -v`** — print the installed `luplo` version and
  exit. First question on every bug report; now answerable without
  `pip show`.
- **`luplo_item_search` raw-tsquery mode** — new `tsquery=` parameter
  that bypasses the simple-dialect parser *and* glossary expansion and
  feeds a raw PostgreSQL `to_tsquery` expression straight to the index.
  Lets callers (especially LLMs) compose the full operator surface:
  `&`, `|`, `!`, `:*` prefix, `<->` phrase distance, parentheses for
  grouping. The legacy `query=` simple dialect (plain words AND, `OR`,
  `"phrase"`, `-negation`, glossary-expanded) is unchanged. When both
  are passed, `tsquery` wins and `query` is ignored. Caller is
  responsible for synonym coverage and syntax validity.
- `Backend.search()` (LocalBackend, RemoteBackend, BackendProtocol) gains
  the same `tsquery: str | None` keyword. RemoteBackend forwards it as
  the `tsquery` query-string parameter on `GET /search`.

### Changed

- **`luplo_item_search` and `luplo_brief` results expose the item id.**
  Search hits now render as `- <title> (id: <12-char-prefix>) [systems]`
  instead of `- [<8-char-prefix>] <title>`. The bracketed prefix was
  easy for both humans and LLMs to misread as a tag/label rather than an
  addressable identifier; the new form names it as an `id` and can be
  passed directly to `luplo_item_show`. `luplo_brief`'s items section
  *also* gets the id (previously it was emitted as
  `- [<item_type>] <title>` with no id at all — undrillable). Both tools
  append a one-line hint at the end pointing callers at
  `luplo_item_show`.

## [0.10.0] - 2026-04-28

A "drop the dead path" release. The bundled FastAPI HTTP server is
removed — it had been frozen since v0.7.0 and never caught up to the
qa / tasks / page_sync surface. Self-host now means "lp + your own
Postgres" (LocalBackend, the default mode); for team or hosted use,
install [luplo-cloud](https://pypi.org/project/luplo-cloud/) which
points lp's RemoteBackend at the managed multi-tenant API.

### Removed

- **`src/luplo/server/`** (was the optional `[project.optional-dependencies]
  server = […]` extra). Routes, `LuploServerSettings`, `luplo-server.toml`
  loader, route handlers (`/projects`, `/items`, `/work-units`,
  `/search`, `/checks`), and the corresponding test suite are gone.
  - `RemoteBackend` (`luplo.core.backend.remote`) **stays** — it's still
    the path lp uses to talk to *any* compatible HTTP server, including
    luplo-cloud's managed API.
  - The `server` optional-dependency group (`fastapi`, `uvicorn`,
    `pydantic-settings`) is removed. Existing installs that depended on
    `luplo[server]` should pin `luplo<0.10` or migrate to luplo-cloud.

### Migration

- **Self-host operators**: switch to local mode (`backend.type = "local"`
  in `.luplo`, with `LUPLO_DB_URL` pointing at your Postgres). This is
  the same code path you were using inside `luplo serve` — no data
  layout change.
- **Anyone wanting multi-tenant or OAuth**: install `luplo-cloud` and
  use the hosted cloud (or run your own copy of luplo-saas if you want
  to fork that — its server has auth + multi-tenancy).

## [0.9.0] - 2026-04-28

A "remote becomes real" release. `lp mcp` now has a working remote backend
path so the OSS CLI can drive the hosted luplo cloud (or any compatible
HTTP server) instead of only a local Postgres.

### Added

- **Remote-mode MCP server** — `lp mcp` now reads `[backend] type = "remote"`
  + `server_url` from `.luplo` and routes tool calls through the configured
  HTTP server instead of dialing local Postgres. Local mode is unchanged
  and remains the default.
- **Two-source token resolution for remote mode** —
  `LUPLO_CLOUD_API_KEY` env var (long-lived `lupk_…` API keys, the path for
  servers / CI / IaC) wins, falling back to the OS keyring entry written by
  `lps login` (short-lived OAuth access JWT, for interactive desktop use).
  When neither is present, a friendly error points at both escape hatches.
  `keyring` is consulted via optional import — installations without it
  silently skip to the env path.
- **`RemoteBackend.query_history()`** — fills the last `Backend` Protocol
  gap so `luplo_history_query` works in remote mode against a server
  exposing `GET /history`.

## [0.8.0] - 2026-04-27

A "surface catches up to core" release. Seven gaps where the CLI/MCP
surface was thinner than the underlying core get filled, plus two
release-blocking invariant bugs in items get fixed. No schema changes.

### Added

- **`lp work ls` + `luplo_work_list` MCP tool** — list every work unit
  in a project, optionally filtered by `--status`. Closes the
  "I just closed it, how do I find it again" gap (`luplo_work_resume`
  only searches `in_progress` titles).
- **`--wu` on `lp items add` and `lp items list`** — attach a new
  item to a work unit, or filter the list to one. The flag accepts
  the same 8-char hex prefix the CLI prints elsewhere; the core layer
  resolves it transparently.
- **Direct glossary curation** — three new commands so users can
  build the glossary by hand instead of waiting for extraction:
  - `lp glossary group create <canonical> [--def TEXT]` — creates the
    group plus a `canonical`-status seed term in one shot. The two
    cannot be created separately at the CLI level (a group without a
    canonical term is a broken intermediate state).
  - `lp glossary add <surface> --group <id> [--canonical]` — adds a
    new term to a group. Default status is `alias`; passing
    `--canonical` demotes the existing canonical to alias and promotes
    this term in the same transaction.
  - `lp glossary term rm <id>` — permanently deletes a term. Removing
    the *last* canonical/alias term in a group cascades the whole
    group (and its rejection records, and any leftover pending /
    rejected siblings). Removing the canonical while aliases still
    exist is refused with `GlossaryGroupHasActiveTermsError`.
- **`GlossaryGroupHasActiveTermsError`** — new `ConflictError`
  subclass surfaced when the cascade-delete refuses (above).

### Changed

- **`_run` translates every `ConflictError` into a clean
  `Error: ...` line + exit 2** instead of letting it surface as a
  Python traceback. Covers `TaskStateTransitionError`,
  `QAStateTransitionError`, `TaskAlreadyInProgressError`, and
  `WorkUnitHasActiveTasksError` uniformly. The bespoke `try` blocks
  in `work close` and `task start` are removed.
- **Uniform prefix resolution across glossary curation** — `approve_term`,
  `merge_groups`, `split_term`, and `reject_term` all resolve hex
  prefixes for term-ids and group-ids via shared helpers; the helpers
  also verify existence for full UUIDs so `None` reliably means "no
  such row" instead of cascading into a downstream FK violation.

### Fixed

- **`core.items.list_items` now returns only chain heads** —
  `NOT EXISTS (SELECT 1 FROM items s WHERE s.supersedes_id = items.id)`
  is part of the WHERE clause. Before, intermediate supersede rows
  leaked into the listing, letting users copy a stale ID into a new
  supersede call and silently break the head-identity contract.
- **`core.items.create_item` / `list_items` resolve `work_unit_id`
  prefixes** — passing the CLI's displayed 8-char prefix as
  `--wu <prefix>` previously raised an `ForeignKeyViolation` traceback
  on insert (and silently returned no rows on the filter path). The
  core helper now resolves the prefix or raises a clean `NotFoundError`.
  Affects MCP `luplo_item_upsert(work_unit_id=...)` for free.

### Internal

- **`Backend` Protocol gains** `create_glossary_group_with_canonical`,
  `add_term_to_group`, and `delete_glossary_term` so future backends
  inherit the contract; the existing `RemoteBackend` does not yet
  implement glossary at all (unchanged from 0.7.x).
- **`_resolve_group` / `_resolve_term`** in `core.glossary` are the
  single point that combines `resolve_uuid_prefix` with an
  existence-check for full UUIDs. Used everywhere glossary IDs cross
  a function boundary.

## [0.7.1] - 2026-04-21

### Added

- **`luplo_item_show` MCP tool** — returns the full body, rationale, and
  metadata of a single item by id. Closes a gap where `luplo_item_search`
  truncated body / rationale to 150 chars and no MCP surface existed to
  read the untruncated text. Accepts a full UUID or ≥8-char hex prefix;
  project-scoped. Soft-deleted items return "not found". The underlying
  `Backend.get_item(id, project_id=...)` already existed; this is
  formatting-only on the MCP side.

## [0.7.0] - 2026-04-20

luplo goes dry. The built-in authentication layer is removed; attribution
is preserved. The library stops pretending to be a hosted product and
goes back to being a library. A deployment that needs authentication
wraps luplo — it does not extend luplo's schema.

### Breaking

- **Authentication removed from core.** The HTTP server no longer
  validates identity. Point luplo at a trusted network (localhost, VPN)
  or put it behind a reverse proxy / auth-proxy that authenticates the
  caller and forwards an ``X-Actor: <uuid>`` header. As a convenience
  for solo use, set ``LUPLO_DEFAULT_ACTOR_ID`` and every write is
  attributed to that actor.
- **Schema**: migration ``0006_drop_auth`` drops
  ``actors.password_hash``, ``actors.is_admin``, ``actors.last_login_at``,
  ``actors.oauth_provider``, ``actors.oauth_subject``, and the
  ``auth_reset_tokens`` table. ``actors`` keeps
  ``{id, name, email, role, external_ids, joined_at}`` — it is now a
  pure attribution registry. All 10 FK columns that reference ``actors``
  stay intact; no item/history/audit data is lost.
- **Deleted code**: ``src/luplo/server/auth/`` (JWT, OAuth + PKCE,
  password hashing, magic-link reset, email sender, domain filter, admin
  seed — 641 LOC across 10 files), ``src/luplo/server/routes/auth.py``
  (``/auth/*`` endpoints).
- **Deleted CLI commands**: ``lp login``, ``lp logout``, ``lp whoami``,
  ``lp token refresh``, ``lp admin set-password``,
  ``lp server init-secrets``, ``lp server config-check``.
- **Deleted settings**: ``LUPLO_JWT_SECRET``, ``LUPLO_JWT_ALG``,
  ``LUPLO_JWT_TTL_MINUTES``, ``LUPLO_ADMIN_EMAIL``,
  ``LUPLO_ADMIN_PASSWORD_INITIAL``, ``LUPLO_GITHUB_CLIENT_ID/SECRET``,
  ``LUPLO_GOOGLE_CLIENT_ID/SECRET``, ``LUPLO_SESSION_SECRET``,
  ``LUPLO_ALLOWED_EMAIL_DOMAINS``, ``LUPLO_AUTO_CREATE_USERS``,
  ``LUPLO_AUTH_DISABLED``. Replaced by a single optional
  ``LUPLO_DEFAULT_ACTOR_ID``.
- **Dependencies removed from ``luplo[server]``**: ``authlib``,
  ``pyjwt``, ``argon2-cffi``, ``jinja2``, ``itsdangerous``. The
  ``luplo[server]`` extras now only pull in ``fastapi``, ``uvicorn``,
  and ``pydantic-settings``. ``keyring`` is removed from core
  dependencies (it only served the deleted token storage).

### Added

- **``GET /ready``** — readiness probe that round-trips a ``SELECT 1``
  against the connection pool. Use this for Kubernetes readiness
  (distinct from ``/health`` which only reports that the process is up).
- **``X-Actor`` request header** — write handlers read the attribution
  actor from this header. Falls back to ``settings.default_actor_id``
  if set; 400 otherwise. Reads do not require it.

### Migration guide

1. Run ``alembic upgrade head`` to apply ``0006_drop_auth``. Nothing
   else changes on your data.
2. If you were running the server with ``LUPLO_AUTH_DISABLED=1``, drop
   that env var; the new server has no auth to disable.
3. If you were running with real auth (JWT + cookies + OAuth), stand
   up a reverse proxy that authenticates users and sets
   ``X-Actor: <uuid>`` downstream. Or — recommended — wrap luplo as a
   library (``from luplo.core.backend.local import LocalBackend``) and
   let your own service own identity.
4. CLI users on the local backend: nothing to change. ``lp init`` still
   writes ``.luplo`` with ``actor.id``; all ``lp`` commands read from
   it unchanged.

## [0.6.2] - 2026-04-18

Hotfix on top of 0.6.1 — `lp login` / `lp whoami` / `lp logout`
crashed on headless Linux (including CI runners) because the
`keyring` library raises `NoKeyringError` when no backend is
available and v0.6.1 did not guard the call sites.

### Fixed

- **`cli.py` keyring call sites** — `_store_token` now catches
  `KeyringError` and prints an actionable message pointing at
  `secret-tool` / desktop session before exiting 1. `_load_token`
  returns `None` when the backend is unavailable (indistinguishable
  from "not logged in" at the caller). `_delete_token` broadens
  `contextlib.suppress` from `PasswordDeleteError` to `KeyringError`.
- **`tests/test_cli.py`** — regression test asserting `lp whoami`
  prints "Not logged in" when the backend is unavailable. This is
  the exact failure that broke CI on the 0.6.1 release commit.

## [0.6.1] - 2026-04-18

A v0.6 follow-up focused on the deterministic rule pack, one residual
logging bug, a wide AI-smell cleanup, and a large test-coverage push.
No schema changes. No public API removals.

### Added

- **Rule pack (`lp check`)** — deterministic checks over the item
  graph with five starter rules: `missing_rationale` (error),
  `undated_retention` (warn), `dangling_edge` (warn),
  `unresolved_conflict` (warn), and `unlinked_policy` (info). Rules
  are SQL + Python only; no LLM, no plugin runtime. Surfaces on
  `lp check [--rule NAME]... [--severity LEVEL] [--list]`, MCP tool
  `luplo_check`, and `GET /checks?project_id=&rule=`. Non-zero CLI
  exit on any `error`-severity finding.
- **`.luplo [checks] disabled_rules`** — per-project rule disable.
  A disabled rule is skipped even when the caller asks for it
  explicitly via `--rule`; project-level disable is the stronger
  signal.
- **`docs/reference/checks.md`** — one section per rule plus
  "what the rule pack is not" (no compliance certification, no
  LLM auditor, no plugin runtime).

### Fixed

- **`core/worker.py:117`** — `fail_sync_job(..., error=str(Exception))`
  was logging the string `"<class 'Exception'>"` because the except
  clause had no binding. Fixed to `except Exception as exc: ...
  str(exc)` so real failure messages reach the sync-job record.

### Changed

- **AI-smell sweep across `src/luplo/`** — removed Step 1/2/3
  scaffolding comments from `cli.py init`, `core/search/pipeline.py
  search`, and `core/glossary.py expand_query`. Private-helper
  docstring compression on `_resolve_head` (tasks + qa),
  `row_to_item`, `_run`, `_revalidate_qa_for`. `_print_task` and
  `_print_qa` dropped their `item: object` + isinstance-assert
  defence in favour of a `item: Item` signature. `errors.py`
  module docstring de-romanised. `_render_impact_json`'s hand-rolled
  `_asdict` walk replaced with stdlib `dataclasses.asdict`.
  `item_types.__all__` no longer re-exports error classes (single
  source: `core.errors`). Misc: redundant inline imports, Korean
  example in a Protocol docstring.

### Tests + CI

- **+119 new tests** (300 → 419): `tests/test_auth_helpers.py` (unit
  coverage for password/jwt/pkce/domain_filter helpers),
  `tests/test_remote_backend.py` (HTTP round-trips through a stubbed
  transport), expanded `tests/test_cli.py` (top-level and subcommand
  groups end-to-end), expanded `tests/test_mcp.py` (smoke → real tool
  invocations with a module-scoped backend fixture), expanded
  `tests/test_auth_routes.py` (paths not covered by password-reset
  work).
- **`codecov.yml`** — project + patch coverage gate with a ratcheting
  threshold so merges that lower coverage fail CI.

## [0.6.0] - 2026-04-17

Narrative v0.6 ships. PyPI version jumps 0.1.0 → 0.6.0 to align the
SemVer axis with the migration-aligned narrative versions in
`docs/project/changelog.md` (v0.5, v0.5.1, v0.5.2, v0.5.3, v0.6). Pre-1.0
version numbers are not dense — skipping 0.2 through 0.5 is deliberate.

### Added

- **Audit (impact analysis)** — `lp impact <id> [--depth N<=5] [--format tree|flat|json]`,
  MCP tool `luplo_impact`, and `GET /items/{id}/impact`. Recursive CTE
  over typed edges (`depends` / `blocks` / `supersedes` / `conflicts`)
  with cycle prevention, project scope, and a five-hop ceiling enforced
  server-side.
- **`lp task edit` + `luplo_task_edit`** — dedicated surface for editing
  a task's title / body / sort_order via supersede (status machine
  preserved).
- **On `task done`, propose a decision draft** — CLI flag
  `--propose-decision` and MCP kwarg `propose_decision` return a
  never-inserted `ItemCreate` draft derived from the completed task.
- **Web-search-style search** — `"exact phrase"`, `word OR word`,
  `-negation`. Glossary expansion applies only to required and OR-group
  terms; phrases and negations are literal.
- **Password reset (magic link)** — `POST /auth/reset-request`
  (no-enumeration), `POST /auth/reset-confirm` (atomic token use +
  password rotation). Argon2id token hashes, 15-minute TTL. New
  `EmailSender` abstraction with logging and SMTP backends.
- **`docs/concepts/positioning.md`** — 8-axis comparison against a
  generic AI-memory tool, plus "when luplo is the wrong tool".
- **`docs/project/roadmap.md`** — public roadmap (Audit →
  Slack `/archive` → Notion webhook → rule pack).
- **`demos/`** — reproducible VHS pipeline with fixed-ID seed data for
  the README's recall and impact gifs.

### Changed

- **Philosophy** restructured around **five refusals**
  (vectors-don't-lead, five-hop, decisions-immutable,
  typed-and-bounded-edges, not-a-general-memory). The three existing
  operational commitments (tool-not-framework, augment-not-replace,
  honesty-over-coverage) moved below as the enforcement layer.
- **Hero tagline** is now "AI memory that survives across sessions,
  teammates, and vendors." — applied to README, docs, `pyproject.toml`
  description, `src/luplo/__init__.py`, and the FastAPI app.
- **Mutator project scope** — `start_task`, `complete_task`, `block_task`,
  `skip_task`, `reorder_tasks`, `start_qa`, `pass_qa`, `fail_qa`,
  `block_qa`, `skip_qa`, `assign_qa` all accept `project_id` kwarg
  threaded into prefix resolution. CLI and MCP surfaces pass the
  current project automatically.
- **CLI error handling** — `_run` now catches `NotFoundError` subclasses
  and prints a clean message instead of a traceback (exposed by the
  scope work above).

### Fixed

- Cross-project prefix collisions could silently mutate a task / QA
  check in the wrong project. Closed by the scope propagation above.

### Migrations

- `0005_auth_reset_tokens` — new table for magic-link reset tokens.

## [0.1.0] - 2026-04-16

Initial public release. luplo is usable end-to-end in Local mode and is
documented at <https://luplo.readthedocs.io>.

### Added

- **PostgreSQL schema** — 12 tables covering projects, actors, work_units,
  systems, items, links, the item_types registry, items_history, audit_log,
  sync_jobs, and the three glossary tables (migrations 0001–0004).
- **CLI (`lp`)** — `init`, `brief`, `worker`, and subcommand groups for
  `items`, `work`, `systems`, `glossary`, `task`, `qa`, plus
  `login`/`logout`/`whoami`/`token`/`admin`/`server` for the Remote backend.
- **MCP server** — stdio adapter for any MCP-compatible client (Claude
  Code / Claude Desktop / Cursor / Zed / custom). Exposes `luplo_brief`,
  `luplo_item_search`, `luplo_item_upsert`, `luplo_work_*`, `luplo_task_*`,
  `luplo_qa_*`, `luplo_page_sync`, `luplo_history_query`, and
  `luplo_save_decisions`.
- **HTTP server** — optional FastAPI + OAuth app under the `server`
  extra, with routes for items, work units, projects, search, and auth.
- **`research` item_type** — cached external references with a required
  `source_url` (enforced by DB `CHECK` and an early app-level guard) and
  a configurable TTL via `expires_at`. Default TTL is 90 days; override
  with `[research] ttl_days = N` in `.luplo`.
- **Documentation** — Sphinx + Read the Docs at
  <https://luplo.readthedocs.io>, including quickstart, concepts,
  guides, reference, and an autoapi-generated API reference.

[Unreleased]: https://github.com/luplo-io/luplo/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/luplo-io/luplo/releases/tag/v0.11.0
[0.10.0]: https://github.com/luplo-io/luplo/releases/tag/v0.10.0
[0.9.0]: https://github.com/luplo-io/luplo/releases/tag/v0.9.0
[0.8.0]: https://github.com/luplo-io/luplo/releases/tag/v0.8.0
[0.7.1]: https://github.com/luplo-io/luplo/releases/tag/v0.7.1
[0.7.0]: https://github.com/luplo-io/luplo/releases/tag/v0.7.0
[0.6.2]: https://github.com/luplo-io/luplo/releases/tag/v0.6.2
[0.6.1]: https://github.com/luplo-io/luplo/releases/tag/v0.6.1
[0.6.0]: https://github.com/luplo-io/luplo/releases/tag/v0.6.0
[0.1.0]: https://github.com/luplo-io/luplo/releases/tag/v0.1.0
