# Running the Local worker

The **worker** drains two kinds of background work that the core
enqueues on every write:

- **Outbound sync jobs** — debounced, per-item work for future
  external-sync targets (Notion, Confluence, …).
- **Glossary term candidates** — terms the LLM pipeline flagged for
  curation, queued into `glossary_terms` with `status='pending'`.

One worker handles both. It wakes via Postgres `LISTEN/NOTIFY`, so
there is no Redis, no Celery, no separate broker to run.

## When to run it

- **Local mode** — start it yourself. Nothing auto-boots.
- **Remote mode** — set `LUPLO_WORKER_ENABLED=true` and the FastAPI
  lifespan hook starts the worker alongside the server. Do not also
  run `lp worker` separately; you'll get duplicate processing.

## Start

```bash
uv run lp worker
```

The worker prints `Worker running. Ctrl+C to stop.` and waits for
`NOTIFY` events. Output stays quiet otherwise — by design, so you can
run it in a background shell without spam.

To background it:

```bash
uv run lp worker &
# or, under a process manager:
nohup uv run lp worker > /var/log/luplo-worker.log 2>&1 &
```

Stop:

```bash
kill %1        # if it's a job in this shell
# or Ctrl+C in the foreground
```

## What it does

### Sync jobs

Every core write that flags an item for external sync lands in
`sync_jobs`. Rows carry:

- The item id.
- A `run_after` timestamp (debounce).
- A retry counter.

The worker drains jobs whose `run_after` has passed, performs the
target-specific write (once sync drivers ship), and updates the row
with success or a retry-scheduled-for-later.

:::{note}
luplo v0.5.x does not yet ship external sync drivers. The queue
infrastructure is in place (tables, worker loop, debounce) so that
Notion / Confluence / etc. drivers can drop in without further schema
changes.
:::

### Glossary candidates

The glossary pipeline (strict-first — see
{doc}`../concepts/search-pipeline`) writes pending terms into
`glossary_terms` when it is **not confident** a term belongs to an
existing group. The worker batches these for the user's curation queue,
accessible via:

```bash
uv run lp glossary pending
uv run lp glossary approve <term-id> --group <group-id>
uv run lp glossary reject  <term-id>
```

`reject` writes to `glossary_rejections`, a permanent "don't suggest
this again" list per group.

## Verifying it is alive

The worker is silent unless something happens. Prove it is working by
creating an item and watching the queue drain:

```bash
# window 1
uv run lp worker

# window 2
uv run lp items add "Test entry" --type knowledge \
    --body "Small note for the worker."
```

You should see a burst of log lines in window 1 as the worker picks up
the enqueued glossary candidates and (where applicable) sync jobs.

## Crash behaviour

- **LISTEN/NOTIFY reconnect.** If Postgres restarts, the worker's
  long-poll will error; the loop reconnects on the next iteration.
- **Missed NOTIFYs.** The worker also polls the queue with a bounded
  back-off, so `NOTIFY` is an optimization, not a correctness
  requirement. A missed wake-up just delays a job by at most the
  poll interval.
- **Exceptions inside a job.** Caught, logged, job's retry counter
  incremented, moved on. No crash of the parent loop.

## Running under a service manager

For systemd:

```ini
# /etc/systemd/system/luplo-worker.service
[Unit]
Description=luplo background worker
After=postgresql.service

[Service]
Type=simple
WorkingDirectory=/opt/luplo
Environment=LUPLO_DB_URL=postgresql://luplo@localhost/luplo
ExecStart=/usr/local/bin/uv run lp worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now luplo-worker
sudo systemctl status luplo-worker
```

## Related

- {doc}`../concepts/architecture` — where the worker sits.
- {doc}`remote-server` — Remote-mode servers boot the worker in-process.
- {doc}`../reference/config` — `LUPLO_WORKER_ENABLED` and friends.
